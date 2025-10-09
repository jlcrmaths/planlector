#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, time, pathlib, random
from io import BytesIO
from PIL import Image
import google.generativeai as genai

# --- CONFIGURACIÓN GOOGLE GEMINI ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    print("🚨 ERROR: Falta GOOGLE_API_KEY. No se puede generar imágenes con Gemini.")
    sys.exit(1)

try:
    genai.configure(api_key=GOOGLE_API_KEY)
    print("✅ Gemini configurado correctamente.")
except Exception as e:
    print(f"🚨 ERROR: clave de API inválida -> {e}")
    sys.exit(1)


# --- FUNCIÓN PRINCIPAL ---
def generate_image_with_gemini(prompt: str, out_dir: str, retries: int = 8) -> str:
    """
    Genera una imagen con Gemini respetando los límites de cuota (sin placeholders).
    Reintenta automáticamente cuando recibe un error 429.
    """
    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(pathlib.Path(out_dir, f"img_{os.urandom(8).hex()}.png"))

    model = genai.GenerativeModel("gemini-2.5-flash-image")

    for attempt in range(1, retries + 1):
        try:
            # 🔹 Pausa natural entre peticiones (respetar RPM ≈10)
            delay = random.uniform(6, 9)
            print(f"⏳ Esperando {delay:.1f}s antes del intento {attempt}...")
            time.sleep(delay)

            print(f"🎨 Solicitando imagen a Gemini (intento {attempt}): {prompt[:90]}...")
            full_prompt = (
                f"Genera una ilustración digital educativa, con estilo limpio y colores vivos. "
                f"Debe representar: {prompt}. No incluyas texto ni marcas de agua."
            )
            response = model.generate_content(full_prompt)

            # --- Buscar datos de imagen ---
            image_data = None
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        image_data = part.inline_data.data
                        break

            if not image_data:
                raise ValueError("La respuesta no contenía imagen válida.")

            # --- Guardar imagen ---
            image = Image.open(BytesIO(image_data))
            image.convert("RGB").save(out_path, "PNG")
            print(f"✅ Imagen generada correctamente: {out_path}")
            return out_path

        except Exception as e:
            err = str(e).lower()
            if "429" in err or "quota" in err:
                wait = min(60 * attempt, 300)
                print(f"⚠️ Cuota de Gemini excedida. Esperando {wait}s antes de reintentar...")
                time.sleep(wait)
                continue
            elif "503" in err or "temporarily" in err:
                wait = 15 * attempt
                print(f"⚠️ Servicio temporalmente no disponible. Reintentando en {wait}s...")
                time.sleep(wait)
                continue
            else:
                print(f"🚨 Error inesperado en intento {attempt}: {e}")
                if attempt == retries:
                    raise
                time.sleep(10)

    raise RuntimeError("No se pudo generar la imagen tras múltiples intentos.")


# --- PRUEBA LOCAL ---
if __name__ == "__main__":
    img = generate_image_with_gemini(
        "una clase de matemáticas con estudiantes y una pizarra llena de fórmulas",
        "imagenes_test"
    )
    print("✅ Prueba finalizada. Imagen:", img)

