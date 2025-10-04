#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente mínimo para un endpoint OpenAI-compatible (ImageRouter).
Genera una imagen a partir de un prompt y la guarda en disco.

Requiere:
  - IMAGEROUTER_BASE_URL (env): p.ej. https://<tu-router>
    *Puede ser raíz (https://host) o ya incluir /v1 o /v1/openai*
  - IMAGEROUTER_API_KEY  (env): API key si la instancia la pide (opcional)
  - IMAGEROUTER_IMAGES_ENDPOINT (env, opcional):
      Ruta del endpoint de imágenes si quieres forzarla.
      Ejemplos: 
        "/v1/images/generations" (por defecto)
        "/v1/openai/images/generations"
        "images/generations" (sin barra inicial)
"""

import os
import time
import base64
import json
import pathlib
from typing import Optional

import requests


class ImageRouterError(Exception):
    pass


def _rand_name(n=8) -> str:
    import secrets, string
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(n))


def _join_url(base: str, path: str) -> str:
    base = base.rstrip('/')
    if not path:
        return base
    if path.startswith('/'):
        return base + path
    return base + '/' + path


def _resolve_images_endpoint(base_url: str) -> str:
    """Resuelve el endpoint final de imágenes evitando duplicados.
    Estrategia:
      1) Si IMAGEROUTER_IMAGES_ENDPOINT está definido => usarlo literalmente sobre base_url.
      2) Si base_url ya termina en '/images/generations' => usar base_url tal cual.
      3) Si base_url contiene '/v1/openai' => añadir '/images/generations'.
      4) Si base_url contiene '/v1' => añadir '/images/generations'.
      5) En cualquier otro caso => añadir '/v1/images/generations'.
    """
    forced = os.getenv('IMAGEROUTER_IMAGES_ENDPOINT', '').strip()
    if forced:
        return _join_url(base_url, forced)

    low = base_url.rstrip('/').lower()
    if low.endswith('/images/generations'):
        return base_url.rstrip('/')
    if '/v1/openai' in low:
        return _join_url(base_url, '/images/generations')
    if '/v1' in low:
        return _join_url(base_url, '/images/generations')
    return _join_url(base_url, '/v1/images/generations')


def generate_image_via_imagerouter(
    prompt: str,
    out_dir: str,
    model: str = "black-forest-labs/FLUX-1-schnell:free",
    size: str = "1024x768",
    guidance: float = 4.0,
    steps: int = 20,
    seed: Optional[int] = None,
    timeout: int = 120
) -> str:
    """
    Llama a un endpoint OpenAI-style y guarda un PNG/JPG en out_dir.
    Devuelve la ruta final creada.

    Ajusta 'model' a otro gratuito si lo prefieres (p.ej. "stabilityai/sdxl-turbo:free"),
    según la lista de modelos de la instancia que uses.
    """
    base_url = os.getenv("IMAGEROUTER_BASE_URL", "").rstrip("/")
    api_key = os.getenv("IMAGEROUTER_API_KEY", "")
    if not base_url:
        raise ImageRouterError("Falta IMAGEROUTER_BASE_URL (variable de entorno).")

    endpoint = _resolve_images_endpoint(base_url)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": 1,
        # Campos que algunas pasarelas aceptan:
        "guidance_scale": guidance,
        "steps": steps,
    }
    if seed is not None:
        payload["seed"] = seed

    # Backoff suave para 429/5xx
    backoff = [0, 1, 2, 4]
    last_exc = None
    for wait in backoff:
        if wait:
            time.sleep(wait)
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 429:
                last_exc = ImageRouterError(f"Rate limit 429 en {endpoint}: {resp.text[:200]}")
                continue
            if 500 <= resp.status_code < 600:
                last_exc = ImageRouterError(f"Upstream {resp.status_code} en {endpoint}: {resp.text[:200]}")
                continue
            if resp.status_code >= 400:
                # Mensaje explícito con el endpoint real usado (para depurar 404)
                raise ImageRouterError(f"HTTP {resp.status_code} en {endpoint}: {resp.text[:500]}")

            data = resp.json()
            # OpenAI images: data[0].b64_json o data[0].url
            img_b64 = None
            img_url = None
            if "data" in data and data["data"]:
                entry = data["data"][0]
                img_b64 = entry.get("b64_json")
                img_url = entry.get("url")

            pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
            fname = f"img_{_rand_name()}.png"
            out_path = str(pathlib.Path(out_dir, fname))

            if img_b64:
                with open(out_path, "wb") as f:
                    f.write(base64.b64decode(img_b64))
                return out_path

            if img_url:
                r = requests.get(img_url, timeout=timeout)
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return out_path

            raise ImageRouterError(f"Respuesta sin imagen reconocible en {endpoint}: {json.dumps(data)[:800]}")

        except requests.RequestException as e:
            last_exc = e
            continue

    raise ImageRouterError(f"No se pudo generar imagen tras reintentos: {last_exc}")
