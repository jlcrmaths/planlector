#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import google.generativeai as genai
from PIL import Image
import io
import pathlib

# --- CONFIGURACIÓN DE LA API DE GEMINI (SIMPLE Y DIRECTA) ---

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    print("🚨 ERROR FATAL: No se encontró la variable de entorno GOOGLE_API_KEY en el entorno de ejecución.")
    print("   Por favor, asegúrate de que tu archivo .github/workflows/main.yml contiene el bloque 'env:' para pasar el secret.")
    sys.exit(1)

try:
    genai.configure(api_key=GOOGLE_API_KEY)
    print("✅ Cliente de Gemini configurado correctamente con la clave proporcionada.")
except Exception as e:
    print(f"🚨 ERROR: La clave de API parece ser inválida. Error de Google: {e}")
    sys.exit(1)


# --- FUNCIÓN PARA GENERAR IMÁGENES ---

def generate_image_with_gemini(prompt: str, out_dir: str) -> str:
    """
    Genera una imagen usando la API de Gemini y devuelve la ruta al archivo guardado.
    """
    print(f"🎨 Enviando prompt a Gemini: '{prompt[:90]}...'")
    
    try:
        # --- INICIO DE LA CORRECCIÓN FINAL ---
        # Usamos 'gemini-pro-vision', el modelo multimodal estándar y estable
        # diseñado para entender y generar contenido a partir de texto e imágenes.
        model = genai.GenerativeModel('gemini-pro-vision')
        # --- FIN DE LA CORRECCIÓN FINAL ---
        
        full_prompt = f"Genera una ilustración digital para un libro educativo de matemáticas para adolescentes. La escena debe representar: {prompt}. Estilo claro, colores vivos, sin texto, firmas ni marcas de agua."
        
        response = model.generate_content(
            full_prompt,
            generation_config={"candidate_count": 1}
        )
        
        image_data = response.parts[0].inline_data.data
        image = Image.open(io.BytesIO(image_data))
        
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
        out_path = str(pathlib.Path(out_dir, f"img_{os.urandom(8).hex()}.png"))
        
        image.convert("RGB").save(out_path, "PNG")
        print(f"🖼️ Imagen guardada en: {out_path}")
        return out_path

    except Exception as e:
        print(f"🚨 ERROR al generar imagen con Gemini. Respuesta de la API: {getattr(e, 'response', e)}")
        raise ConnectionError(f"Fallo en la API de Gemini: {e}")
