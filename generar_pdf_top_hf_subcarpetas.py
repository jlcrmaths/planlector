import os
from markdown2 import markdown
from fpdf import FPDF
from PIL import Image
from diffusers import StableDiffusionPipeline
import torch

# -----------------------------
# Token seguro de Hugging Face
# -----------------------------
hf_token = os.getenv("HF_TOKEN")
if not hf_token:
    raise ValueError("❌ No se encontró el HF_TOKEN. Configura el secret en GitHub.")

# -----------------------------
# Carpeta principal
# -----------------------------
folder = "historias"
output_folder = "pdfs_generados"
md_files = []

# Recorre subcarpetas recursivamente
for root, dirs, files in os.walk(folder):
    for file in files:
        if file.endswith(".md"):
            md_files.append(os.path.join(root, file))

print(f"📄 Archivos Markdown encontrados: {len(md_files)}")

# -----------------------------
# Configurar Stable Diffusion
# -----------------------------
pipe = StableDiffusionPipeline.from_pretrained(
    "CompVis/stable-diffusion-v1-4",
    use_auth_token=hf_token,
    torch_dtype=torch.float16
).to("cuda")  # Cambiar a "cpu" si no hay GPU

# -----------------------------
# Función para procesar un Markdown
# -----------------------------
def procesar_md(md_path):
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.splitlines()
    title = os.path.splitext(os.path.basename(md_path))[0]
    subtitles = [line[3:].strip() for line in lines if line.startswith("## ")]
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Portada
    portada_prompt = f"Portada de libro tipo cómic, estilo ilustración colorida, título: {title}"
    portada_image = pipe(portada_prompt).images[0]
    portada_image_path = "temp_portada.png"
    portada_image.save(portada_image_path)

    # Imágenes párrafos
    images = []
    for para in paragraphs[:3]:
        prompt = f"Ilustración tipo cómic, colores vivos, estilo cómic, escena: {para}"
        image = pipe(prompt).images[0]
        images.append({"paragraph": para, "image": image})

    # Crear PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.image(portada_image_path, w=180)
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 24)
    pdf.set_text_color(30, 30, 120)
    pdf.multi_cell(0, 12, title, align='C')
    pdf.ln(10)

    pdf.set_font("Arial", '', 12)
    pdf.set_text_color(0, 0, 0)

    for para in paragraphs:
        for sub in subtitles:
            if sub in para:
                pdf.set_font("Arial", 'B', 16)
                pdf.set_text_color(200, 30, 30)
                pdf.multi_cell(0, 10, sub)
                pdf.ln(3)
                pdf.set_font("Arial", '', 12)
                pdf.set_text_color(0, 0, 0)
        for img in images:
            if img["paragraph"] == para:
                img_path = "temp.png"
                img["image"].save(img_path)
                pdf.image(img_path, w=150)
                pdf.ln(5)
        pdf.multi_cell(0, 7, para)
        pdf.ln(5)

    activity_index = text.find("## Actividades")
    if activity_index != -1:
        pdf.add_page()
        pdf.set_font("Arial", 'B', 18)
        pdf.set_text_color(30, 100, 30)
        pdf.multi_cell(0, 10, "Actividades", align='C')
        pdf.ln(10)
        pdf.set_font("Arial", '', 12)
        pdf.set_text_color(0, 0, 0)
        activities_text = text[activity_index:].split("\n")
        for act in activities_text[1:]:
            if act.strip():
                pdf.multi_cell(0, 7, act.strip())
                pdf.ln(3)

    # Crear carpeta de salida replicando estructura
    rel_path = os.path.relpath(os.path.dirname(md_path), folder)
    pdf_folder = os.path.join(output_folder, rel_path)
    os.makedirs(pdf_folder, exist_ok=True)

    # Guardar PDF con el mismo nombre que el Markdown
    output_pdf = os.path.join(pdf_folder, os.path.basename(md_path).replace(".md", ".pdf"))
    pdf.output(output_pdf)
    print(f"✅ PDF generado: {output_pdf}")

# -----------------------------
# Procesar todos los Markdown
# -----------------------------
for md in md_files:
    procesar_md(md)
