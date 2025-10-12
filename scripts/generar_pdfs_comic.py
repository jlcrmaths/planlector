#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador de PDFs educativos optimizado:
- 1 imagen por reto (512x512, JPEG q=80)
- imagen a un lado (alternando izquierda/derecha)
- apartados a), b), c)... en nueva línea
- caching de imágenes para ahorrar coste
- respeto de cuotas (reintentos y pausas adaptativas)
- evita regenerar PDFs si ya existen
- requiere GOOGLE_API_KEY en env
"""

import os
import re
import sys
import time
import random
import hashlib
import pathlib
from dataclasses import dataclass
from typing import List, Optional, Tuple

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image
from io import BytesIO

# --- Intentamos importar el cliente Gemini ---
try:
    import google.generativeai as genai
except Exception:
    genai = None

# --- CONFIGURACIÓN ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    print("🚨 ERROR: Debes exportar la variable de entorno GOOGLE_API_KEY con una clave válida.")
    sys.exit(1)

try:
    genai.configure(api_key=GOOGLE_API_KEY)
except Exception as e:
    print(f"🚨 ERROR al configurar Gemini: {e}")
    sys.exit(1)

# --- Expresiones regulares ---
HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*)\s*$')
RETO_RE = re.compile(r'^\s*##\s*Reto\s*(\d+)', re.IGNORECASE)

@dataclass
class Block:
    type: str
    text: str

# --- Funciones auxiliares ---
def clean_inline_md(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'\s*\n\s*', ' ', s)
    return re.sub(r'\s{2,}', ' ', s).strip()

def split_subitems(text: str) -> str:
    return re.sub(r'(?<!^)\s*(?=([a-záéíóúñ]\)))', '\n', text)

def parse_markdown(md_text: str) -> Tuple[List[Block], str]:
    lines = md_text.splitlines()
    blocks: List[Block] = []
    current_para: List[str] = []
    title_h1: Optional[str] = None

    def flush_para():
        nonlocal current_para
        if current_para:
            content = "\n".join(current_para).strip()
            if content:
                blocks.append(Block('p', content))
            current_para = []

    for line in lines:
        m_heading = HEADING_RE.match(line)
        if m_heading:
            flush_para()
            level = len(m_heading.group(1))
            heading_text = m_heading.group(2).strip()
            if level == 1 and not title_h1:
                title_h1 = heading_text
            if level == 2 and RETO_RE.match(line):
                blocks.append(Block('reto_start', heading_text))
            else:
                blocks.append(Block(f'h{level}', heading_text))
            continue

        if not line.strip():
            flush_para()
        else:
            current_para.append(line)
    flush_para()
    return blocks, (title_h1 or "Documento educativo")

# --- Clase PDF personalizada ---
class EduPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(auto=True, margin=16)
        self._font_family = "Helvetica"
        self._init_fonts()

    def _init_fonts(self):
        font_dirs = [
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/liberation",
            str(pathlib.Path(__file__).resolve().parent / "fonts"),
        ]
        for base in font_dirs:
            if not os.path.isdir(base):
                continue
            reg = os.path.join(base, "DejaVuSans.ttf")
            bold = os.path.join(base, "DejaVuSans-Bold.ttf")
            if os.path.isfile(reg):
                self.add_font("DejaVu", "", reg)
                if os.path.isfile(bold):
                    self.add_font("DejaVu", "B", bold)
                self._font_family = "DejaVu"
                break
        self.set_font(self._font_family, "", 12)

    def portada(self, titulo: str):
        self.add_page()
        self.set_font(self._font_family, "B", 26)
        self.set_text_color(0, 102, 204)
        self.ln(60)
        for line in re.findall(r'.{1,40}(?:\s|$)', titulo):
            self.cell(0, 14, line.strip(), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        self.ln(20)
        self.set_font(self._font_family, "", 14)
        self.cell(0, 8, "Material educativo generado automáticamente", align="C")
        self.add_page()

    def add_heading(self, text: str, level: int):
        size = max(10, 22 - 2 * level)
        color = (0, 102, 204) if level == 2 else (0, 0, 0)
        self.set_text_color(*color)
        self.set_font(self._font_family, "B", size)
        self.multi_cell(0, 9, clean_inline_md(text))
        self.ln(2)
        self.set_text_color(0, 0, 0)
        self.set_font(self._font_family, "", 12)

    def add_paragraph(self, text: str):
        text = split_subitems(text)
        for para in text.split('\n'):
            self.multi_cell(0, 7, clean_inline_md(para), align="J")
            self.ln(1)
        self.ln(3)

    def flow_paragraph_with_image(self, text: str, img_path: str, side="right"):
        gutter, img_w, line_h = 6, 70, 6
        page_w = self.w - self.l_margin - self.r_margin
        text_w = page_w - img_w - gutter
        y_start = self.get_y()
        im = Image.open(img_path)
        iw, ih = im.size
        img_h = img_w * ih / iw
        if y_start + img_h > self.page_break_trigger:
            self.add_page()
            y_start = self.get_y()
        x_img = self.l_margin if side == "left" else self.w - self.r_margin - img_w
        self.image(img_path, x=x_img, y=y_start, w=img_w)
        x_text = self.l_margin + img_w + gutter if side == "left" else self.l_margin
        self.set_xy(x_text, y_start)
        for para in split_subitems(text).split('\n'):
            self.multi_cell(text_w, line_h, clean_inline_md(para), align="J")
            self.ln(1)
        self.set_y(max(y_start + img_h, self.get_y()) + 6)

# --- Imagen optimizada con caché ---
def prompt_to_hash(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]

def generate_image_with_gemini(prompt: str, out_dir: str) -> str:
    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    img_path = os.path.join(out_dir, f"img_{prompt_to_hash(prompt)}.jpg")
    if os.path.exists(img_path):
        print(f"♻️ Imagen cacheada: {img_path}")
        return img_path
    model = genai.GenerativeModel("gemini-2.5-flash-image")
    for attempt in range(1, 6):
        try:
            delay = random.uniform(6, 9)
            print(f"⏳ Esperando {delay:.1f}s antes del intento {attempt}...")
            time.sleep(delay)
            prompt_full = (
                f"Genera una ilustración educativa clara y limpia de 512x512 píxeles. "
                f"Representa: {prompt}. Sin texto ni marcas de agua. Estilo digital, colores vivos."
            )
            response = model.generate_content(prompt_full)
            image_data = None
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        image_data = part.inline_data.data
                        break
            if not image_data:
                raise RuntimeError("Sin datos de imagen en la respuesta.")
            im = Image.open(BytesIO(image_data)).convert("RGB")
            im = im.resize((512, 512), Image.LANCZOS)
            im.save(img_path, "JPEG", quality=80)
            print(f"✅ Imagen guardada: {img_path}")
            return img_path
        except Exception as e:
            if "429" in str(e):
                wait = min(60 * attempt, 300)
                print(f"⚠️ Cuota excedida. Reintentando en {wait}s...")
                time.sleep(wait)
                continue
            elif attempt == 5:
                raise
    raise RuntimeError("Fallo tras varios intentos con Gemini.")

# --- Generar PDF ---
def generar_pdf_optimizado(md_path, input_folder, output_folder, images_out_dir):
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()
    blocks, title = parse_markdown(md_text)
    retos, current = [], None
    for b in blocks:
        if b.type == "reto_start":
            if current:
                retos.append(current)
            current = {"title": b.text, "blocks": []}
        else:
            if not current:
                current = {"title": "Introducción", "blocks": []}
            current["blocks"].append(b)
    if current:
        retos.append(current)
    pdf = EduPDF()
    pdf.portada(title)
    side = "right"
    for reto in retos:
        pdf.add_heading(reto["title"], 2)
        prompt = reto["title"]
        for rb in reto["blocks"]:
            if rb.type == "p":
                prompt += " " + rb.text[:200]
                break
        img_path = generate_image_with_gemini(prompt, images_out_dir)
        text = "\n\n".join(rb.text for rb in reto["blocks"] if rb.type == "p")
        pdf.flow_paragraph_with_image(text, img_path, side)
        side = "left" if side == "right" else "right"
    os.makedirs(output_folder, exist_ok=True)
    out_pdf = os.path.join(output_folder, os.path.basename(md_path).replace(".md", ".pdf"))
    pdf.output(out_pdf)
    print(f"✅ PDF generado: {out_pdf}")

# --- MAIN ---
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Genera PDFs educativos con 1 imagen por reto (optimizado).")
    parser.add_argument("--input-folder", default="historias")
    parser.add_argument("--output-folder", default="pdfs_generados")
    parser.add_argument("--images-cache", default="imagenes_cache")
    args = parser.parse_args()

    os.makedirs(args.output_folder, exist_ok=True)
    md_files = [os.path.join(root, f)
                for root, _, files in os.walk(args.input_folder)
                for f in files if f.lower().endswith(".md")]

    print(f"📄 Archivos Markdown detectados: {len(md_files)}")
    for md in sorted(md_files):
        out_pdf = os.path.join(args.output_folder, os.path.basename(md).replace(".md", ".pdf"))
        if os.path.exists(out_pdf):
            print(f"⏭️  PDF ya existe, se omite: {out_pdf}")
            continue
        print(f"--- Procesando: {md} ---")
        try:
            generar_pdf_optimizado(md, args.input_folder, args.output_folder, args.images_cache)
        except Exception as e:
            print(f"❌ Error procesando {md}: {e}")
            continue

if __name__ == "__main__":
    main()



