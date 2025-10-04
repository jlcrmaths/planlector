#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente multiproveedor para generación de imágenes:

Proveedores soportados (vía variable de entorno IMAGEROUTER_PROVIDER):
- 'aihorde'     -> API pública gratuita (voluntariado): https://aihorde.net (por defecto de este repo)
- 'huggingface' -> Hugging Face Inference API (devuelve bytes)
- 'openai'      -> Cualquier router OpenAI-style con /v1/images/generations

ENV requeridas (según proveedor):
  IMAGEROUTER_PROVIDER = aihorde | huggingface | openai
  IMAGEROUTER_BASE_URL = 
      aihorde:  https://aihorde.net/api/v2
      huggingface: https://api-inference.huggingface.co/models/<model_id>
      openai:   https://<router>   (el cliente añade /v1/images/generations si falta)
  IMAGEROUTER_API_KEY  =
      aihorde:  tu key o '0000000000' (anónimo, funciona con menor prioridad)
      huggingface: token 'hf_...'
      openai:   token del router (si aplica)
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


class ImageRouterBillingRequired(ImageRouterError):
    pass


def _rand_name(n=8) -> str:
    import secrets, string
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(n))


# ---------- OpenAI-style ----------
def _post_openai_images(endpoint: str, api_key: str, payload: dict, timeout: int) -> bytes:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)

    if resp.status_code == 403:
        # Algunos routers retornan un mensaje pidiendo depósito
        try:
            data = resp.json()
            msg = (data.get("error", {}).get("message") or "")[:500]
        except Exception:
            msg = resp.text[:500]
        if "deposit" in msg.lower():
            raise ImageRouterBillingRequired(msg)

    if resp.status_code >= 400:
        raise ImageRouterError(f"HTTP {resp.status_code} en {endpoint}: {resp.text[:500]}")

    data = resp.json()
    if "data" in data and data["data"]:
        entry = data["data"][0]
        if entry.get("b64_json"):
            return base64.b64decode(entry["b64_json"])
        if entry.get("url"):
            r = requests.get(entry["url"], timeout=timeout)
            r.raise_for_status()
            return r.content

    raise ImageRouterError("Respuesta sin imagen reconocible (OpenAI-style).")


# ---------- Hugging Face (bytes directos) ----------
def _post_hf_bytes(endpoint: str, api_key: str, prompt: str, timeout: int) -> bytes:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"inputs": prompt}

    resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)

    # warming-up / edge timeout
    if resp.status_code in (503, 524):
        time.sleep(2)
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)

    if resp.status_code >= 400:
        raise ImageRouterError(f"HF HTTP {resp.status_code} en {endpoint}: {resp.text[:500]}")

    return resp.content


# ---------- AI Horde (HTTP directo, gratis) ----------
def _nearest_multiple_64(x: int) -> int:
    if x < 64:
        return 64
    lo = (x // 64) * 64
    hi = lo + 64
    # elegir el más cercano
    return hi if (x - lo) > (hi - x) else lo


def _post_aihorde_http(base_url: str, prompt: str, api_key: str,
                       width: int, height: int, steps: int, timeout: int) -> bytes:
    """
    Flujo oficial (asincrónico) de AI Horde:
      POST  {base}/generate/async      -> id
      GET   {base}/generate/check/{id} -> done?
      GET   {base}/generate/status/{id}-> generations[0].img (base64)
    Cabeceras requeridas: 'apikey' y se recomienda 'Client-Agent'.

    Doc integración (endpoints /async, /check, /status):
      https://github.com/Haidra-Org/AI-Horde/blob/main/README_integration.md
    Servicio y key anónima '0000000000' (10 ceros) disponible:
      https://stablehorde.net / https://aihorde.net
    """

    base = base_url.rstrip('/') or "https://aihorde.net/api/v2"
    key = api_key or "0000000000"  # anónimo permitido (menor prioridad)
    headers = {
        "apikey": key,
        "Client-Agent": os.getenv("CLIENT_AGENT", "MathGym/1.0 (+https://github.com/mathgymdcr)")
    }

    # Las resoluciones suelen funcionar mejor en múltiplos de 64
    w = _nearest_multiple_64(max(64, min(width, 1536)))
    h = _nearest_multiple_64(max(64, min(height, 1536)))

    payload = {
        "prompt": prompt,
        "params": {
            "width": w,
            "height": h,
            "steps": max(1, min(steps, 20)),  # mantener bajo para colas rápidas
            "cfg_scale": 5.0
        },
        "n": 1,
        "r2": True,          # permitir URLs R2 si aplica (optimiza entrega)
        "nsfw": False,
        "censor_nsfw": True
        # "models": ["Deliberate"]  # opcional: dejar que Horde elija el modelo disponible
    }

    # 1) Encolar
    r = requests.post(f"{base}/generate/async", headers=headers, json=payload, timeout=timeout)
    if r.status_code >= 400:
        raise ImageRouterError(f"AI Horde async HTTP {r.status_code}: {r.text[:300]}")
    job = r.json()
    req_id = job.get("id")
    if not req_id:
        raise ImageRouterError(f"AI Horde: respuesta sin id: {json.dumps(job)[:300]}")

    # 2) Polling
    t0 = time.time()
    while True:
        rc = requests.get(f"{base}/generate/check/{req_id}", timeout=timeout)
        if rc.status_code >= 400:
            raise ImageRouterError(f"AI Horde check HTTP {rc.status_code}: {rc.text[:300]}")
        chk = rc.json()
        if chk.get("done") == 1:
            break
        if time.time() - t0 > timeout:
            raise ImageRouterError("AI Horde: timeout esperando la generación.")
        time.sleep(2)

    # 3) Recuperar resultados
    rs = requests.get(f"{base}/generate/status/{req_id}", timeout=timeout)
    if rs.status_code >= 400:
        raise ImageRouterError(f"AI Horde status HTTP {rs.status_code}: {rs.text[:300]}")
    st = rs.json()
    gens = st.get("generations") or []
    if not gens or not gens[0].get("img"):
        raise ImageRouterError("AI Horde: sin 'generations' o 'img' en la respuesta.")
    b64 = gens[0]["img"]
    return base64.b64decode(b64)


def generate_image_via_imagerouter(
    prompt: str,
    out_dir: str,
    model: str = "aihorde",
    size: str = "1024x768",
    guidance: float = 4.0,
    steps: int = 12,
    seed: Optional[int] = None,
    timeout: int = 180
) -> str:
    """
    Devuelve la RUTA de un PNG guardado en out_dir.
    """
    base_url = os.getenv("IMAGEROUTER_BASE_URL", "").rstrip("/")
    api_key = os.getenv("IMAGEROUTER_API_KEY", "")
    provider = os.getenv("IMAGEROUTER_PROVIDER", "aihorde").strip().lower()

    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(pathlib.Path(out_dir, f"img_{_rand_name()}.png"))

    if provider == "aihorde":
        if not base_url:
            base_url = "https://aihorde.net/api/v2"
        try:
            w, h = map(int, size.lower().split("x"))
        except Exception:
            w, h = 1024, 768
        img_bytes = _post_aihorde_http(base_url, prompt, api_key, w, h, steps, timeout)
        with open(out_path, "wb") as f:
            f.write(img_bytes)
        return out_path

    if provider == "huggingface":
        if not base_url:
            raise ImageRouterError("Falta IMAGEROUTER_BASE_URL para Hugging Face.")
        img_bytes = _post_hf_bytes(base_url, api_key, prompt, timeout)
        with open(out_path, "wb") as f:
            f.write(img_bytes)
        return out_path

    # OpenAI-style por defecto
    endpoint = base_url if base_url.endswith("/images/generations") else f"{base_url}/v1/images/generations"
    payload = {"model": model, "prompt": prompt, "size": size, "n": 1, "guidance_scale": guidance, "steps": steps}
    if seed is not None:
        payload["seed"] = seed
    img_bytes = _post_openai_images(endpoint, api_key, payload, timeout)
    with open(out_path, "wb") as f:
        f.write(img_bytes)
    return out_path
