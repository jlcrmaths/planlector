#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, time, base64, json, pathlib
from typing import Optional
from io import BytesIO
import requests
from PIL import Image

class ImageRouterError(Exception): pass

def _rand_name(n=8) -> str:
    import secrets, string
    return ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(n))

def _clean(s: Optional[str]) -> str:
    return s.strip() if s else ""

def _ensure_png(img_bytes: bytes) -> bytes:
    try:
        im = Image.open(BytesIO(img_bytes)); buf = BytesIO()
        im.convert("RGB").save(buf, "PNG"); return buf.getvalue()
    except Exception: return img_bytes

def _post_aihorde_http(base_url: str, prompt: str, api_key: str, width: int, height: int, steps: int, timeout: int) -> bytes:
    headers = {"apikey": _clean(api_key) or "0000000000", "Client-Agent": "ImageIllustrator:1.0"}
    
    # --- PARÁMETROS DE ALTA CALIDAD ---
    negative_prompt = "(worst quality, low quality, normal quality), lowres, bad anatomy, bad hands, multiple views, multiple panels, watermark, signature, text, letters, username, artist name, blurry, ugly"
    full_prompt = f"{prompt} ### {negative_prompt}"
    
    payload = {
        "prompt": full_prompt,
        "params": {
            "sampler_name": "k_dpmpp_2m_sde",  # Sampler de alta calidad
            "width": width, "height": height,
            "steps": 30,  # Más pasos para mayor detalle
            "cfg_scale": 7.5
        },
        "models": ["AlbedoBase XL (SDXL)"], # Modelo potente
        "n": 1, "r2": True, "nsfw": True, "censor_nsfw": False
    }
    # --- FIN DE PARÁMETROS ---

    r = requests.post(f"{base_url.rstrip('/')}/generate/async", headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    req_id = r.json().get("id")
    if not req_id: raise ImageRouterError("AI Horde sin id de petición.")
    t0 = time.time()
    while True:
        time.sleep(4) # Más tiempo de espera para la generación
        rc = requests.get(f"{base_url.rstrip('/')}/generate/check/{req_id}", timeout=timeout)
        rc.raise_for_status()
        status = rc.json()
        if status.get("done"): break
        if time.time() - t0 > timeout: raise ImageRouterError("AI Horde: timeout.")
    
    rs = requests.get(f"{base_url.rstrip('/')}/generate/status/{req_id}", timeout=timeout)
    rs.raise_for_status()
    st = rs.json()
    gens = st.get("generations") or []
    if not gens: raise ImageRouterError("AI Horde: sin generaciones.")
    img_field = gens[0].get("img") or ""
    if img_field.lower().startswith("http"):
        rimg = requests.get(img_field, timeout=timeout); rimg.raise_for_status()
        return _ensure_png(rimg.content)
    if "data:image/" in img_field.lower():
        b64 = img_field.split(",", 1)[1]; return _ensure_png(base64.b64decode(b64))
    return _ensure_png(base64.b64decode(img_field))

def generate_image_via_imagerouter(
    prompt: str, out_dir: str, model: str = "", size: str = "1024x768",
    guidance: float = 4.0, steps: int = 12, seed: Optional[int] = None, timeout: int = 600
) -> str:
    provider = os.getenv("IMAGEROUTER_PROVIDER", "aihorde").strip().lower()
    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(pathlib.Path(out_dir, f"img_{_rand_name()}.png"))
    
    w, h = 512, 512 # Tamaño fijo y seguro
    
    if provider == "aihorde":
        api_key = _clean(os.getenv("IMAGEROUTER_API_KEY")) or "0000000000"
        img_bytes = _post_aihorde_http("https://aihorde.net/api/v2", prompt, api_key, w, h, steps, timeout)
        with open(out_path, "wb") as f: f.write(img_bytes)
        return out_path

    raise ImageRouterError(f"Proveedor no soportado: {provider}")
