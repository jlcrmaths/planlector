#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import argparse
import textwrap
import tempfile
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

# -----------------------------
# Utilidades de parsing Markdown
# -----------------------------
HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*)\s*$')

@dataclass
class Block:
    type: str   # 'h1'..'h6' o 'p'
    text: str

def parse_markdown(text: str) -> Tuple[List[Block], List[str], List[str], str]:
    """
    Devuelve:
      - blocks: lista de bloques (headings y párrafos)
      - h2_list: títulos H2 (para estilo)
      - actividades: líneas bajo '## Actividades' hasta el SIGUIENTE heading
      - title: H1 si existe, si no el caller usará el nombre de archivo
    """
    lines = text.splitlines()
    blocks: List[Block] = []
    h2_list: List[str] = []
    actividades: List[str] = []
    current_para: List[str] = []
    in_actividades = False
    title_h1: Optional[str] = None

    def flush_para():
        nonlocal current_para, blocks
        if current_para:
            blocks.append(Block('p', "\n".join(current_para).strip()))
            current_para = []

    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            # si empezamos un heading, cerramos párrafo previo
            flush_para()
            level = len(m.group(1))
            heading_text = m.group(2).strip()

            # Al encontrar un heading, si estábamos en Actividades, salimos
            if in_actividades and heading_text.lower() != "actividades":
                in_actividades = False

            blocks.append(Block(f'h{level}', heading_text))
            if level == 1 and not title_h1:
                title_h1 = heading_text
            if level == 2:
                if heading_text.lower() == "actividades":
                    in_actividades = True
                else:
                    in_actividades = False
                h2_list.append(heading_text)
            continue

        if in_actividades:
            # Recogemos actividades como líneas simples
            if line.strip():
                actividades.append(line.strip())
            continue

        # Gestión de párrafos
        if line.strip() == "":
            flush_para()
        else:
            current_para.append(line)

    flush_para()
    return blocks, h2_list, actividades, (title_h1 or "")

# -----------------------------
# Generación de imágenes
# -----------------------------
def load_font_for_placeholder(font_path: Optional[str], size: int) -> ImageFont.ImageFont:
    try:
        if font_path and os.path.isfile(font_path):
            return ImageFont.truetype(font_path, size)
    except Exception:
        pass
    return ImageFont.load_default()

def make_placeholder(prompt: str, size=(512, 320), bg=(236, 239, 244), fg=(38, 50, 56), font_path: Optional[str]=None) -> Image.Image:
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    title = "Ilustración tipo cómic"
    body = textwrap.shorten(prompt.replace("\n", " "), width=180, placeholder="…")

    # Tipografías para placeholder
    font_title = load_font_for_placeholder(font_path, 28)
    font_body = load_font_for_placeholder(font_path, 18)

    # Centrados
    tw, th = draw.textbbox((0, 0), title, font=font_title)[2:]
    bw, bh = draw.textbbox((0, 0), body, font=font_body)[2:]

    W, H = img.size
    y0 = (H - (th + 14 + bh)) // 2
    draw.text(((W - tw)//2, y0), title, font=font_title, fill=fg)
    draw.text(((W - bw)//2, y0 + th + 14), body, font=font_body, fill=fg)
    return img

class SDWrapper:
    """Capa delgada para cargar Stable Diffusion solo si FAST_MODE=0."""
    def __init__(self, fast_mode: bool, hf_token: Optional[str]):
        self.fast_mode = fast_mode
        self.hf_token = hf_token
        self._pipe = None
        self._device = "cpu"
        self._generator = None
        self._loaded = False
        self._available = False

    def _lazy_load(self):
        if self.fast_mode:
            self._loaded = True
            self._available = False
            return
        try:
            import torch
            from diffusers import StableDiffusionPipeline

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if self._device == "cuda" else torch.float32

            # Nota: usar 'token=' en lugar de 'use_auth_token=' (deprecado). [1](https://discuss.huggingface.co/t/the-use-auth-token-argument-is-deprecated-and-will-be-removed-in-v5-of-transformers/53943)
            self._pipe = StableDiffusionPipeline.from_pretrained(
                "CompVis/stable-diffusion-v1-4",
                token=self.hf_token,
                torch_dtype=dtype,
            ).to(self._device)

            # Ahorro de memoria
            try:
                self._pipe.enable_attention_slicing()
            except Exception:
                pass

            self._generator = torch.Generator(device=self._device).manual_seed(42)
            self._loaded = True
            self._available = True
        except Exception as e:
            print(f"[AVISO] No se pudo cargar Stable Diffusion: {e}")
            self._loaded = True
            self._available = False

    def generate(self, prompt: str, width: int = 512, height: int = 512, font_path: Optional[str]=None) -> Image.Image:
        if not self._loaded:
            self._lazy_load()

        if not self._available:
            # Placeholder rápido para CI
            return make_placeholder(prompt, size=(min(width, 768), min(height, 512)), font_path=font_path)

        # Generación real
        try:
            import torch  # type: ignore
            if self._device == "cpu":
                width = height = 384  # bajar resolución en CPU
            image = self._pipe(prompt, generator=self._generator, width=width, height=height).images[0]
            return image
        except Exception as e:
            print(f"[AVISO] Fallo generando imagen, usando placeholder: {e}")
            return make_placeholder(prompt, size=(min(width, 768), min(height, 512)), font_path=font_path)

# -----------------------------
# Maquetación PDF (fpdf2)
# -----------------------------
class ComicPDF(FPDF):
    def __init__(self, font_path: Optional[str] = None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=15)
        self._font_ready = False
        self._font_family = "helvetica"  # fallback ASCII
        self._font_path = font_path
        self._init_fonts()

    def _init_fonts(self):
        # Usar DejaVu Sans si está disponible; es un TTF Unicode (instalado por el workflow).
        # Proyecto oficial de DejaVu Fonts: TTFs públicos. [2](https://github.com/dejavu-fonts/dejavu-fonts)
        if self._font_path and os.path.isfile(self._font_path):
            try:
                self.add_font("DejaVu", style="", fname=self._font_path)
                self._font_family = "DejaVu"
                self._font_ready = True
            except Exception as e:
                print(f"[AVISO] No se pudo cargar la fuente Unicode ({self._font_path}): {e}")
        # si falla, usaremos helvetica (ASCII)

    def header_title(self, title: str):
        self.set_font(self._font_family, style="B" if self._font_ready else "", size=20)
        self.set_text_color(30, 30, 120)
        self.multi_cell(0, 10, title, align="C")
        self.ln(3)
        self.set_text_color(0, 0, 0)

    def add_image_fullwidth(self, img: Image.Image, max_w: float = None):
        if max_w is None:
            max_w = self.w - 2 * self.l_margin
        # Convertir a RGB y JPEG temporal
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            path = tmp.name
        try:
            img_rgb = img.convert("RGB")
            # Escala por ancho
            iw, ih = img_rgb.size
            scale = max_w / iw
            new_size = (int(iw * scale), int(ih * scale))
            img_rgb = img_rgb.resize(new_size, Image.LANCZOS)
            img_rgb.save(path, "JPEG", quality=90, optimize=True)
            self.image(path, w=max_w)
            self.ln(5)
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

# -----------------------------
# Lógica de generación por .md
# -----------------------------
def generar_pdf_de_md(md_path: str, input_folder: str, output_folder: str, sd: SDWrapper, font_path: Optional[str]):
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    blocks, h2_list, actividades, title_h1 = parse_markdown(text)
    filename_title = os.path.splitext(os.path.basename(md_path))[0]
    title = title_h1 or filename_title

    # Crear portada e imágenes de párrafos (hasta 3)
    portada_prompt = f"Portada tipo cómic, colorida, título: {title}"
    portada_img = sd.generate(portada_prompt, width=768, height=512, font_path=font_path)

    # Seleccionar los tres primeros párrafos de contenido (no actividades)
    paragraphs = [b.text for b in blocks if b.type == "p"]
    para_prompts = []
    for para in paragraphs[:3]:
        prompt = f"Ilustración tipo cómic, escena: {para}"
        para_prompts.append(prompt)

    para_images = [sd.generate(p, width=640, height=400, font_path=font_path) for p in para_prompts]

    # PDF
    pdf = ComicPDF(font_path=font_path)
    pdf.set_title(title)
    pdf.set_author("MathGym / José Luis Cantón")
    pdf.add_page()
    pdf.add_image_fullwidth(portada_img)
    pdf.header_title(title)

    # Cuerpo
    pdf.set_font(pdf._font_family, size=12)
    img_idx = 0
    for b in blocks:
        if b.type.startswith("h"):
            level = int(b.type[1])
            if level == 2:
                pdf.set_font(pdf._font_family, style="B", size=16)
                pdf.set_text_color(200, 30, 30)
                pdf.multi_cell(0, 8, b.text)
                pdf.ln(2)
                pdf.set_text_color(0, 0, 0)
                pdf.set_font(pdf._font_family, size=12)
            elif level == 3:
                pdf.set_font(pdf._font_family, style="B", size=14)
                pdf.multi_cell(0, 7, b.text)
                pdf.ln(1)
                pdf.set_font(pdf._font_family, size=12)
            continue
        if b.type == "p":
            # intercalar imagen si corresponde
            if img_idx < len(para_images) and b.text.strip():
                pdf.add_image_fullwidth(para_images[img_idx], max_w=pdf.w - 2 * pdf.l_margin)
                img_idx += 1
            pdf.multi_cell(0, 6, b.text)
            pdf.ln(2)

    # Actividades (si existen)
    if actividades:
        pdf.add_page()
        pdf.set_font(pdf._font_family, style="B", size=18)
        pdf.set_text_color(30, 100, 30)
        pdf.multi_cell(0, 10, "Actividades", align="C")
        pdf.ln(5)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font(pdf._font_family, size=12)
        for act in actividades:
            pdf.multi_cell(0, 6, f"• {act}")
            pdf.ln(2)

    # Guardar replicando estructura
    rel_path = os.path.relpath(os.path.dirname(md_path), input_folder)
    pdf_folder = os.path.join(output_folder, rel_path)
    os.makedirs(pdf_folder, exist_ok=True)
    output_pdf = os.path.join(pdf_folder, os.path.basename(md_path).replace(".md", ".pdf"))
    pdf.output(output_pdf)
    print(f"✅ PDF generado: {output_pdf}")

def listar_md(input_folder: str) -> List[str]:
    out = []
    for root, _, files in os.walk(input_folder):
        for fn in files:
            if fn.lower().endswith(".md"):
                out.append(os.path.join(root, fn))
    return sorted(out)

def main():
    parser = argparse.ArgumentParser(description="Genera PDFs tipo cómic a partir de Markdown")
    parser.add_argument("--input-folder", default="historias", help="Carpeta base de entrada")
    parser.add_argument("--output-folder", default="pdfs_generados", help="Carpeta base de salida")
    parser.add_argument("md_files", nargs="*", help="Rutas específicas de .md (opcional); si no, recorre input-folder")
    args = parser.parse_args()

    # Modo rápido por defecto en CI
    fast_mode = os.getenv("FAST_MODE", "1").lower() in ("1", "true", "yes")
    hf_token = os.getenv("HF_TOKEN", None)

    # Ruta a la fuente Unicode (instalada por apt en /usr/share/...)
    font_path = os.getenv("FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not os.path.isfile(font_path):
        # permitir fallback ASCII si no existe
        print(f"[AVISO] Fuente Unicode no encontrada en {font_path}. Se usará Helvetica (ASCII).")

    sd = SDWrapper(fast_mode=fast_mode, hf_token=hf_token)

    # Determinar lista de archivos
    if args.md_files:
        # Filtra a los que existan realmente
        md_list = [p for p in args.md_files if os.path.isfile(p) and p.endswith(".md")]
        if not md_list:
            print("[AVISO] No se encontraron .md válidos en la lista proporcionada.")
            return
        # Si pasan rutas absolutas, normalizamos el input_folder al antecesor común
        # pero para la salida mantenemos la ruta relativa a args.input_folder si encaja
    else:
        md_list = listar_md(args.input_folder)

    print(f"📄 MD a procesar: {len(md_list)}")
    for md in md_list:
        try:
            generar_pdf_de_md(md, args.input_folder, args.output_folder, sd, font_path=font_path)
        except Exception as e:
            print(f"❌ Error procesando {md}: {e}")

if __name__ == "__main__":
    main()
