#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import argparse
import textwrap
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image, ImageDraw

# --- Robustez de imports: permite ejecutar con `python scripts/...` o `python -m scripts...`
from pathlib import Path
HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

try:
    # Ejecutando como script: python scripts/generar_pdfs_comic.py
    from imagerouter_client import generate_image_via_imagerouter, ImageRouterError
except ModuleNotFoundError:
    # Ejecutando como módulo: python -m scripts.generar_pdfs_comic
    from scripts.imagerouter_client import generate_image_via_imagerouter, ImageRouterError


# ---------- Parsing MD muy simple ----------
HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*)\s*$')

@dataclass
class Block:
    type: str   # 'h1'..'h6' o 'p'
    text: str


def parse_markdown(text: str) -> Tuple[List[Block], List[str], str]:
    """
    Devuelve (blocks, actividades, title_h1)
    - blocks: secuencia de 'h#' y 'p'
    - actividades: líneas bajo H2 "Actividades"
    - title_h1: título del documento si existe
    """
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

    last_line_blank = False
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            flush_para()
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            if level == 1 and not title_h1:
                title_h1 = heading_text
            if level == 2:
                in_actividades = (heading_text.lower() == "actividades")
            blocks.append(Block(f'h{level}', heading_text))
            last_line_blank = False
            continue

        if in_actividades:
            if line.strip():
                actividades.append(line.strip())
            last_line_blank = (line.strip() == "")
            continue

        if line.strip() == "":
            if not last_line_blank:
                flush_para()
            last_line_blank = True
        else:
            current_para.append(line)
            last_line_blank = False

    flush_para()
    return blocks, actividades, (title_h1 or "")


def clean_inline_md(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = s.replace(r'\(', '(').replace(r'\)', ')').replace(r'\*', '*')
    s = re.sub(r'[\U00013000-\U0001342F]', '', s)  # evita jeroglíficos que faltan en DejaVu
    s = re.sub(r'\s{2,}', ' ', s).strip()
    return s


# ---------- Selección de párrafos clave ----------
KEYWORDS = ["definición", "concepto", "importante", "clave", "conclusión", "ejemplo", "problema"]


def select_key_paragraphs(blocks: List[Block], max_images: int = 4) -> Set[int]:
    """
    Devuelve el conjunto de índices (en la secuencia 'blocks') de los párrafos más importantes.
    Criterios: longitud, proximidad a H2/H3, palabras clave.
    """
    paragraph_indices = []
    para_texts = []
    last_heading_level = None

    for i, b in enumerate(blocks):
        if b.type.startswith("h"):
            last_heading_level = int(b.type[1])
        elif b.type == "p":
            paragraph_indices.append(i)
            para_texts.append((i, b.text, last_heading_level))

    scored = []
    for _, text, hlevel in para_texts:
        score = 0.0
        L = len(text)
        score += min(L / 400.0, 1.5)  # longitud (hasta 1.5)
        if hlevel in (2, 3):
            score += 0.6              # primer párrafo tras H2/H3
        low = text.lower()
        if any(kw in low for kw in KEYWORDS):
            score += 0.7              # palabra clave
        scored.append(score)

    ranked = sorted(enumerate(scored), key=lambda x: x[1], reverse=True)[:max_images]
    top_block_idxs = [paragraph_indices[idx] for idx, _ in ranked]
    top_block_idxs.sort()
    return set(top_block_idxs)


# ---------- Perfiles demográficos y prompts ----------
DEMOGRAPHIC_PROFILES = [
    # Español/a
    {"origen": "español",      "genero": "chico", "detalle": "pelo corto o rizado, ropa urbana o sudadera/vaqueros"},
    {"origen": "española",     "genero": "chica", "detalle": "pelo suelto o recogido, ropa casual o deportiva"},
    # Marroquí
    {"origen": "marroquí",     "genero": "chico", "detalle": "pelo corto o rizado, ropa cotidiana juvenil; sin estereotipos"},
    {"origen": "marroquí",     "genero": "chica", "detalle": "pelo suelto o recogido; hiyab opcional y respetuoso; ropa cotidiana juvenil"},
    # Subsahariano/a
    {"origen": "subsahariano", "genero": "chico", "detalle": "pelo corto o trenzas cortas, ropa casual juvenil"},
    {"origen": "subsahariana", "genero": "chica", "detalle": "trenzas o afro, ropa casual juvenil"},
]


def next_profiles(idx: int) -> List[dict]:
    """
    Devuelve una mezcla de 3 perfiles rotando el pool para diversidad.
    """
    base = DEMOGRAPHIC_PROFILES
    start = (idx * 2) % len(base)
    sel = [base[start], base[(start + 1) % len(base)], base[(start + 2) % len(base)]]
    return sel


def build_prompt_demo(paragraph: str, title: str, style: str, perfiles: List[dict]) -> str:
    """
    Prompt seguro y neutro para ilustrar adolescentes (12–16) diversos (españoles, marroquíes, subsaharianos).
    Evita texto/estereotipos/sexualización; contexto escolar/calle; ropa cotidiana.
    """
    common = (
        "Ilustración de adolescentes de 12 a 16 años, sin texto sobreimpreso, sin marcas de agua, sin logos. "
        "Vestimenta cotidiana (escolar o de calle), sin sexualización, postura natural y respetuosa. "
        "Evitar estereotipos culturales; representación inclusiva y realista. "
        "Composición clara y legible centrada en la idea principal del párrafo. "
    )

    if style == "infografia":
        style_txt = "Estilo infográfico minimalista, colores planos suaves, iconografía simple, fondo limpio. "
    elif style == "boceto-pizarra":
        style_txt = "Estilo boceto/rotulador tipo pizarra, trazos definidos, fondo claro, aspecto didáctico. "
    elif style == "fotoreal":
        style_txt = "Estilo fotográfico realista, iluminación suave, profundidad moderada, escena natural. "
    else:
        style_txt = "Estilo ilustración contemporánea neutra, colores equilibrados, detalles moderados. "

    mix_txt = []
    for p in perfiles:
        mix_txt.append(f"{p['genero']} {p['origen']} ({p['detalle']})")
    demographic = "Diversidad visible: " + ", ".join(mix_txt) + ". "

    topic = f"Tema: {title}. "
    content = f"Escena basada en el párrafo (resumir idea principal): {paragraph}"

    return common + style_txt + demographic + topic + content


# ---------- PDF ----------
class ComicPDF(FPDF):
    def __init__(self, font_path: Optional[str] = None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(auto=True, margin=16)
        self._font_family = "helvetica"
        self._font_path = font_path
        self._font_ready = False
        self._has_b = self._has_i = self._has_bi = False
        self._init_fonts()

    def _init_fonts(self):
        base_dir = os.path.dirname(self._font_path) if (self._font_path and os.path.isfile(self._font_path)) \
            else "/usr/share/fonts/truetype/dejavu"
        reg = os.path.join(base_dir, "DejaVuSans.ttf")
        bold = os.path.join(base_dir, "DejaVuSans-Bold.ttf")
        ital = os.path.join(base_dir, "DejaVuSans-Oblique.ttf")
        boldital = os.path.join(base_dir, "DejaVuSans-BoldOblique.ttf")
        try:
            if os.path.isfile(reg):
                self.add_font("DejaVu", style="", fname=reg)
                self._font_family = "DejaVu"
                self._font_ready = True
            if os.path.isfile(bold):
                self.add_font("DejaVu", style="B", fname=bold)
                self._has_b = True
            if os.path.isfile(ital):
                self.add_font("DejaVu", style="I", fname=ital)
                self._has_i = True
            if os.path.isfile(boldital):
                self.add_font("DejaVu", style="BI", fname=boldital)
                self._has_bi = True
        except Exception as e:
            print(f"[AVISO] Fuentes DejaVu incompletas: {e}")

    def use_font(self, style: str = "", size: int = 12):
        if self._font_family.lower() == "dejavu":
            up = "".join(sorted(set(style.upper())))
            if up == "BI" and self._has_bi:
                self.set_font("DejaVu", style="BI", size=size)
                return
            if up == "B" and self._has_b:
                self.set_font("DejaVu", style="B", size=size)
                return
            if up == "I" and self._has_i:
                self.set_font("DejaVu", style="I", size=size)
                return
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

    def _pil_to_temp_jpg(self, img, w_mm: float):
        iw, ih = img.size
        h_mm = w_mm * (ih / iw)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            path = tmp.name
        img_rgb = img.convert("RGB")
        img_rgb.save(path, "JPEG", quality=90, optimize=True)
        return path, h_mm

    def flow_paragraph_with_image(self, text: str, img, side: str = "right",
                                  img_w_mm: float = 70.0, gutter_mm: float = 6.0,
                                  line_h: float = 6.0):
        text = clean_inline_md(text)
        l, r = self.l_margin, self.r_margin
        usable_w = self.w - l - r
        text_w = usable_w - img_w_mm - gutter_mm
        if text_w < 48:
            text_w = usable_w
            img_w_mm = 0.0

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
            try:
                os.remove(img_path)
            except Exception:
                pass
        else:
            x_text = l
            text_w = usable_w

        self.set_xy(x_text, y_start)
        self.multi_cell(text_w, line_h, text, align='J')
        y_text_end = self.get_y()
        y_next = max(y_start + img_h, y_text_end) + 4.0
        self.set_xy(l, y_next)


# ---------- Imagen vía ImageRouter ----------
def obtener_imagen(prompt: str, cache_dir: str, model: str) -> "Image.Image":
    """
    Pide la imagen a ImageRouter y usa caché por hash del prompt.
    Fallo → placeholder seguro (sin texto).
    """
    from PIL import Image
    import hashlib

    h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    out_dir = os.path.join(cache_dir, "imagerouter")
    os.makedirs(out_dir, exist_ok=True)
    cached = os.path.join(out_dir, f"{h}.png")
    if os.path.isfile(cached):
        return Image.open(cached).convert("RGB")

    try:
        png_real = generate_image_via_imagerouter(
            prompt=prompt,
            out_dir=out_dir,
            model=model,
            size="1024x768",
            steps=20,
            guidance=4.0,
            seed=None
        )
        os.replace(png_real, cached)
        return Image.open(cached).convert("RGB")
    except Exception as e:
        print(f"[AVISO] ImageRouter falló ({e}); usando placeholder")
        W, H = 1024, 640
        img = Image.new("RGB", (W, H), (14, 18, 32))
        draw = ImageDraw.Draw(img)
        # placeholder sin texto
        draw.rectangle([(24, 24), (W - 24, H - 24)], outline=(233, 238, 248), width=2)
        return img


# ---------- Generador principal ----------
def generar_pdf_de_md(md_path: str, input_folder: str, output_folder: str,
                      font_path: Optional[str], model: str, style: str, max_images: int):
    # Leer MD
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    blocks, actividades, title_h1 = parse_markdown(text)
    filename_title = os.path.splitext(os.path.basename(md_path))[0]
    title = title_h1 or filename_title

    cache_dir = os.path.join(output_folder, "_cache_imgs")

    # Portada (ya muestra diversidad también)
    portada_perfiles = next_profiles(0)
    portada_prompt = build_prompt_demo("Portada del documento", title, style=style, perfiles=portada_perfiles)
    portada_img = obtener_imagen(portada_prompt, cache_dir, model=model)

    pdf = ComicPDF(font_path=font_path)
    pdf.set_title(title)
    pdf.set_author("Proyecto educativo")

    pdf.add_page()
    path_tmp, _ = pdf._pil_to_temp_jpg(portada_img, w_mm=(pdf.w - pdf.l_margin - pdf.r_margin))
    pdf.image(path_tmp, x=pdf.l_margin, y=pdf.get_y(), w=(pdf.w - pdf.l_margin - pdf.r_margin))
    try:
        os.remove(path_tmp)
    except Exception:
        pass
    pdf.ln(5)
    pdf.header_title(title)
    pdf.use_font(size=12)

    # Elegimos los párrafos clave
    top_block_idxs = select_key_paragraphs(blocks, max_images=max_images)

    side = "right"
    img_counter = 1  # 0 ya usado por portada

    for idx, b in enumerate(blocks):
        if b.type.startswith("h"):
            level = int(b.type[1])
            if level == 2 and b.text.strip().lower() == "actividades":
                continue
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
            if idx in top_block_idxs:
                perfiles = next_profiles(img_counter)
                prompt = build_prompt_demo(text_clean, title, style=style, perfiles=perfiles)
                img = obtener_imagen(prompt, cache_dir, model=model)
                pdf.flow_paragraph_with_image(text_clean, img, side=side, img_w_mm=70.0)
                side = "left" if side == "right" else "right"
                img_counter += 1
            else:
                pdf.multi_cell(0, 6, text_clean, align='J')
                pdf.ln(2)

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
    parser = argparse.ArgumentParser(
        description="Genera PDFs con imágenes integradas (ImageRouter, párrafos clave y diversidad 12–16)"
    )
    parser.add_argument("--input-folder", default="historias", help="Carpeta base de entrada")
    parser.add_argument("--output-folder", default="pdfs_generados", help="Carpeta base de salida")
    parser.add_argument(
        "--model",
        default=os.getenv("IMAGEROUTER_MODEL", "black-forest-labs/FLUX-1-schnell:free"),
        help="Modelo en ImageRouter (p.ej. 'stabilityai/sdxl-turbo:free')"
    )
    parser.add_argument(
        "--style",
        default=os.getenv("PROMPT_STYLE", "neutral"),
        choices=["neutral", "infografia", "boceto-pizarra", "fotoreal"],
        help="Estilo del prompt"
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=int(os.getenv("MAX_IMAGES", "4")),
        help="Número de párrafos importantes a ilustrar"
    )
    args = parser.parse_args()

    font_path = os.getenv("FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not os.path.isfile(font_path):
        print(f"[AVISO] Fuente Unicode no encontrada en {font_path}. Se usará Helvetica (ASCII).")

    md_list = listar_md(args.input_folder)
    print(f"📄 MD a procesar: {len(md_list)}")
    if not md_list:
        print("⚠️ No se encontraron .md en la carpeta de entrada.")
        return

    for md in md_list:
        try:
            generar_pdf_de_md(
                md,
                args.input_folder,
                args.output_folder,
                font_path=font_path,
                model=args.model,
                style=args.style,
                max_images=args.max_images
            )
        except Exception as e:
            print(f"❌ Error procesando {md}: {e}")


if __name__ == "__main__":
    main()
