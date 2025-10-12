#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generación de imágenes con Google Gemini con reintentos, backoff exponencial y CLI.

Requisitos:
- python >= 3.8
- pip install google-generativeai pillow
- Variable de entorno: GOOGLE_API_KEY

Notas:
- El nombre del modelo debe corresponder a uno que admita salida de imagen en tu cuenta.
- Por defecto se usa "gemini-2.5-flash-image" (cámbialo con --model o GOOGLE_GEMINI_MODEL).

Uso rápido:
    export GOOGLE_API_KEY="tu_clave"
    python gemini_image_gen.py --prompt "una clase de matemáticas con estudiantes y una pizarra" --out-dir imagenes --format PNG

Parámetros CLI:
    --prompt        Descripción de la imagen a generar (str)
    --out-dir       Directorio de salida (str, por defecto: imagenes_test)
    --model         Nombre del modelo (str, por defecto: env GOOGLE_GEMINI_MODEL o 'gemini-2.5-flash-image')
    --format        Formato de salida [PNG|JPEG|WEBP] (str, por defecto: PNG)
    --max-retries   Reintentos máximos (int, por defecto: 8)
    --min-delay     Espera mínima entre llamadas, en segundos (float, por defecto: 6.0)
    --max-delay     Espera máxima entre llamadas, en segundos (float, por defecto: 9.0)
    --seed          Semilla opcional (int)

Salida:
    Imprime por stdout la ruta del archivo generado y registra eventos con logging.

"""

import os
import sys
import time
import base64
import random
import logging
import argparse
from io import BytesIO
from typing import Optional
from pathlib import Path
from PIL import Image

import google.generativeai as genai

# ---------------------------------
# Logging
# ---------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gemini-image-gen")


# ---------------------------------
# Utilidades de extracción
# ---------------------------------
def _extract_image_bytes(response) -> Optional[bytes]:
    """Extrae los bytes de imagen de la respuesta del SDK.
    Recorre candidates -> content -> parts -> inline_data.data, decodifica Base64 si procede.
    Devuelve None si no encuentra binarios.
    """
    try:
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if not inline:
                    continue
                data = getattr(inline, "data", None)
                if not data:
                    continue
                if isinstance(data, str):
                    try:
                        return base64.b64decode(data)
                    except Exception:
                        # Fallback raro: intentar bytes directos
                        try:
                            return data.encode("latin1")
                        except Exception:
                            pass
                elif isinstance(data, (bytes, bytearray)):
                    return bytes(data)
        return None
    except Exception:
        return None


# ---------------------------------
# Función principal
# ---------------------------------
def generate_image_with_gemini(
    prompt: str,
    out_dir: str = "imagenes",
    model_name: str = None,
    out_format: str = "PNG",  # PNG | JPEG | WEBP
    max_retries: int = 8,
    min_delay_s: float = 6.0,
    max_delay_s: float = 9.0,
    seed: Optional[int] = None,
) -> str:
    """Genera una imagen con Gemini respetando límites de cuota con backoff y jitter.

    Parameters
    ----------
    prompt : str
        Descripción de la escena/ilustración a generar.
    out_dir : str
        Directorio de salida.
    model_name : str
        Nombre del modelo con capacidad de imagen. Si None, usa env GOOGLE_GEMINI_MODEL
        o el valor por defecto "gemini-2.5-flash-image".
    out_format : str
        Formato de salida: "PNG" (por defecto), "JPEG" o "WEBP".
    max_retries : int
        Reintentos ante errores transitorios (429/503, etc.).
    min_delay_s, max_delay_s : float
        Ventana de espera aleatoria entre llamadas para respetar RPM.
    seed : Optional[int]
        Semilla opcional (si el modelo la respeta por prompt; no garantizado).

    Returns
    -------
    str
        Ruta del archivo de imagen generado.
    """

    # Validar API key
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("Falta GOOGLE_API_KEY en el entorno.")

    # Configurar SDK
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        raise RuntimeError(f"No se pudo configurar Google Generative AI: {e}")

    # Modelo
    model_name = (
        model_name
        or os.environ.get("GOOGLE_GEMINI_MODEL")
        or "gemini-2.5-flash-image"
    )

    # Validar formato
    of = out_format.upper().strip()
    if of not in {"PNG", "JPEG", "WEBP"}:
        raise ValueError("out_format debe ser PNG, JPEG o WEBP")

    # Preparar salida
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    out_path = str(out_dir_path / f"img_{os.urandom(8).hex()}.{of.lower()}")

    # Instanciar modelo
    model = genai.GenerativeModel(model_name)

    # Prompt compuesto
    guidelines = (
        "Genera una ilustración digital con estilo limpio y colores equilibrados. "
        "Evita logotipos, marcas de agua y texto embebido."
    )
    if seed is not None:
        guidelines += f" Mantén una composición coherente (seed sugerida: {seed})."
    full_prompt = f"{guidelines} Debe representar: {prompt}".strip()

    # Reintentos con backoff exponencial + jitter
    for attempt in range(1, max_retries + 1):
        delay = random.uniform(min_delay_s, max_delay_s)
        log.info(f"Esperando {delay:.1f}s antes del intento {attempt}…")
        time.sleep(delay)

        try:
            log.info(f"Solicitando imagen a '{model_name}' (intento {attempt})…")
            response = model.generate_content(full_prompt)

            img_bytes = _extract_image_bytes(response)
            if not img_bytes:
                raise ValueError("La respuesta no contenía datos de imagen válidos (inline_data).")

            # Guardado con Pillow
            with Image.open(BytesIO(img_bytes)) as im:
                # Normalización de modos
                if of == "JPEG" and im.mode in ("RGBA", "LA"):
                    im = im.convert("RGB")
                elif im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGB")
                im.save(out_path, of)

            log.info(f"Imagen generada correctamente: {out_path}")
            return out_path

        except Exception as e:
            err_text = str(e).lower()
            is_quota = ("429" in err_text) or ("quota" in err_text) or ("resourceexhausted" in err_text)
            is_unavail = ("503" in err_text) or ("temporarily" in err_text) or ("service unavailable" in err_text)

            if is_quota or is_unavail:
                backoff = min(5 * (2 ** (attempt - 1)), 300)  # 5s, 10s, 20s, ... máx 300s
                kind = "Cuota excedida" if is_quota else "Servicio no disponible"
                log.warning(f"{kind}. Reintentando en {backoff}s… (intento {attempt}/{max_retries})")
                time.sleep(backoff)
                continue

            log.error(f"Error inesperado en intento {attempt}: {e}")
            if attempt == max_retries:
                raise
            time.sleep(10)

    raise RuntimeError("No se pudo generar la imagen tras múltiples intentos.")


# ---------------------------------
# CLI
# ---------------------------------
def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Genera una imagen con Google Gemini.")
    p.add_argument("--prompt", required=False, default="una escena sencilla de ejemplo",
                   help="Descripción de la imagen a generar.")
    p.add_argument("--out-dir", default="imagenes_test", help="Directorio de salida.")
    p.add_argument("--model", dest="model_name", default=None,
                   help="Nombre del modelo (por defecto: env GOOGLE_GEMINI_MODEL o 'gemini-2.5-flash-image').")
    p.add_argument("--format", dest="out_format", default="PNG", choices=["PNG", "JPEG", "WEBP"],
                   help="Formato de la imagen de salida.")
    p.add_argument("--max-retries", type=int, default=8, help="Reintentos máximos.")
    p.add_argument("--min-delay", dest="min_delay_s", type=float, default=6.0,
                   help="Espera mínima entre llamadas (s).")
    p.add_argument("--max-delay", dest="max_delay_s", type=float, default=9.0,
                   help="Espera máxima entre llamadas (s).")
    p.add_argument("--seed", type=int, default=None, help="Semilla (opcional).")
    return p


def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        log.error("Falta GOOGLE_API_KEY. Exporta la variable de entorno antes de ejecutar.")
        sys.exit(1)

    args = _build_cli().parse_args()

    try:
        path = generate_image_with_gemini(
            prompt=args.prompt,
            out_dir=args.out_dir,
            model_name=args.model_name,
            out_format=args.out_format,
            max_retries=args.max_retries,
            min_delay_s=args.min_delay_s,
            max_delay_s=args.max_delay_s,
            seed=args.seed,
        )
        print(path)
    except Exception:
        log.exception("Fallo en la generación de imagen")
        sys.exit(2)


if __name__ == "__main__":
    main()

