#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import sys
import time
import pathlib
from io import BytesIO
from PIL import Image
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import google.generativeai as genai


# --- CONFIGURACIÓN DE GOOGLE GEMINI ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    print("🚨 ERROR FATAL: No se encontró la variable de entorno GOOGLE_API_KEY.")
    sys.exit(1)

try:
    genai.configure(api_key=GOOGLE_API_KEY)
    print("✅ Cliente de Google AI configurado correctamente.")
except Exception as e:
    print(f"🚨 ERROR: La clave de API parece ser inválida. Detalles: {e}")
    sys.exit(1)


# --- FUNCIÓN DE GENERACIÓN DE IMÁGENES ---
def generate_image_with_gemini(prompt: str, out_dir: str) -> str:
    """Genera imagen educativa con Gemini."""
    print(f"🎨 Enviando prompt a Gemini: '{prompt[:80]}...'")
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-preview-image')
        full_prompt = (
            f"Genera una ilustración digital educativa y colorida sobre: {prompt}. "
            "Debe ser apropiada para adolescentes, con estilo limpio y sin texto ni marcas de agua."
        )
        response = model.generate_content(full_prompt)

        image_data = None
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_data = part.inline_data.data
                break

        if not image_data:
            raise ValueError("La respuesta no contenía una imagen válida.")

        image = Image.open(BytesIO(image_data))
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
        out_path = str(pathlib.Path(out_dir, f"img_{os.urandom(8).hex()}.png"))
        image.convert("RGB").save(out_path, "PNG")
        print(f"🖼️ Imagen guardada en: {out_path}")
        return out_path
    except Exception as e:
        print(f"🚨 ERROR al generar imagen con Gemini. Error: {e}")
        raise


# --- LIMPIADOR DE TEXTO ---
def clean_inline_md(s: str) -> str:
    """Quita formato MD y separa apartados a), b), c)."""
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'\s*\n\s*', ' ', s)
    s = re.sub(r'([a-zA-Z]\))', r'\1\n', s)
    return re.sub(r'\s{2,}', ' ', s).strip()


# --- CLASE PDF CON MAQUETACIÓN MEJORADA ---
class EducativoPDF(FPDF):
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
            print(f"[AVISO] No se pudo cargar DejaVu: {e}")

    def footer(self):
        self.set_y(-15)
        self.set_font(self._font_family, "", 10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Página {self.page_no()}", align="C")

    def titulo(self, text: str):
        self.set_font(self._font_family, "B", 22)
        self.set_text_color(0, 102, 204)
        self.multi_cell(0, 15, text, align="C")
        self.ln(10)
        self.set_text_color(0, 0, 0)
        self.set_font(self._font_family, "", 12)

    def flow_text_with_image(self, text: str, img_path: str, side: str):
        """Coloca imagen a un lado y adapta el texto."""
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

        # Ajustar salto tras la imagen
        self.set_y(max(y_before + img_h_mm, self.get_y()) + 6)


# --- GENERADOR PRINCIPAL ---
def generar_pdf_educativo(titulo: str, secciones: list, salida_pdf: str):
    pdf = EducativoPDF()
    pdf.add_page()
    pdf.titulo(titulo)

    side = "right"
    for idx, (texto, prompt) in enumerate(secciones):
        try:
            img_path = generate_image_with_gemini(prompt, "imagenes_cache")
            pdf.flow_text_with_image(texto, img_path, side)
            side = "left" if side == "right" else "right"
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ No se pudo generar la imagen para '{prompt}': {e}")
            pdf.multi_cell(0, 6, clean_inline_md(texto), align="J")
            pdf.ln(6)

    pdf.output(salida_pdf)
    print(f"✅ PDF generado: {salida_pdf}")


# --- EJEMPLO DE USO ---
if __name__ == "__main__":
    titulo = "Lectura 1: El origen de los números"
    secciones = [
        ("Reto 1: Investiga cómo las antiguas civilizaciones representaban los números.", "Reto 1: escritura numérica antigua, civilizaciones, piedra y símbolos"),
        ("Reto 2: Explica por qué el cero fue un avance tan importante.", "Reto 2: símbolo del cero, matemáticas antiguas, representación visual educativa"),
        ("Reto 3: Piensa cómo serían las matemáticas si no existiera el cero.", "Reto 3: educación matemática, ilustración conceptual sobre ausencia del cero"),
        ("Reto 4: Crea un breve cómic sobre cómo nacieron los números.", "Reto 4: historieta educativa sobre el origen de los números"),
    ]
    generar_pdf_educativo(titulo, secciones, "pdfs_generados/1_reto_matematico.pdf")
