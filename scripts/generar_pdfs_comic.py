#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import argparse
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from pathlib import Path

from fpdf import FPDF
from PIL import Image

# --- Configuración de rutas e imports ---
HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
for p in (HERE, PARENT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    # Usamos el nuevo y correcto cliente de Gemini
    from gemini_client import generate_image_with_gemini
except ModuleNotFoundError:
    from scripts.gemini_client import generate_image_with_gemini

# --- Parser (sin cambios) ---
HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*)\s*$')
PROMPT_RE = re.compile(r'^\s*!\[prompt\]\s*(.*)\s*$', re.IGNORECASE)

@dataclass
class Block:
    type: str
    text: str

def parse_markdown(text: str) -> Tuple[List[Block], str]:
    lines = text.splitlines()
    blocks: List[Block] = []
    current_para: List[str] = []
    title_h1: Optional[str] = None
    
    def flush_para():
        nonlocal current_para
        if current_para:
            content = "\n".join(current_para).strip()
            if content: blocks.append(Block('p', content))
            current_para = []

    for line in lines:
        m_prompt = PROMPT_RE.match(line)
        if m_prompt:
            flush_para()
            prompt_text = (m_prompt.group(1) or "").strip()
            if prompt_text: blocks.append(Block('img', prompt_text))
            continue

        m_heading = HEADING_RE.match(line)
        if m_heading:
            flush_para()
            level = len(m_heading.group(1))
            heading_text = m_heading.group(2).strip()
            if level == 1 and not title_h1: title_h1 = heading_text
            blocks.append(Block(f'h{level}', heading_text))
            continue
        
        if not line.strip():
            if current_para: flush_para()
        else:
            current_para.append(line)

    flush_para()
    return blocks, (title_h1 or "")

def clean_inline_md(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s); s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'\s*\n\s*', ' ', s)
    return re.sub(r'\s{2,}', ' ', s).strip()

class ComicPDF(FPDF):
    def __init__(self, font_path: Optional[str] = None):
        super().__init__(orientation="P", unit="mm", format="A4"); self.set_margins(18, 18, 18)
        self.set_auto_page_break(auto=True, margin=20); self._font_family = "helvetica"; self._init_fonts(font_path)
    
    def _init_fonts(self, font_path: Optional[str]):
        base_dir = os.path.dirname(font_path) if (font_path and os.path.isfile(font_path)) else "/usr/share/fonts/truetype/dejavu"
        try:
            reg = os.path.join(base_dir, "DejaVuSans.ttf"); bold = os.path.join(base_dir, "DejaVuSans-Bold.ttf")
            if os.path.isfile(reg): self.add_font("DejaVu", style="", fname=reg); self._font_family = "DejaVu"
            if os.path.isfile(bold): self.add_font("DejaVu", style="B", fname=bold)
        except Exception as e: print(f"[AVISO] No se pudieron cargar fuentes DejaVu: {e}")

    def header_title(self, title: str):
        self.set_font(self._font_family, 'B', 24); self.set_text_color(40, 40, 40); self.multi_cell(0, 12, title, align="C"); self.ln(5); self.set_text_color(0, 0, 0); self.set_font(self._font_family, '', 11)

    def footer(self):
        self.set_y(-15); self.set_font(self._font_family, '', 9); self.set_text_color(150, 150, 150); self.cell(0, 10, f'Página {self.page_no()}', align='C')

    def _pil_to_temp_jpg(self, img: Image.Image, w_mm: float):
        iw, ih = img.size; h_mm = w_mm * (ih / iw) if iw else w_mm
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            path = tmp.name; img.convert("RGB").save(path, "JPEG", quality=90, optimize=True)
        return path, h_mm
    
    def flow_paragraph_with_image(self, text: str, img: Image.Image, side: str = "right"):
        text_clean = clean_inline_md(text); img_w_mm = 70.0; gutter_mm = 5.0; line_height = 5.5
        page_w = self.w - self.l_margin - self.r_margin; text_w = page_w - img_w_mm - gutter_mm
        
        y_before = self.get_y(); img_path, img_h_mm = self._pil_to_temp_jpg(img, img_w_mm)
        
        lines = self.multi_cell(text_w, line_height, text_clean, dry_run=True, output='LINES')
        text_h_mm = len(lines) * line_height

        if self.get_y() + max(img_h_mm, text_h_mm) + 10 > self.page_break_trigger:
            self.add_page(); y_before = self.get_y()

        x_img = self.l_margin if side == 'left' else self.w - self.r_margin - img_w_mm
        self.image(img_path, x=x_img, y=y_before, w=img_w_mm)
        try: os.remove(img_path)
        except Exception: pass
        
        x_text = self.l_margin if side == 'right' else self.l_margin + img_w_mm + gutter_mm
        self.set_xy(x_text, y_before)
        self.multi_cell(text_w, line_height, text_clean, align='J')
        self.set_y(max(y_before + img_h_mm, self.get_y()) + 8)

def obtener_imagen(prompt: str, cache_dir: str) -> Optional[Image.Image]:
    try:
        image_path = generate_image_with_gemini(prompt=prompt, out_dir=cache_dir)
        return Image.open(image_path).convert("RGB")
        time.sleep(15) # Pausa de 15 segundos para no saturar la API
    except Exception as e:
        print(f"🚨 [ERROR FATAL] No se pudo obtener la imagen de Gemini: {e}")
        return None

def generar_pdf_de_md(md_path: str, input_folder: str, output_folder: str, font_path: Optional[str]):
    with open(md_path, "r", encoding="utf-8") as f: text = f.read()
    
    blocks, title_h1 = parse_markdown(text)
    
    title = title_h1 or os.path.splitext(os.path.basename(md_path))[0]
    cache_dir = os.path.join(output_folder, "_cache_imgs"); os.makedirs(cache_dir, exist_ok=True)
    pdf = ComicPDF(font_path=font_path); pdf.set_title(title); pdf.add_page()
    
    pdf.header_title(title)
    
    side = "right"
    for idx, b in enumerate(blocks):
        if b.type == 'img':
            if idx + 1 < len(blocks) and blocks[idx + 1].type == 'p':
                print(f"🎨 Maquetando imagen con texto: '{b.text[:50]}...'")
                img = obtener_imagen(b.text, cache_dir)
                if img:
                    pdf.flow_paragraph_with_image(blocks[idx+1].text, img, side=side)
                    side = "left" if side == "right" else "right"
                    time.sleep(1) # Pausa para no saturar la API
            else: # Imagen sola
                img = obtener_imagen(b.text, cache_dir)
                if img:
                    w = pdf.w - pdf.l_margin - pdf.r_margin; y = pdf.get_y()
                    path, h = pdf._pil_to_temp_jpg(img, w)
                    if y + h > pdf.h - pdf.b_margin: pdf.add_page(); y = pdf.get_y()
                    pdf.image(path, x=pdf.l_margin, y=y, w=w); pdf.set_y(y + h + 5)
        
        elif b.type.startswith("h"):
            level = int(b.type[1]);
            if level == 1: continue
            pdf.set_font(pdf._font_family, 'B', 22 - 3 * level)
            pdf.multi_cell(0, 10, clean_inline_md(b.text))
            pdf.set_font(pdf._font_family, '', 11); pdf.ln(2)
        
        elif b.type == 'p':
            if idx > 0 and blocks[idx-1].type == 'img':
                continue
            pdf.multi_cell(0, 5.5, clean_inline_md(b.text), align='J'); pdf.ln(4)

    rel_path = os.path.relpath(os.path.dirname(md_path), input_folder)
    pdf_folder = os.path.join(output_folder, rel_path); os.makedirs(pdf_folder, exist_ok=True)
    output_pdf = os.path.join(pdf_folder, os.path.basename(md_path).replace(".md", ".pdf"))
    pdf.output(output_pdf)
    print(f"✅ PDF generado: {output_pdf}")

def main():
    parser = argparse.ArgumentParser(); 
    parser.add_argument("--input-folder", default="historias"); 
    parser.add_argument("--output-folder", default="pdfs_generados")
    args = parser.parse_args()
    
    font_path = os.getenv("FONT_PATH")
    md_files = [os.path.join(root, f) for root, _, files in os.walk(args.input_folder) for f in files if f.lower().endswith(".md")]
    print(f"📄 MD a procesar: {len(md_files)}")
    
    for md in sorted(md_files):
        print(f"--- Procesando: {md} ---")
        generar_pdf_de_md(md, args.input_folder, args.output_folder, font_path)

if __name__ == "__main__":
    main()


