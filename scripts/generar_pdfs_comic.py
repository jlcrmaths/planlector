#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import sys
import time
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image
import google.generativeai as genai

# --- CONFIGURACIÓN DE GOOGLE GEMINI ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    print("🚨 ERROR FATAL: No se encontró la variable de entorno GOOGLE_API_KEY.")
    print("   Asegúrate de definirla antes de ejecutar este script, por ejemplo:")
    print("   export GOOGLE_API_KEY='tu_clave_real_de_gemini'")
    sys.exit(1)

try:
    genai.configure(api_key=GOOGLE_API_KEY)
    print("✅ Cliente de Google Gemini configurado correctamente.")
except Exception as e:
    print(f"🚨 ERROR: La clave de API parece inválida o la conexión falló.\n   Detalles: {e}")
    sys.exit(1)


# --- FUNCIONES AUXILIARES ---

@dataclass
class Block:
    type: str
    text: str


HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*)\s*$')

def parse_markdown(text: str) -> Tuple[List[Block], str]:
    lines = text.splitlines()
    blocks: List[Block] = []
    title_h1: Optional[str] = None

    for line in lines:
        m_heading = HEADING_RE.match(line)
        if m_heading:
            level = len(m_heading.group(1))
            heading_text = m_heading.group(2).strip()
            if level == 1 and not title_h1:
                title_h1 = heading_text
            blocks.append(Block(f"h{level}", heading_text))
        elif line.strip():
            blocks.append(Block("p", line.strip()))

    return blocks, (title_h1 or "Documento sin título")


def clean_inline_md(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'\s*\n\s*', ' ', s)
    s = re.sub(r'([a-zA-Z])\)', r'\1)\n', s)  # fuerza salto tras a), b), c)
    return re.sub(r'\s{2,}', ' ', s).strip()


# --- GENERACIÓN DE IMÁGENES ---

def generate_image_with_gemini(prompt: str, out_dir: str, name_hint: str) -> str:
    """Genera imagen con resolución moderada (512x512) y la guarda en caché."""
    os.makedirs(out_dir, exist_ok=True)
    cache_file = os.path.join(out_dir, f"{name_hint}.png")
    if os.path.exists(cache_file):
        print(f"🖼️  Imagen en caché: {cache_file}")
        return cache_file

    print(f"🎨 Generando imagen para '{prompt[:60]}...'")

    try:
        model = genai.GenerativeModel("gemini-2.0-flash-image")
        response = model.generate_content(
            f"Ilustración educativa 512x512 px sin texto ni marcas. Tema: {prompt}"
        )

        image_data = None
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                image_data = part.inline_data.data
                break

        if not image_data:
            raise ValueError("La respuesta no contiene imagen válida.")

        img = Image.open(tempfile.SpooledTemporaryFile())
        img = Image.open(tempfile.SpooledTemporaryFile())
        img = Image.open(BytesIO(image_data))
        img.save(cache_file, "PNG")
        print(f"✅ Imagen guardada: {cache_file}")
        time.sleep(2)
        return cache_file

    except Exception as e:
        print(f"🚨 ERROR al generar imagen con Gemini: {e}")
        raise


# --- CLASE PDF ---

class RetoPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(20, 20, 20)
        self.set_auto_page_break(auto=True, margin=18)
        self._font_family = "DejaVu"
        self._init_fonts()

    def _init_fonts(self):
        base_dir = "/usr/share/fonts/truetype/dejavu"
        try:
            self.add_font("DejaVu", "", os.path.join(base_dir, "DejaVuSans.ttf"))
            self.add_font("DejaVu", "B", os.path.join(base_dir, "DejaVuSans-Bold.ttf"))
            print("✅ Fuente DejaVu cargada.")
        except Exception as e:
            print(f"[AVISO] No se pudo cargar fuente DejaVu: {e}")

    def header(self):
        pass

    def footer(self):
        self.set_y(-15)
        self.set_font(self._font_family, "", 10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Página {self.page_no()}", align="C")

    def titulo(self, text: str):
        self.set_font(self._font_family, "B", 22)
        self.set_text_color(0, 102, 204)
        self.cell(0, 15, text, align="C", new_y=YPos.NEXT)
        self.ln(8)
        self.set_text_color(0, 0, 0)
        self.set_font(self._font_family, "", 12)

    def flow_text_with_image(self, text: str, img_path: str, side: str):
        img_w_mm = 70
        gutter = 8
        line_h = 6
        page_w = self.w - self.l_margin - self.r_margin
        text_w = page_w - img_w_mm - gutter

        y_before = self.get_y()
        img = Image.open(img_path)
        iw, ih = img.size
        img_h_mm = img_w_mm * ih / iw

        if self.get_y() + img_h_mm > self.page_break_trigger:
            self.add_page()
            y_before = self.get_y()

        x_img = self.l_margin if side == "left" else self.w - self.r_margin - img_w_mm
        self.image(img_path, x=x_img, y=y_before, w=img_w_mm)

        x_text = self.l_margin if side == "right" else self.l_margin + img_w_mm + gutter
        self.set_xy(x_text, y_before)
        self.multi_cell(text_w, line_h, clean_inline_md(text), align="J")

        self.set_y(max(y_before + img_h_mm, self.get_y()) + 8)


# --- GENERACIÓN DEL PDF ---

def generar_pdf_optimizado(md_path: str, input_folder: str, output_folder: str, cache_folder: str):
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    blocks, title = parse_markdown(text)
    pdf = RetoPDF()
    pdf.add_page()
    pdf.titulo(title)

    reto_idx = 0
    side = "right"
    current_text = ""
    for idx, b in enumerate(blocks):
        if b.type == "h2" and "reto" in b.text.lower():
            if current_text:
                img_path = generate_image_with_gemini(
                    b.text, cache_folder, f"reto{reto_idx}"
                )
                pdf.flow_text_with_image(current_text, img_path, side)
                reto_idx += 1
                side = "left" if side == "right" else "right"
                current_text = ""
        elif b.type == "p":
            current_text += b.text + "\n"

    # último bloque
    if current_text:
        img_path = generate_image_with_gemini(
            f"Reto final de {title}", cache_folder, f"reto{reto_idx}"
        )
        pdf.flow_text_with_image(current_text, img_path, side)

    os.makedirs(output_folder, exist_ok=True)
    output_pdf = os.path.join(output_folder, os.path.basename(md_path).replace(".md", ".pdf"))
    pdf.output(output_pdf)
    print(f"✅ PDF generado: {output_pdf}")


# --- MAIN ---

def main():
    import argparse
    parser = argparse.ArgumentParser()
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
        output_pdf = os.path.join(
            args.output_folder, os.path.basename(md).replace(".md", ".pdf")
        )
        if os.path.exists(output_pdf):
            print(f"⏭️  PDF ya existe, se omite: {output_pdf}")
            continue
        print(f"--- Procesando: {md} ---")
        try:
            generar_pdf_optimizado(md, args.input_folder, args.output_folder, args.images_cache)
        except Exception as e:
            print(f"❌ Error procesando {md}: {e}")
            continue


if __name__ == "__main__":
    main()
