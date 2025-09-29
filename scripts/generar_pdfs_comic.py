#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import io
import argparse
import textwrap
import tempfile
from dataclasses import dataclass
from typing import List, Tuple, Optional

import requests
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

# --------------------------
# Parsing Markdown muy simple
# --------------------------
HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*)\s*$')

@dataclass
class Block:
    type: str   # 'h1'..'h6' o 'p'
    text: str

def parse_markdown(text: str) -> Tuple[List['Block'], List[str], List[str], str]:
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
            flush_para()
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            if level == 1 and not title_h1:
                title_h1 = heading_text
            if level == 2:
                if heading_text.lower() == "actividades":
                    in_actividades = True
                else:
                    in_actividades = False
                h2_list.append(heading_text)
            if in_actividades and heading_text.lower() != "actividades":
                in_actividades = False
            blocks.append(Block(f'h{level}', heading_text))
            continue

        if in_actividades:
            if line.strip():
                actividades.append(line.strip())
            continue

        if line.strip() == "":
            flush_para()
        else:
            current_para.append(line)

    flush_para()
    return blocks, h2_list, actividades, (title_h1 or "")

def clean_inline_md(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)  # **negrita**
    s = re.sub(r'__(.+?)__', r'\1', s)      # __negrita__
    s = s.replace(r'\(', '(').replace(r'\)', ')').replace(r'\*', '*')
    # Evitar glifos jeroglíficos que no cubre DejaVu Sans:
    s = re.sub(r'[\U00013000-\U0001342F]', '', s)
    s = re.sub(r'\s{2,}', ' ', s).strip()
    return s

# --------------------------
# Imágenes: Unsplash Source + filtro "cómic" con PIL
# --------------------------
STOPWORDS_ES = set("""
un una unas unos uno sobre todo tambien tras otro algun alguno alguna algunos algunas
ser es soy eres somos sois estoy esta estamos estais estan como en para atras porque por que
estado estaba ante antes siendo ambos pero por poder puede puedo podemos pueden fui fue fuimos
fueron hacer hago hace hacemos hacen cada fin incluso primero desde conseguir consigo consigue
consigues conseguimos consiguen ir voy va vamos van venir vengo viene venimos vienen
""".split())

def keywords_from_text(text: str, max_words: int = 6) -> str:
    # Muy simple: primeras palabras "significativas"
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", text)
    filtered = [t for t in tokens if t.lower() not in STOPWORDS_ES and len(t) > 2]
    return " ".join(filtered[:max_words]) or "educacion matematica"

def fetch_unsplash_image(query: str, width: int = 1024, height: int = 640, timeout: int = 30) -> Optional[Image.Image]:
    # Unsplash Source devuelve una redirección a una imagen libre de uso (educativo)
    # https://source.unsplash.com/ (no requiere API key)
    url = f"https://source.unsplash.com/{width}x{height}/?{requests.utils.quote(query)}"
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and r.content:
            return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as e:
        print(f"[AVISO] Unsplash error: {e}")
    return None

def comicize(img: Image.Image) -> Image.Image:
    # Look tipo cómic: posterize + edges suave
    base = img.resize((img.width, img.height), Image.LANCZOS)
    poster = ImageOps.posterize(base, 3)  # pocos niveles de color
    edges = base.convert("L").filter(ImageFilter.FIND_EDGES)
    edges = ImageOps.autocontrast(edges).filter(ImageFilter.SMOOTH_MORE)
    edges_col = ImageOps.colorize(edges, black=(0,0,0), white=(255,255,255))
    # mezclar: multiplicar bordes suaves sobre poster
    blended = Image.blend(poster, edges_col, alpha=0.25)
    return blended

class ImageGen:
    def __init__(self, font_path: Optional[str]=None):
        self.font_path = font_path

    def generate(self, prompt: str, width: int = 960, height: int = 600) -> Image.Image:
        q = keywords_from_text(prompt)
        img = fetch_unsplash_image(q, width=width, height=height)
        if img is None:
            # fallback: tarjeta placeholder agradable
            return make_placeholder(f"Escena: {q}", size=(width, height), font_path=self.font_path)
        return comicize(img)

# Placeholder bonito si falla todo
def load_font_for_placeholder(font_path: Optional[str], size: int) -> ImageFont.ImageFont:
    try:
        if font_path and os.path.isfile(font_path):
            return ImageFont.truetype(font_path, size)
    except Exception:
        pass
    return ImageFont.load_default()

def make_placeholder(prompt: str, size=(768, 480), bg=(14, 18, 32), fg=(233, 238, 248), font_path: Optional[str]=None) -> Image.Image:
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    title = "Ilustración tipo cómic"
    body = textwrap.shorten(prompt.replace("\n", " "), width=200, placeholder="…")
    font_title = load_font_for_placeholder(font_path, 32)
    font_body = load_font_for_placeholder(font_path, 20)
    tw, th = draw.textbbox((0, 0), title, font=font_title)[2:]
    bw, bh = draw.textbbox((0, 0), body, font=font_body)[2:]
    W, H = img.size
    y0 = (H - (th + 18 + bh)) // 2
    draw.text(((W - tw)//2, y0), title, font=font_title, fill=fg)
    draw.text(((W - bw)//2, y0 + th + 18), body, font=font_body, fill=fg)
    return img

# --------------------------
# PDF con texto rodeando imagen
# --------------------------
class ComicPDF(FPDF):
    def __init__(self, font_path: Optional[str] = None):
        super().__init__(orientation="P", unit="mm", format="A4")
        # Márgenes suaves
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(auto=True, margin=16)
        self._font_family = "helvetica"  # fallback ASCII
        self._font_path = font_path
        self._font_ready = False
        self._has_b = self._has_i = self._has_bi = False
        self._init_fonts()

    def _init_fonts(self):
        base_dir = os.path.dirname(self._font_path) if (self._font_path and os.path.isfile(self._font_path)) \
                   else "/usr/share/fonts/truetype/dejavu"
        reg  = os.path.join(base_dir, "DejaVuSans.ttf")
        bold = os.path.join(base_dir, "DejaVuSans-Bold.ttf")
        ital = os.path.join(base_dir, "DejaVuSans-Oblique.ttf")
        boldital = os.path.join(base_dir, "DejaVuSans-BoldOblique.ttf")
        try:
            if os.path.isfile(reg):
                self.add_font("DejaVu", style="",  fname=reg)
                self._font_family = "DejaVu"
                self._font_ready = True
            if os.path.isfile(bold):
                self.add_font("DejaVu", style="B", fname=bold); self._has_b = True
            if os.path.isfile(ital):
                self.add_font("DejaVu", style="I", fname=ital); self._has_i = True
            if os.path.isfile(boldital):
                self.add_font("DejaVu", style="BI", fname=boldital); self._has_bi = True
        except Exception as e:
            print(f"[AVISO] Fuentes DejaVu incompletas: {e}")

    def use_font(self, style: str = "", size: int = 12):
        if self._font_family.lower() == "dejavu":
            up = "".join(sorted(set(style.upper())))
            if up == "BI" and self._has_bi: self.set_font("DejaVu", style="BI", size=size); return
            if up == "B"  and self._has_b:  self.set_font("DejaVu", style="B",  size=size); return
            if up == "I"  and self._has_i:  self.set_font("DejaVu", style="I",  size=size); return
            self.set_font("DejaVu", style="", size=size)
        else:
            self.set_font(self._font_family, style="", size=size)

    def header_title(self, title: str):
        self.use_font(style="B", size=20)
        self.set_text_color(30, 30, 120)
        self.multi_cell(0, 10, title, align="C")
        self.ln(3)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-15)
        self.use_font(size=10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f'Página {self.page_no()}', new_x=XPos.RIGHT, new_y=YPos.TOP, align='C')

    def _pil_to_temp_jpg(self, img: Image.Image, w_mm: float) -> Tuple[str, float]:
        iw, ih = img.size
        h_mm = w_mm * (ih / iw)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            path = tmp.name
        img_rgb = img.convert("RGB")
        img_rgb.save(path, "JPEG", quality=90, optimize=True)
        return path, h_mm

    def flow_paragraph_with_image(self, text: str, img: Image.Image, side: str = "right",
                                  img_w_mm: float = 70.0, gutter_mm: float = 6.0,
                                  line_h: float = 6.0):
        """
        Coloca una imagen a un lado y fluye el texto en el espacio restante,
        continuando debajo de la imagen si hace falta.
        """
        text = clean_inline_md(text)
        l, r = self.l_margin, self.r_margin
        usable_w = self.w - l - r
        text_w = usable_w - img_w_mm - gutter_mm
        if text_w < 48:  # evita columnas demasiado estrechas
            text_w = usable_w
            img_w_mm = 0.0

        # Medición (sin deprecations): dry_run=True, output="LINES"
        lines = self.multi_cell(
            text_w if img_w_mm > 0 else usable_w,
            line_h, text, align='J', dry_run=True, output="LINES"
        )
        if isinstance(lines, dict) and "lines" in lines:
            lines = lines["lines"]
        text_h = len(lines) * line_h

        y_start = self.get_y()
        bottom_limit = self.h - self.b_margin

        img_path, img_h = (None, 0.0)
        if img_w_mm > 0:
            img_path, img_h = self._pil_to_temp_jpg(img, img_w_mm)

        needed_h = max(text_h, img_h)
        if y_start + needed_h > bottom_limit:
            self.add_page()
            y_start = self.get_y()

        if img_w_mm > 0 and img_path:
            if side == "right":
                x_img = self.w - r - img_w_mm
                x_text = l
            else:
                x_img = l
                x_text = l + img_w_mm + gutter_mm
            self.image(img_path, x=x_img, y=y_start, w=img_w_mm)
            try: os.remove(img_path)
            except Exception: pass
        else:
            x_text = l
            text_w = usable_w

        self.set_xy(x_text, y_start)
        self.multi_cell(text_w, line_h, text, align='J')
        y_text_end = self.get_y()
        y_next = max(y_start + img_h, y_text_end) + 4.0
        self.set_xy(l, y_next)

# --------------------------
# Generador principal
# --------------------------
def generar_pdf_de_md(md_path: str, input_folder: str, output_folder: str, gen: ImageGen, font_path: Optional[str]):
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    blocks, h2_list, actividades, title_h1 = parse_markdown(text)
    filename_title = os.path.splitext(os.path.basename(md_path))[0]
    title = title_h1 or filename_title

    # Portada
    portada_prompt = f"Portada educativa estilo cómic, limpia, con símbolos numéricos sutiles (sin texto sobreimpreso). Título: {title}"
    cover_img = gen.generate(portada_prompt, width=1280, height=720)

    pdf = ComicPDF(font_path=font_path)
    pdf.set_title(title)
    pdf.set_author("MathGym / José Luis Cantón")

    pdf.add_page()
    path_tmp, _ = pdf._pil_to_temp_jpg(cover_img, w_mm=(pdf.w - pdf.l_margin - pdf.r_margin))
    pdf.image(path_tmp, x=pdf.l_margin, y=pdf.get_y(), w=(pdf.w - pdf.l_margin - pdf.r_margin))
    try: os.remove(path_tmp)
    except Exception: pass
    pdf.ln(5)
    pdf.header_title(title)
    pdf.use_font(size=12)

    # Imágenes integradas: hasta 6 párrafos, alternando lado
    paragraphs = [b.text for b in blocks if b.type == "p"]
    max_imgs = 6
    img_paras_idx = [i for i in range(min(max_imgs, len(paragraphs)))]
    side = "right"

    p_counter = 0
    for b in blocks:
        if b.type.startswith("h"):
            level = int(b.type[1])
            if level == 2 and b.text.strip().lower() == "actividades":
                continue  # H2 "Actividades" va en su propia página
            if level == 2:
                pdf.use_font(style="B", size=16)
                pdf.set_text_color(200, 30, 30)
                pdf.multi_cell(0, 8, clean_inline_md(b.text), align='J')
                pdf.ln(2)
                pdf.set_text_color(0, 0, 0)
                pdf.use_font(size=12)
            elif level == 3:
                pdf.use_font(style="B", size=14)
                pdf.multi_cell(0, 7, clean_inline_md(b.text), align='J')
                pdf.ln(1)
                pdf.use_font(size=12)
            continue

        if b.type == "p":
            text_clean = clean_inline_md(b.text)
            if p_counter in img_paras_idx:
                prompt = f"Escena: {text_clean}"
                img = gen.generate(prompt, width=960, height=600)
                pdf.flow_paragraph_with_image(text_clean, img, side=side, img_w_mm=70.0)
                side = "left" if side == "right" else "right"
            else:
                pdf.multi_cell(0, 6, text_clean, align='J')
                pdf.ln(2)
            p_counter += 1

    if actividades:
        pdf.add_page()
        pdf.use_font(style="B", size=18)
        pdf.set_text_color(30, 100, 30)
        pdf.multi_cell(0, 10, "Actividades", align='C')
        pdf.ln(5)
        pdf.set_text_color(0, 0, 0)
        pdf.use_font(size=12)
        for act in actividades:
            pdf.multi_cell(0, 6, f"• {clean_inline_md(act)}", align='J')
            pdf.ln(2)

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
    parser = argparse.ArgumentParser(description="Genera PDFs tipo cómic a partir de Markdown con imágenes integradas (sin GPU)")
    parser.add_argument("--input-folder", default="historias", help="Carpeta base de entrada")
    parser.add_argument("--output-folder", default="pdfs_generados", help="Carpeta base de salida")
    args = parser.parse_args()

    font_path = os.getenv("FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not os.path.isfile(font_path):
        print(f"[AVISO] Fuente Unicode no encontrada en {font_path}. Se usará Helvetica (ASCII).")

    gen = ImageGen(font_path=font_path)

    md_list = listar_md(args.input_folder)
    print(f"📄 MD a procesar: {len(md_list)}")
    if not md_list:
        print("⚠️ No se encontraron .md en la carpeta de entrada.")
        return

    for md in md_list:
        try:
            generar_pdf_de_md(md, args.input_folder, args.output_folder, gen, font_path=font_path)
        except Exception as e:
            print(f"❌ Error procesando {md}: {e}")

if __name__ == "__main__":
    main()
