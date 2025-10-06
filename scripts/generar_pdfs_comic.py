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

# (El código de importación y configuración inicial se mantiene igual)
HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
for p in (HERE, PARENT):
    s = str(p)
    if s not in sys.path: sys.path.insert(0, s)

try:
    from imagerouter_client import (generate_image_via_imagerouter, ImageRouterError, ImageRouterBillingRequired)
except ModuleNotFoundError:
    from scripts.imagerouter_client import (generate_image_via_imagerouter, ImageRouterError, ImageRouterBillingRequired)

try:
    from scripts.prompt_synthesizer import build_visual_prompt
except Exception:
    ABSTRACT = {"idea","concepto","teoría","historia","cultura","sistema","proceso","método","información","cantidad","tiempo","serie","conjunto","uso","necesidad","tecnología","herramienta","algoritmo","posicional","invención","viaje","origen","números","matemáticas","clase","práctica","registro"}
    NEGATIVE = "watermark, logo, text overlay, subtítulos, texto, marcas de agua, caption, screenshot"
    def _clean_text_fallback(s: str) -> str: return re.sub(r'\s+', ' ', re.sub(r'__(.+?)__', r'\1', re.sub(r'\*\*(.+?)\*\*', r'\1', s))).strip()
    def build_visual_prompt(text: str, doc_title: str = "") -> str:
        raw = _clean_text_fallback(f"{doc_title}. {text}") if doc_title else _clean_text_fallback(text)
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\-']{3,}", raw)
        lower = [w.lower() for w in words]
        verbs = [w for w in lower if w.endswith(("ar","er","ir","ando","endo","iendo","ado","ido"))][:2]
        nouns = [w for w in lower if w not in verbs]
        visual = [w for w in nouns if w not in ABSTRACT][:4]
        if not verbs: verbs = ["representar"]
        if not visual: visual = ["elementos clave del tema"]
        prompt = (f"ilustración educativa contemporánea, clara y legible. Escena principal: {', '.join(visual[:2])} {', '.join(verbs)}. Elementos: {', '.join(visual)}. Evitar: {NEGATIVE}.")
        return re.sub(r"\s{2,}", " ", prompt).strip()

# --- INICIO DE LA CORRECCIÓN ---

HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*)\s*$')
PROMPT_RE = re.compile(r'') # Expresión regular simplificada

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
        # Usamos re.search que es más flexible
        m_prompt = PROMPT_RE.search(line)
        if m_prompt:
            flush_para()
            # El grupo 1 siempre existirá en un match, incluso si es una cadena vacía
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

# --- FIN DE LA CORRECCIÓN ---


def clean_inline_md(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s); s = re.sub(r'__(.+?)__', r'\1', s)
    return re.sub(r'\s{2,}', ' ', s).strip()

def select_key_paragraphs(blocks: List[Block], max_images: int = 4) -> Set[int]:
    paragraph_indices = [i for i, b in enumerate(blocks) if b.type == "p"]
    para_texts = []
    last_heading_level: Optional[int] = None
    for i, b in enumerate(blocks):
        if b.type.startswith("h"): last_heading_level = int(b.type[1])
        elif b.type == "p": para_texts.append((i, b.text, last_heading_level))
    scored: List[float] = []
    for _, text, hlevel in para_texts:
        score = 0.0; L = len(text); score += min(L / 400.0, 1.5)
        if hlevel in (2, 3): score += 0.6
        if any(kw in text.lower() for kw in ["definición", "concepto", "importante", "clave"]): score += 0.7
        if L < 80: score -= 0.6
        if re.match(r'^\s*([-*+]|\d+\.)\s+', text): score -= 0.8
        if "```" in text: score -= 1.0
        scored.append(score)
    ranked = sorted(enumerate(scored), key=lambda x: x[1], reverse=True)[:max_images]
    return set(paragraph_indices[idx] for idx, _ in ranked)

class ComicPDF(FPDF):
    def __init__(self, font_path: Optional[str] = None):
        super().__init__(orientation="P", unit="mm", format="A4"); self.set_margins(18, 18, 18)
        self.set_auto_page_break(auto=True, margin=16); self._font_family = "helvetica"; self._init_fonts(font_path)
    def _init_fonts(self, font_path: Optional[str]):
        base_dir = os.path.dirname(font_path) if (font_path and os.path.isfile(font_path)) else "/usr/share/fonts/truetype/dejavu"
        try:
            reg = os.path.join(base_dir, "DejaVuSans.ttf"); bold = os.path.join(base_dir, "DejaVuSans-Bold.ttf")
            ital = os.path.join(base_dir, "DejaVuSans-Oblique.ttf"); boldital = os.path.join(base_dir, "DejaVuSans-BoldOblique.ttf")
            if os.path.isfile(reg): self.add_font("DejaVu", style="", fname=reg); self._font_family = "DejaVu"
            if os.path.isfile(bold): self.add_font("DejaVu", style="B", fname=bold)
            if os.path.isfile(ital): self.add_font("DejaVu", style="I", fname=ital)
            if os.path.isfile(boldital): self.add_font("DejaVu", style="BI", fname=boldital)
        except Exception as e: print(f"[AVISO] No se pudieron cargar fuentes DejaVu: {e}")
    def use_font(self, style: str = "", size: int = 12): self.set_font(self._font_family, style=style, size=size)
    def header_title(self, title: str): self.use_font(style="B", size=20); self.set_text_color(30, 30, 120); self.multi_cell(0, 10, title, align="C"); self.ln(3); self.set_text_color(0, 0, 0)
    def footer(self): self.set_y(-15); self.use_font(size=10); self.set_text_color(120, 120, 120); self.cell(0, 10, f'Página {self.page_no()}', align='C')
    def _pil_to_temp_jpg(self, img: Image.Image, w_mm: float):
        iw, ih = img.size; h_mm = w_mm * (ih / iw) if iw else w_mm
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            path = tmp.name; img.convert("RGB").save(path, "JPEG", quality=90, optimize=True)
        return path, h_mm
    def flow_paragraph_with_image(self, text: str, img: Image.Image, side: str = "right", img_w_mm: float = 70.0, gutter_mm: float = 6.0, line_h: float = 6.0):
        text = clean_inline_md(text); l, r = self.l_margin, self.r_margin; usable_w = self.w - l - r
        text_w = usable_w - img_w_mm - gutter_mm;
        if text_w < 48: text_w = usable_w; img_w_mm = 0.0
        lines = self.multi_cell(text_w if img_w_mm > 0 else usable_w, line_h, text, align='J', dry_run=True, output="LINES")
        if isinstance(lines, dict) and "lines" in lines: lines = lines["lines"]
        text_h = len(lines) * line_h; y_start = self.get_y(); bottom = self.h - self.b_margin
        img_path, img_h = (None, 0.0)
        if img_w_mm > 0: img_path, img_h = self._pil_to_temp_jpg(img, img_w_mm)
        if y_start + max(text_h, img_h) > bottom: self.add_page(); y_start = self.get_y()
        if img_w_mm > 0 and img_path:
            x_img = self.w - r - img_w_mm if side == "right" else l
            x_text = l if side == "right" else l + img_w_mm + gutter_mm
            self.image(img_path, x=x_img, y=y_start, w=img_w_mm)
            try: os.remove(img_path)
            except Exception: pass
        else: x_text = l
        self.set_xy(x_text, y_start); self.multi_cell(text_w if img_w_mm > 0 else usable_w, line_h, text, align='J')
        self.set_xy(l, max(y_start + img_h, self.get_y()) + 4.0)

def obtener_imagen(prompt: str, cache_dir: str, model: str) -> Image.Image:
    import hashlib
    h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    out_dir = os.path.join(cache_dir, "imagerouter"); os.makedirs(out_dir, exist_ok=True)
    cached_png = os.path.join(out_dir, f"{h}.png")
    if os.path.isfile(cached_png):
        try: return Image.open(cached_png).convert("RGB")
        except Exception:
            try: os.remove(cached_png)
            except Exception: pass
    seed = int(h, 16) % 2_147_483_647
    try:
        png_real = generate_image_via_imagerouter(prompt=prompt, out_dir=out_dir, model=model, size="512x512", seed=seed, timeout=600)
        if png_real != cached_png:
            try: os.replace(png_real, cached_png)
            except Exception:
                if not os.path.isfile(cached_png): import shutil; shutil.copyfile(png_real, cached_png)
        return Image.open(cached_png).convert("RGB")
    except ImageRouterBillingRequired as e: raise
    except Exception as e:
        print(f"[AVISO] ImageRouter falló ({e}); usando placeholder")
        W, H = 512, 512; img = Image.new("RGB", (W, H), (14, 18, 32))
        draw = ImageDraw.Draw(img); draw.rectangle([(24, 24), (W - 24, H - 24)], outline=(233, 238, 248), width=2)
        return img

def generar_pdf_de_md(md_path: str, input_folder: str, output_folder: str, font_path: Optional[str], model: str, max_images: int, no_images: bool = False, fail_on_router_error: bool = False):
    with open(md_path, "r", encoding="utf-8") as f: text = f.read()
    blocks, actividades, title_h1 = parse_markdown(text)
    title = title_h1 or os.path.splitext(os.path.basename(md_path))[0]
    cache_dir = os.path.join(output_folder, "_cache_imgs")
    pdf = ComicPDF(font_path=font_path); pdf.set_title(title); pdf.add_page()
    manual_prompts_indices = {i for i, b in enumerate(blocks) if b.type == 'img'}
    has_manual_prompts = bool(manual_prompts_indices)
    if not no_images and not has_manual_prompts:
        try:
            portada_prompt = build_visual_prompt("Portada del documento", title)
            portada_img = obtener_imagen(portada_prompt, cache_dir, model=model)
            img_w = pdf.w - pdf.l_margin - pdf.r_margin; y0 = pdf.get_y()
            path_tmp, h_mm = pdf._pil_to_temp_jpg(portada_img, w_mm=img_w)
            pdf.image(path_tmp, x=pdf.l_margin, y=y0, w=img_w)
            try: os.remove(path_tmp)
            except Exception: pass
            pdf.set_y(y0 + h_mm + 5)
        except Exception as e: print(f"[AVISO] Falló la imagen de portada: {e}")
    pdf.header_title(title)
    top_idxs = manual_prompts_indices if has_manual_prompts else select_key_paragraphs(blocks, max_images)
    side = "right"
    for idx, b in enumerate(blocks):
        if b.type.startswith("h"):
            level = int(b.type[1])
            if level == 2 and b.text.strip().lower() == "actividades": continue
            pdf.use_font(style="B", size=18 - 2 * (level - 2)); pdf.ln(1)
            pdf.multi_cell(0, 7, clean_inline_md(b.text)); pdf.ln(2); pdf.use_font(size=12)
            continue
        if b.type == 'img' and idx in top_idxs and not no_images:
            try:
                print(f"🎨 Generando imagen con prompt manual: '{b.text[:80]}...'")
                img = obtener_imagen(b.text, cache_dir, model=model)
                img_w = pdf.w - pdf.l_margin - pdf.r_margin; y0 = pdf.get_y()
                path_tmp, h_mm = pdf._pil_to_temp_jpg(img, w_mm=img_w)
                if y0 + h_mm > pdf.h - pdf.b_margin: pdf.add_page(); y0 = pdf.get_y()
                pdf.image(path_tmp, x=pdf.l_margin, y=y0, w=img_w)
                pdf.set_y(y0 + h_mm + 5)
                try: os.remove(path_tmp)
                except Exception: pass
                time.sleep(1)
            except Exception as e: print(f"[AVISO] Falló la generación de imagen manual: {e}")
        elif b.type == 'p':
            text_clean = clean_inline_md(b.text)
            if idx in top_idxs and not no_images and not has_manual_prompts:
                try:
                    prompt = build_visual_prompt(text_clean, title)
                    img = obtener_imagen(prompt, cache_dir, model=model)
                    pdf.flow_paragraph_with_image(text_clean, img, side=side)
                    side = "left" if side == "right" else "right"
                    time.sleep(1)
                except Exception as e:
                    print(f"[AVISO] Falló la generación de imagen automática: {e}")
                    pdf.multi_cell(0, 6, text_clean, align='J'); pdf.ln(2)
            else:
                pdf.multi_cell(0, 6, text_clean, align='J'); pdf.ln(2)
    if actividades:
        pdf.add_page(); pdf.use_font(style="B", size=18); pdf.set_text_color(30, 100, 30)
        pdf.multi_cell(0, 10, "Actividades", align='C'); pdf.ln(5)
        pdf.set_text_color(0, 0, 0); pdf.use_font(size=12)
        for act in actividades: pdf.multi_cell(0, 6, f"• {clean_inline_md(act)}"); pdf.ln(2)
    rel_path = os.path.relpath(os.path.dirname(md_path), input_folder)
    pdf_folder = os.path.join(output_folder, rel_path); os.makedirs(pdf_folder, exist_ok=True)
    output_pdf = os.path.join(pdf_folder, os.path.basename(md_path).replace(".md", ".pdf"))
    pdf.output(output_pdf)
    print(f"✅ PDF generado: {output_pdf}")

def main():
    parser = argparse.ArgumentParser(description="Genera PDFs con imágenes");
    parser.add_argument("--input-folder", default="historias"); parser.add_argument("--output-folder", default="pdfs_generados")
    parser.add_argument("--model", default=os.getenv("IMAGEROUTER_MODEL", "runware:101@1")); parser.add_argument("--max-images", type=int, default=int(os.getenv("MAX_IMAGES", "6")))
    parser.add_argument("--no-images", action="store_true"); parser.add_argument("--fail-on-router-error", action="store_true")
    args = parser.parse_args();
    font_path = os.getenv("FONT_PATH");
    md_list = [os.path.join(r, f) for r, _, fs in os.walk(args.input_folder) for f in fs if f.lower().endswith(".md")]
    print(f"📄 MD a procesar: {len(md_list)}")
    if not md_list: print("⚠️ No se encontraron .md"); return
    for md in sorted(md_list):
        generar_pdf_de_md(md, args.input_folder, args.output_folder, font_path=font_path, model=args.model, max_images=args.max_images, no_images=args.no_images, fail_on_router_error=args.fail_on_router_error)

if __name__ == "__main__":
    main()
