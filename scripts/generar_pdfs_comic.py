#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para generar PDFs educativos a partir de archivos Markdown (.md)
con formato limpio, colores, portada y recuadros de ilustración opcionales.

Autor: versión educativa mejorada por ChatGPT
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
HEADING_RE = re.compile(r'^\s*(#{1,6})\s+(.*)\s*$')
PROMPT_RE = re.compile(r'^\s*!\[prompt\]\s*(.*)\s*$', re.IGNORECASE)

# --- Datos estructurados ---
@dataclass
class Block:
    type: str
    text: str

# --- Función para limpiar texto inline Markdown ---
def clean_inline_md(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'\s*\n\s*', ' ', s)
    return re.sub(r'\s{2,}', ' ', s).strip()

# --- Función para parsear el Markdown ---
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

class EduPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(20, 20, 20)
        self.set_auto_page_break(auto=True, margin=15)

        # ✅ Fuente Unicode
        try:
            # usa DejaVuSans si está disponible en el sistema
            self.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", uni=True)
            self.add_font("DejaVu", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", uni=True)
            self.set_font("DejaVu", size=12)
            self._font_family = "DejaVu"
        except Exception:
            # fallback a Helvetica si no existe (sin acentos)
            self.set_font("Helvetica", size=12)
            self._font_family = "Helvetica"

    def header(self):
        if self.page_no() == 1:
            return  # sin encabezado en la portada
        self.set_font(self._font_family, "B", 10)
        self.set_text_color(0, 102, 204)
        self.cell(0, 10, self.title, align="C", new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-15)
        self.set_font(self._font_family, "", 10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Página {self.page_no()}", align="C")

    # --- Portada segura con Unicode ---
    def portada(self, titulo: str):
        self.add_page()
        titulo = str(titulo or "Documento educativo").strip()
        self.set_font(self._font_family, "B", 24)
        self.set_text_color(0, 102, 204)
        self.cell(0, 80, "", new_y=YPos.NEXT)

        # ✅ dividir el título en líneas seguras y forzar salto
        palabras = titulo.replace("\n", " ").split()
        linea = ""
        for palabra in palabras:
            if len(linea + " " + palabra) > 40:
                self.multi_cell(0, 12, linea.strip(), align="C")
                linea = palabra
            else:
                linea += " " + palabra
        if linea:
            self.multi_cell(0, 12, linea.strip(), align="C")

        self.set_text_color(0, 0, 0)
        self.ln(10)
        self.set_font(self._font_family, "", 14)
        self.multi_cell(0, 10, "Material educativo generado automáticamente", align="C")
        self.ln(20)
        self.set_font(self._font_family, "I", 12)
        self.multi_cell(0, 8, "Proyecto de aprendizaje por retos", align="C")
        self.add_page()

    def add_heading(self, text: str, level: int):
        colors = {2: (255, 140, 0), 3: (0, 102, 204), 4: (0, 150, 100)}
        color = colors.get(level, (0, 0, 0))
        self.set_text_color(*color)
        self.set_font(self._font_family, "B", 22 - 2 * level)
        self.multi_cell(0, 10, clean_inline_md(text))
        self.ln(2)
        self.set_font(self._font_family, "", 12)
        self.set_text_color(0, 0, 0)

    def add_paragraph(self, text: str):
        self.set_font(self._font_family, "", 12)
        self.multi_cell(0, 7, clean_inline_md(text), align="J")
        self.ln(4)

    def add_prompt_box(self, description: str):
        self.set_fill_color(240, 240, 240)
        self.set_draw_color(200, 200, 200)
        self.set_font(self._font_family, "I", 10)
        self.multi_cell(0, 7,
                        f"💡 Ilustración sugerida:\n{clean_inline_md(description)}",
                        align="C", fill=True)
        self.ln(6)
        self.set_font(self._font_family, "", 12)


    # --- Portada ---
    def portada(self, titulo: str):
        self.add_page()
        titulo = str(titulo).strip()
        if not titulo:
            titulo = "Documento educativo"

        # Configuración visual
        self.set_font("Helvetica", "B", 24)
        self.set_text_color(0, 102, 204)
        self.cell(0, 80, "", new_y=YPos.NEXT)

        # Controlar que el texto no desborde el ancho
        try:
            self.multi_cell(0, 15, titulo, align="C")
        except Exception:
            # Si el texto es muy largo, reducir tamaño y dividir
            self.set_font("Helvetica", "B", 18)
            partes = [titulo[i:i+60] for i in range(0, len(titulo), 60)]
            for parte in partes:
                self.multi_cell(0, 12, parte, align="C")

        # Subtítulo y créditos
        self.set_text_color(0, 0, 0)
        self.ln(10)
        self.set_font("Helvetica", "", 14)
        self.multi_cell(0, 10, "Material educativo generado automáticamente", align="C")
        self.ln(20)
        self.set_font("Helvetica", "I", 12)
        self.multi_cell(0, 8, "Proyecto de aprendizaje por retos", align="C")
        self.add_page()


    # --- Bloques de texto ---
    def add_heading(self, text: str, level: int):
        colors = {2: (255, 140, 0), 3: (0, 102, 204), 4: (0, 150, 100)}
        color = colors.get(level, (0, 0, 0))
        self.set_text_color(*color)
        self.set_font("Helvetica", "B", 22 - 2 * level)
        self.multi_cell(0, 10, clean_inline_md(text))
        self.ln(2)
        self.set_font("Helvetica", "", 12)
        self.set_text_color(0, 0, 0)

    def add_paragraph(self, text: str):
        self.set_font("Helvetica", "", 12)
        self.multi_cell(0, 7, clean_inline_md(text), align="J")
        self.ln(4)

    # --- Bloques de ilustración (sin imágenes IA) ---
    def add_prompt_box(self, description: str):
        self.set_fill_color(240, 240, 240)
        self.set_draw_color(200, 200, 200)
        self.set_font("Helvetica", "I", 10)
        self.multi_cell(0, 7, f"💡 Ilustración sugerida:\n{clean_inline_md(description)}",
                        align="C", fill=True)
        self.ln(6)
        self.set_font("Helvetica", "", 12)

# --- Función principal de generación ---
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

# --- Main ---
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
