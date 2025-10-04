#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente multiproveedor:
- openai  -> /v1/images/generations (routers OpenAI-style)
- huggingface -> Inference API (bytes)
- aihorde -> API pública gratuita (voluntariado)

Selecciona con IMAGEROUTER_PROVIDER = openai | huggingface | aihorde
"""

import os
import time
import base64
import json
import pathlib
from typing import Optional
import requests

class ImageRouterError(Exception): ...
class ImageRouterBillingRequired(ImageRouterError): ...

def _rand_name(n=8)->str:
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
        try:
            data = resp.json(); msg = (data.get("error",{}).get("message") or "")[:500]
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

# ---------- Hugging Face (bytes) ----------
def _post_hf_bytes(endpoint: str, api_key: str, prompt: str, timeout: int) -> bytes:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"inputs": prompt}
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    if resp.status_code in (503, 524):  # warming-up / edge timeout
        time.sleep(2)
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise ImageRouterError(f"HF HTTP {resp.status_code} en {endpoint}: {resp.text[:500]}")
    return resp.content

# ---------- AI Horde (gratis) ----------
def _post_aihorde(prompt: str, api_key: str, width: int, height: int, steps: int, timeout: int) -> bytes:
    """
    Flujo asíncrono usando el SDK oficial: txt2img_request -> poll -> status -> primera generación.
    Más info: endpoints /v2/generate/async, /v2/generate/check, /v2/generate/status.  # [3](https://github.com/Haidra-Org/AI-Horde/blob/main/README_integration.md)[4](https://github.com/sigaloid/stablehorde-api)
    El servicio permite clave anónima 0000000000 (menor prioridad).  # [1](https://stablehorde.net/)
    """
    from horde_sdk import HordeClient
    from horde_sdk.ai_horde_api.apis.tags import text_to_image_api
    from horde_sdk.ai_horde_api.models import (
        GenerationInput, ModelGenerationInputStable
    )

    client = HordeClient(api_key=api_key or "0000000000", client_agent="MathGym/1.0")

    gen_params = ModelGenerationInputStable(
        width=width, height=height, steps=max(1, min(steps, 20)), cfg_scale=5.0
    )
    payload = GenerationInput(
        prompt=prompt,
        params=gen_params,
        n=1,             # 1 imagen por petición
        r2=True,         # permitir URLs R2 cuando aplique
        censor_nsfw=True,
        nsfw=False
    )

    # 1) Encolar petición
    req = text_to_image_api.txt2img_request.sync(client, request_body=payload)
    req_id = req.id

    # 2) Polling suave hasta done
    t0 = time.time()
    while True:
        chk = text_to_image_api.generate_check.sync(client, id=req_id)
        if getattr(chk, "done", 0) == 1:
            break
        if time.time() - t0 > timeout:
            raise ImageRouterError("AI Horde: timeout esperando la generación.")
        time.sleep(2)

    # 3) Recuperar generaciones y decodificar la primera
    st = text_to_image_api.generate_status.sync(client, id=req_id)
    gens = getattr(st, "generations", None) or []
    if not gens:
        raise ImageRouterError("AI Horde: sin generaciones en la respuesta.")
    # Cada item suele traer base64 en 'img'
    b64 = gens[0].img
    return base64.b64decode(b64)

def generate_image_via_imagerouter(
    prompt: str,
    out_dir: str,
    model: str = "black-forest-labs/FLUX-1-schnell:free",
    size: str = "1024x768",
    guidance: float = 4.0,
    steps: int = 12,
    seed: Optional[int] = None,
    timeout: int = 180,
) -> str:
    base_url = os.getenv("IMAGEROUTER_BASE_URL", "").rstrip("/")
    api_key  = os.getenv("IMAGEROUTER_API_KEY", "")
    provider = os.getenv("IMAGEROUTER_PROVIDER", "openai").strip().lower()

    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(pathlib.Path(out_dir, f"img_{_rand_name()}.png"))

    if provider == "aihorde":
        # size "WxH"
        try:
            w, h = map(int, size.lower().split("x"))
        except Exception:
            w, h = 1024, 768
        img_bytes = _post_aihorde(prompt=prompt, api_key=api_key or "0000000000",
                                  width=w, height=h, steps=steps, timeout=timeout)
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

    # Por defecto: OpenAI-style
    endpoint = base_url if base_url.endswith("/images/generations") else f"{base_url}/v1/images/generations"
    payload = {"model": model, "prompt": prompt, "size": size, "n": 1, "guidance_scale": guidance, "steps": steps}
    if seed is not None:
        payload["seed"] = seed
    img_bytes = _post_openai_images(endpoint, api_key, payload, timeout)
    with open(out_path, "wb") as f:
        f.write(img_bytes)
    return out_path
