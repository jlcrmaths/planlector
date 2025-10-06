#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente multiproveedor para generación de imágenes.
"""

import os
import time
import base64
import json
import pathlib
from typing import Optional
from io import BytesIO
import requests
from PIL import Image
from uuid import uuid4


class ImageRouterError(Exception):
    pass


class ImageRouterBillingRequired(ImageRouterError):
    pass


def _rand_name(n=8) -> str:
    import secrets, string
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(n))


def _clean(s: Optional[str]) -> str:
    if not s:
        return ""
    return s.replace("\r", "").replace("\n", "").strip()


def _ensure_png(img_bytes: bytes) -> bytes:
    try:
        im = Image.open(BytesIO(img_bytes))
        if im.mode not in ("RGB", "L", "P", "RGBA"):
            im = im.convert("RGB")
        buf = BytesIO()
        im.convert("RGB").save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return img_bytes

def _post_runware_http(api_url: str, api_key: str, prompt: str, model: str, width: int, height: int, steps: int, timeout: int) -> bytes:
    headers = {"Authorization": f"Bearer {_clean(api_key)}","Content-Type": "application/json"}
    mdl = model or os.getenv("RUNWARE_MODEL", "runware:101@1")
    task = {"taskType": "imageInference","taskUUID": str(uuid4()),"outputType": "URL","outputFormat": "JPG","positivePrompt": prompt,"height": int(max(64, min(height, 1536))),"width": int(max(64, min(width, 1536))),"model": mdl,"steps": max(1, min(steps, 20)),"CFGScale": 7.5,"numberResults": 1}
    payload = [task]
    resp = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=timeout)
    if resp.status_code == 401: raise ImageRouterError("Runware: 401 (API key inválida o ausente).")
    if resp.status_code >= 400: raise ImageRouterError(f"Runware HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    arr = data.get("data") or []
    if not arr: raise ImageRouterError(f"Runware: respuesta sin 'data': {data}")
    first = arr[0]
    if "imageURL" in first and first["imageURL"]:
        rimg = requests.get(first["imageURL"], timeout=timeout)
        rimg.raise_for_status()
        return _ensure_png(rimg.content)
    if "imageBase64Data" in first and first["imageBase64Data"]: return _ensure_png(base64.b64decode(first["imageBase64Data"]))
    raise ImageRouterError("Runware: no se encontró imageURL ni base64 en la respuesta.")

def _post_hf_bytes(endpoint: str, api_key: str, prompt: str, timeout: int) -> bytes:
    headers = {"Authorization": f"Bearer {_clean(api_key)}", "Content-Type": "application/json"}
    payload = {"inputs": prompt}
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    if resp.status_code in (503, 524):
        time.sleep(2)
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400: raise ImageRouterError(f"HF HTTP {resp.status_code}: {resp.text[:300]}")
    return _ensure_png(resp.content)

def _post_openai_images(endpoint: str, api_key: str, payload: dict, timeout: int) -> bytes:
    headers = {"Content-Type": "application/json"}
    if _clean(api_key): headers["Authorization"] = f"Bearer {_clean(api_key)}"
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    if resp.status_code == 403:
        try: msg = (resp.json().get("error", {}).get("message") or "")[:500]
        except Exception: msg = resp.text[:500]
        if "deposit" in msg.lower(): raise ImageRouterBillingRequired(msg)
    if resp.status_code >= 400: raise ImageRouterError(f"OpenAI-style HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if "data" in data and data["data"]:
        entry = data["data"][0]
        if entry.get("b64_json"): return _ensure_png(base64.b64decode(entry["b64_json"]))
        if entry.get("url"):
            r = requests.get(entry["url"], timeout=timeout)
            r.raise_for_status()
            return _ensure_png(r.content)
    raise ImageRouterError("OpenAI-style: respuesta sin imagen.")

def _post_aihorde_http(base_url: str, prompt: str, api_key: str, width: int, height: int, steps: int, timeout: int) -> bytes:
    headers = {"apikey": _clean(api_key) or "0000000000"}
    payload = {
        "prompt": prompt,
        "params": { "width": width, "height": height, "steps": max(1, min(steps, 20)), "cfg_scale": 5.0 },
        "n": 1, "r2": True,
        "nsfw": True, "censor_nsfw": False
    }
    r = requests.post(f"{base_url.rstrip('/')}/generate/async", headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    req_id = r.json().get("id")
    if not req_id: raise ImageRouterError("AI Horde sin id de petición.")
    t0 = time.time()
    while True:
        time.sleep(2)
        rc = requests.get(f"{base_url.rstrip('/')}/generate/check/{req_id}", timeout=timeout)
        rc.raise_for_status()
        if rc.json().get("done"): break
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
    guidance: float = 4.0, steps: int = 12, seed: Optional[int] = None, timeout: int = 300
) -> str:
    provider = os.getenv("IMAGEROUTER_PROVIDER", "runware").strip().lower()
    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(pathlib.Path(out_dir, f"img_{_rand_name()}.png"))

    try:
        w, h = map(int, size.lower().split("x"))
    except Exception:
        w, h = 1024, 768

    if provider == "aihorde":
        w = 512
        h = 512

    if provider == "runware":
        api_url = _clean(os.getenv("RUNWARE_API_URL")) or "https://api.runware.ai/v1"
        api_key = _clean(os.getenv("RUNWARE_API_KEY"))
        if not api_key: raise ImageRouterError("Falta RUNWARE_API_KEY.")
        img_bytes = _post_runware_http(api_url, api_key, prompt, model, w, h, steps, timeout)
        with open(out_path, "wb") as f: f.write(img_bytes)
        return out_path

    if provider == "huggingface":
        base_url = _clean(os.getenv("IMAGEROUTER_BASE_URL"))
        if not base_url: raise ImageRouterError("Falta IMAGEROUTER_BASE_URL para Hugging Face.")
        api_key = _clean(os.getenv("IMAGEROUTER_API_KEY"))
        img_bytes = _post_hf_bytes(base_url, api_key, prompt, timeout)
        with open(out_path, "wb") as f: f.write(img_bytes)
        return out_path

    if provider == "openai":
        base_url = (_clean(os.getenv("IMAGEROUTER_BASE_URL")) or "").rstrip("/")
        api_key = _clean(os.getenv("IMAGEROUTER_API_KEY"))
        endpoint = base_url if base_url.endswith("/images/generations") else f"{base_url}/v1/images/generations"
        payload = {"model": model or "gpt-image-1", "prompt": prompt, "size": f"{w}x{h}", "n": 1, "guidance_scale": guidance, "steps": steps}
        if seed is not None: payload["seed"] = seed
        img_bytes = _post_openai_images(endpoint, api_key, payload, timeout)
        with open(out_path, "wb") as f: f.write(img_bytes)
        return out_path

    if provider == "aihorde":
        base = _clean(os.getenv("IMAGEROUTER_BASE_URL")) or "https://aihorde.net/api/v2"
        api_key = _clean(os.getenv("IMAGEROUTER_API_KEY")) or "0000000000"
        img_bytes = _post_aihorde_http(base, prompt, api_key, w, h, steps, timeout)
        with open(out_path, "wb") as f: f.write(img_bytes)
        return out_path

    raise ImageRouterError(f"Proveedor no soportado: {provider}")
