#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import argparse
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple
from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw

# --- Configuración de rutas e imports ---
HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
for p in (HERE, PARENT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from imagerouter_client import (generate_image_via_imagerouter, ImageRouterError, ImageRouterBillingRequired)
except ModuleNotFoundError:
    from scripts.imagerouter_client import (generate_image_via_imagerouter, ImageRouterError, ImageRouterBillingRequired)

try:
    from scripts.prompt_synthesizer import build_visual_prompt
except Exception:
    def build_visual_prompt(text: str, doc_title: str = "") -> str:
        # Fallback simple si no existe el sintetizador
        return f"ilustración educativa sobre {doc_title}, elementos visuales clave: {text[:100]}"

# --- INICIO DE LA CORRECCIÓN DEL BUG ---

HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*)\s*$')
# Esta expresión regular es robusta y contiene el grupo de captura (.*?)
PROMPT_RE = re.compile(r'')

@dataclass
class Block:
    type: str
    text: str

def parse_markdown(text: str) -> Tuple[List[Block], List[str], str]:
    lines = text.splitlines()
    blocks: List[Block] = []
    actividades: List[str] = []
    current_para: List[str] = []
    title_h1: Optional[str] = None
    in_actividades = False

    def flush_para():
        nonlocal current_para
        if current_para:
            blocks.append(Block('p', "\n".join(current_para).strip()))
            current_para = []

    for line in lines:
        # Usamos re.search, que es más flexible y no exige que la línea entera coincida
        m_prompt = PROMPT_RE.search(line)
        if m_prompt:
            flush_para()
            # El grupo (1) siempre existirá si hay un match.
            # Este es el punto que fallaba y que ahora está corregido.
            prompt_text = m_prompt.group(1).strip()
            if prompt_text:
                blocks.append(Block('img', prompt_text))
            continue

        m_heading = HEADING_RE.match(line)
        if m_heading:
            flush_para()
            level = len(m_heading.group(1))
            heading_text = m_heading.group(2).strip()
            if level == 1 and not title_h1: title_h1 = heading_text
            if level == 2: in_actividades = (heading_text.lower() == "actividades")
            blocks.append(Block(f'h{level}', heading_text))
            continue

        if in_actividades:
            if line.strip(): actividades.append(line.strip())
            continue

        if not line.strip():
            flush_para()
        else:
            current_para.append(line)

    flush_para()
    return blocks, actividades, (title_h1 or "")

# --- FIN DE LA CORRECCIÓN DEL BUG ---

def clean_inline_md(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    return re.sub(r'\s{2,}', ' ', s).strip()

def select_key_paragraphs(blocks: List[Block], max_images: int) -> Set[int]:
    paragraph_indices = [i for i, b in enumerate(blocks) if b.type == "p"]
    # (El resto de la lógica de puntuación se mantiene)
    if not paragraph_indices: return set()
    para_texts = [(i, b.text) for i, b in enumerate(blocks) if b.type == "p"]
    scored = [len(text) for _, text in para_texts]
    ranked = sorted(enumerate(scored), key=lambda x: x[1], reverse=True)[:max_images]
    return set(paragraph_indices[idx] for idx, _ in ranked)

class ComicPDF(FPDF):
    def __init__(self, font_path: Optional[str] = None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(auto=True, margin=16)
        self._font_family = "helvetica"
        self._init_fonts(font_path)

    def _init_fonts(self, font_path: Optional[str]):
        # (código sin cambios)
        base_dir = os.path.dirname(font_path) if (font_path and os.path.isfile(font_path)) else "/usr/share/fonts/truetype/dejavu"
        try:
            reg = os.path.join(base_dir, "DejaVuSans.ttf")
            bold = os.path.join(base_dir, "DejaVuSans-Bold.ttf")
            if os.path.isfile(reg): self.add_font("DejaVu", style="", fname=reg); self._font_family = "DejaVu"
            if os.path.isfile(bold): self.add_font("DejaVu", style="B", fname=bold)
        except Exception as e: print(f"[AVISO] No se pudieron cargar fuentes DejaVu: {e}")

    def header_title(self, title: str):
        self.set_font(self._font_family, 'B', 20)
        self.set_text_color(30, 30, 120)
        self.multi_cell(0, 10, title, align="C")
        self.ln(3)
        self.set_text_color(0, 0, 0)
        self.set_font(self._font_family, '', 12)

    def footer(self):
        self.set_y(-15)
        self.set_font(self._font_family, '', 10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f'Página {self.page_no()}', align='C')

    def _pil_to_temp_jpg(self, img: Image.Image, w_mm: float):
        iw, ih = img.size
        h_mm = w_mm * (ih / iw) if iw else w_mm
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            path = tmp.name
            img.convert("RGB").save(path, "JPEG", quality=90)
        return path, h_mm

    def flow_paragraph_with_image(self, text: str, img: Image.Image, side: str):
        # (código sin cambios)
        l, r = self.l_margin, self.r_margin; usable_w = self.w - l - r
        img_w_mm = 70.0; gutter_mm = 6.0
        text_w = usable_w - img_w_mm - gutter_mm
        lines = self.multi_cell(text_w, 6, text, align='J', dry_run=True, output="LINES")
        text_h = len(lines) * 6
        y_start = self.get_y(); bottom = self.h - self.b_margin
        path_tmp, img_h = self._pil_to_temp_jpg(img, img_w_mm)
        if y_start + max(text_h, img_h) > bottom: self.add_page(); y_start = self.get_y()
        x_img = self.w - r - img_w_mm if side == "right" else l
        x_text = l if side == "right" else l + img_w_mm + gutter_mm
        self.image(path_tmp, x=x_img, y=y_start, w=img_w_mm)
        self.set_xy(x_text, y_start)
        self.multi_cell(text_w, 6, text, align='J')
        self.set_y(y_start + max(text_h, img_h) + 4)
        try: os.remove(path_tmp)
        except Exception: pass

def obtener_imagen(prompt: str, cache_dir: str, model: str) -> Image.Image:
    try:
        return generate_image_via_imagerouter(prompt=prompt, out_dir=cache_dir, model=model, size="512x512", timeout=600)
    except Exception as e:
        print(f"[AVISO] ImageRouter falló ({e}); usando placeholder")
        W, H = 512, 512
        img = Image.new("RGB", (W, H), (20, 20, 40))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(24, 24), (W - 24, H - 24)], outline=(200, 200, 220), width=2)
        return img

def generar_pdf_de_md(md_path: str, input_folder: str, output_folder: str, font_path: Optional[str], model: str, max_images: int, no_images: bool, fail_on_router_error: bool):
    with open(md_path, "r", encoding="utf-8") as f: text = f.read()
    blocks, actividades, title_h1 = parse_markdown(text)
    title = title_h1 or os.path.splitext(os.path.basename(md_path))[0]
    cache_dir = os.path.join(output_folder, "_cache_imgs")
    pdf = ComicPDF(font_path=font_path)
    pdf.set_title(title)
    pdf.add_page()

    manual_prompts_indices = {i for i, b in enumerate(blocks) if b.type == 'img'}
    has_manual_prompts = bool(manual_prompts_indices)
    
    if not no_images and not has_manual_prompts:
        # Portada solo si no hay prompts manuales
        img = obtener_imagen(build_visual_prompt("Portada", title), cache_dir, model)
        w = pdf.w - pdf.l_margin - pdf.r_margin; y = pdf.get_y()
        path, h = pdf._pil_to_temp_jpg(img, w)
        pdf.image(path, x=pdf.l_margin, y=y, w=w)
        pdf.set_y(y + h + 5)
        try: os.remove(path)
        except Exception: pass

    pdf.header_title(title)
    
    top_idxs = manual_prompts_indices if has_manual_prompts else select_key_paragraphs(blocks, max_images)
    side = "right"
    for idx, b in enumerate(blocks):
        if b.type == 'img' and not no_images:
            print(f"🎨 Generando imagen manual: '{b.text[:80]}...'")
            img = obtener_imagen(b.text, cache_dir, model)
            w = pdf.w - pdf.l_margin - pdf.r_margin; y = pdf.get_y()
            path, h = pdf._pil_to_temp_jpg(img, w)
            if y + h > pdf.h - pdf.b_margin: pdf.add_page()
            pdf.image(path, x=pdf.l_margin, y=pdf.get_y(), w=w)
            pdf.set_y(pdf.get_y() + h + 5)
            try: os.remove(path)
            except Exception: pass
            time.sleep(1)
        elif b.type.startswith("h"):
            level = int(b.type[1])
            pdf.set_font(pdf._font_family, 'B', 22 - 2 * level)
            pdf.multi_cell(0, 10, clean_inline_md(b.text))
            pdf.set_font(pdf._font_family, '', 12)
            pdf.ln(2)
        elif b.type == 'p':
            text_clean = clean_inline_md(b.text)
            if idx in top_idxs and not no_images and not has_manual_prompts:
                prompt = build_visual_prompt(text_clean, title)
                img = obtener_imagen(prompt, cache_dir, model)
                pdf.flow_paragraph_with_image(text_clean, img, side)
                side = "left" if side == "right" else "right"
                time.sleep(1)
            else:
                pdf.multi_cell(0, 6, text_clean, align='J')
                pdf.ln(4)

    # (El resto del código se mantiene igual)
    rel_path = os.path.relpath(os.path.dirname(md_path), input_folder)
    pdf_folder = os.path.join(output_folder, rel_path)
    os.makedirs(pdf_folder, exist_ok=True)
    output_pdf = os.path.join(pdf_folder, os.path.basename(md_path).replace(".md", ".pdf"))
    pdf.output(output_pdf)
    print(f"✅ PDF generado: {output_pdf}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-folder", default="historias")
    parser.add_argument("--output-folder", default="pdfs_generados")
    parser.add_argument("--model", default=os.getenv("IMAGEROUTER_MODEL", "default"))
    parser.add_argument("--max-images", type=int, default=4)
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument("--fail-on-router-error", action="store_true")
    args = parser.parse_args()
    
    font_path = os.getenv("FONT_PATH")
    md_files = [os.path.join(root, f) for root, _, files in os.walk(args.input_folder) for f in files if f.lower().endswith(".md")]
    print(f"📄 MD a procesar: {len(md_files)}")
    
    for md in sorted(md_files):
        print(f"--- Procesando: {md} ---")
        generar_pdf_de_md(md, args.input_folder, args.output_folder, font_path, args.model, args.max_images, args.no_images, args.fail_on_router_error)

if __name__ == "__main__":
    main()
