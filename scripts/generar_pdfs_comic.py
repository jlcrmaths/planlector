#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera PDFs educativos desde Markdown.
Versión robusta: detección de fuentes (regular/bold/italic),
fallback seguro y portada que no rompe por títulos largos/caracteres.
"""
import os
import re
import sys
import argparse
from dataclasses import dataclass
from typing import List, Optional, Tuple
from pathlib import Path
from fpdf import FPDF
from fpdf.enums import XPos, YPos

# --- Expresiones regulares ---
HEADING_RE = re.compile(r'^\s*(\#{1,6})\s+(.*)\s*$')
PROMPT_RE  = re.compile(r'^\s*!\[prompt\]\s*(.*)\s*$', re.IGNORECASE)

@dataclass
class Block:
    type: str
    text: str

def clean_inline_md(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'\_\_(.+?)\_\_', r'\1', s)
    s = re.sub(r'\s*\n\s*', ' ', s)
    return re.sub(r'\s{2,}', ' ', s).strip()

def parse_markdown(text: str) -> Tuple[List[Block], str]:
    lines = text.splitlines()
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
        m_prompt = PROMPT_RE.match(line)
        if m_prompt:
            flush_para()
            prompt_text = (m_prompt.group(1) or "").strip()
            if prompt_text:
                blocks.append(Block('img', prompt_text))
            continue

        m_heading = HEADING_RE.match(line)
        if m_heading:
            flush_para()
            level = len(m_heading.group(1))
            heading_text = m_heading.group(2).strip()
            if level == 1 and not title_h1:
                title_h1 = heading_text
            blocks.append(Block(f'h{level}', heading_text))
            continue

        if not line.strip():
            flush_para()
        else:
            current_para.append(line)

    flush_para()
    return blocks, (title_h1 or "Documento educativo")

# --- Clase EduPDF robusta ---
class EduPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(20, 20, 20)
        self.set_auto_page_break(auto=True, margin=15)
        # Estarán registradas las variantes que encontremos: '', 'B', 'I'
        self._available_styles = set()
        self._font_family = "Helvetica"
        # Rutas donde buscar fuentes (incluye una carpeta 'fonts' del proyecto)
        font_dirs = []
        if os.getenv("FONT_PATH"):
            font_dirs.append(os.getenv("FONT_PATH"))
        font_dirs += [
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts/truetype",
            str(Path(__file__).resolve().parent / "fonts"),
        ]
        # Intentar registrar DejaVu (regular/bold/italic)
        registered = False
        for base in font_dirs:
            reg    = os.path.join(base, "DejaVuSans.ttf")
            bold   = os.path.join(base, "DejaVuSans-Bold.ttf")
            italic = os.path.join(base, "DejaVuSans-Oblique.ttf")
            try:
                if os.path.isfile(reg):
                    # registrar la familia DejaVu con las variantes que existan
                    try:
                        self.add_font("DejaVu", "", reg)
                        self._available_styles.add('')
                    except Exception:
                        pass
                    if os.path.isfile(bold):
                        try:
                            self.add_font("DejaVu", "B", bold)
                            self._available_styles.add('B')
                        except Exception:
                            pass
                    if os.path.isfile(italic):
                        try:
                            self.add_font("DejaVu", "I", italic)
                            self._available_styles.add('I')
                        except Exception:
                            pass
                    self._font_family = "DejaVu"
                    registered = True
                    break
            except Exception:
                continue
        # Si no registramos DejaVu, usamos la fuente integrada (Helvetica)
        if not registered:
            # built-in fonts: Helvetica está disponible sin add_font
            self._font_family = "Helvetica"
            # asumimos '' y 'B' disponibles; 'I' puede que no. Protegemos vía _set_font.
            self._available_styles = {'', 'B'}
        # establecer fuente por defecto a un tamaño razonable
        # usamos super().set_font para evitar la comprobación en _set_font que aún no existe
        super().set_font(self._font_family, '', 12)

    def _set_font(self, style: str = '', size: int = 12):
        """Establece la fuente usando una variante disponible; si la solicitada
        no existe, aplica un fallback seguro."""
        style = (style or '')
        if style not in self._available_styles:
            # preferimos regular, luego bold, luego lo que haya
            if '' in self._available_styles:
                style_to_use = ''
            elif 'B' in self._available_styles:
                style_to_use = 'B'
            else:
                # si no hay nada registrado, usar '' (built-in)
                style_to_use = ''
        else:
            style_to_use = style
        super().set_font(self._font_family, style_to_use, size)

    # Encabezado y pie (usamos _set_font para proteger estilos)
    def header(self):
        if self.page_no() == 1:
            return
        self._set_font('B', 10)
        self.set_text_color(0, 102, 204)
        # titulado centrado en el header
        # usamos cell() porque es robusto
        self.cell(0, 10, getattr(self, "title", ""), align="C", new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-15)
        self._set_font('', 10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Página {self.page_no()}", align="C")

    # --- Portada robusta (sin multi_cell problemático) ---
    def portada(self, titulo: str):
        self.add_page()
        titulo = str(titulo or "Documento educativo").strip()
        if not titulo:
            titulo = "Documento educativo"
        self._set_font('B', 26)
        self.set_text_color(0, 102, 204)
        # espacio superior
        self.ln(70)
        # dividir por palabras en líneas de longitud controlada (por carácter)
        max_chars = 40
        palabras = titulo.replace("\n", " ").split()
        linea = ""
        lineas = []
        for palabra in palabras:
            if len((linea + " " + palabra).strip()) > max_chars:
                if linea:
                    lineas.append(linea.strip())
                linea = palabra
            else:
                linea = (linea + " " + palabra).strip()
        if linea:
            lineas.append(linea.strip())
        for l in lineas:
            # cell() no falla por "no espacio horizontal"
            self.cell(0, 15, l, align="C", new_y=YPos.NEXT)
        # subtítulo
        self.set_text_color(0, 0, 0)
        self.ln(10)
        self._set_font('', 14)
        self.cell(0, 10, "Material educativo generado automáticamente", align="C", new_y=YPos.NEXT)
        self.ln(5)
        # usar italic si está disponible, si no, caerá a regular/ó bold según _set_font
        self._set_font('I', 12)
        self.cell(0, 10, "Proyecto de aprendizaje por retos", align="C", new_y=YPos.NEXT)
        # nueva página para contenido
        self.add_page()

    # --- Helpers de ancho/posicionamiento seguro ---
    def effective_page_width(self):
        return self.w - self.l_margin - self.r_margin

    def reset_x(self):
        self.set_x(self.l_margin)

    def _make_breakable(self, s: str, every: int = 30) -> str:
        # Inserta U+200B tras cada "every" caracteres no blancos consecutivos para permitir saltos
        return re.sub(r'(\S{' + str(every) + r'})(?=\S)', r'\1\u200b', s)

    def _safe_multicell(self, h: float, txt: str, **kwargs):
        # Recoloca X al margen izquierdo y usa el ancho efectivo
        self.reset_x()
        w = self.effective_page_width()
        # Permite corte en tokens muy largos
        if txt:
            txt = self._make_breakable(txt, every=30)
        self.multi_cell(w, h, txt, **kwargs)

    def add_heading(self, text: str, level: int):
        colors = {2: (255, 140, 0), 3: (0, 102, 204), 4: (0, 150, 100)}
        color = colors.get(level, (0, 0, 0))
        self.set_text_color(*color)
        # tamaño según nivel (protección con _set_font)
        size = max(10, 22 - 2 * level)
        self._set_font('B', size)
        txt = clean_inline_md(text)
        self._safe_multicell(10, txt)
        self.ln(2)
        self._set_font('', 12)
        self.set_text_color(0, 0, 0)

    def add_paragraph(self, text: str):
        self._set_font('', 12)
        txt = clean_inline_md(text)
        self._safe_multicell(7, txt, align="J")
        self.ln(4)

    def add_prompt_box(self, description: str):
        self.set_fill_color(240, 240, 240)
        self.set_draw_color(200, 200, 200)
        # intentar italic, pero si no está, _set_font hará fallback
        self._set_font('I', 10)
        box_text = f"💡 Ilustración sugerida:\n{clean_inline_md(description)}"
        self._safe_multicell(7, box_text, align="C", fill=True)
        self.ln(6)
        self._set_font('', 12)


def generar_pdf_educativo(md_path: str, input_folder: str, output_folder: str):
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()
    blocks, title = parse_markdown(text)
    pdf = EduPDF()
    pdf.title = title
    pdf.portada(title)

    for b in blocks:
        if b.type.startswith("h"):
            pdf.add_heading(b.text, int(b.type[1]))
        elif b.type == "p":
            pdf.add_paragraph(b.text)
        elif b.type == "img":
            pdf.add_prompt_box(b.text)

    rel_path = os.path.relpath(os.path.dirname(md_path), input_folder)
    pdf_folder = os.path.join(output_folder, rel_path)
    os.makedirs(pdf_folder, exist_ok=True)
    output_pdf = os.path.join(pdf_folder, os.path.basename(md_path).replace(".md", ".pdf"))
    pdf.output(output_pdf)
    print(f"✅ PDF educativo generado: {output_pdf}")


def main():
    parser = argparse.ArgumentParser(description="Genera PDFs educativos desde archivos Markdown.")
    parser.add_argument("--input-folder", default="historias")
    parser.add_argument("--output-folder", default="pdfs_generados")
    args = parser.parse_args()

    md_files = [os.path.join(root, f)
                for root, _, files in os.walk(args.input_folder)
                for f in files if f.lower().endswith(".md")]

    print(f"📄 Archivos Markdown detectados: {len(md_files)}")
    for md in sorted(md_files):
        print(f"--- Procesando: {md} ---")
        generar_pdf_educativo(md, args.input_folder, args.output_folder)


if __name__ == "__main__":
    main()




