#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import google.generativeai as genai
from PIL import Image
from io import BytesIO
import pathlib

# --- CONFIGURACIÓN DE LA API DE GOOGLE ---
# Basado en la configuración final que confirmamos que funciona.
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    print("🚨 ERROR FATAL: No se encontró la variable de entorno GOOGLE_API_KEY.")
    print("   Asegúrate de que tu archivo .github/workflows/main.yml contiene el bloque 'env:' para pasar el secret.")
    sys.exit(1)

try:
    genai.configure(api_key=GOOGLE_API_KEY)
    print("✅ Cliente de Google AI configurado correctamente.")
except Exception as e:
    print(f"🚨 ERROR: La clave de API parece ser inválida. Error de Google: {e}")
    sys.exit(1)


# --- FUNCIÓN PARA GENERAR IMÁGENES (BASADA EN TU EJEMPLO) ---

def generate_image_with_gemini(prompt: str, out_dir: str) -> str:
    """
    Genera una imagen usando la API de Gemini y devuelve la ruta al archivo guardado.
    """
    print(f"🎨 Enviando prompt a Gemini: '{prompt[:90]}...'")
    
    try:
        # --- INICIO DE LA LÓGICA CORRECTA (GRACIAS A TU EJEMPLO) ---

        # 1. Usamos un modelo específico para imágenes, como en tu ejemplo.
        #    'gemini-1.5-flash' es una opción robusta y rápida.
        model = genai.GenerativeModel('gemini-2.5-flash-image')
        
        # 2. Creamos un prompt detallado para guiar al modelo.
        full_prompt = f"Genera una ilustración digital de alta calidad para un libro educativo de matemáticas para adolescentes. La escena debe representar claramente: {prompt}. El estilo debe ser limpio, con colores vivos y atractivos. Es crucial que no contenga ningún tipo de texto, letras, firmas ni marcas de agua."

        # 3. Hacemos la llamada a `generate_content`.
        response = model.generate_content(full_prompt)

        # 4. Procesamos la respuesta de forma segura, como en tu ejemplo.
        #    Buscamos la parte que contiene los datos de la imagen.
        image_data = None
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_data = part.inline_data.data
                break
        
        if not image_data:
            # Si no se encuentra una imagen, es un error.
            error_text = response.text or "La respuesta de la API no contenía una imagen."
            raise ValueError(f"No se pudo generar la imagen. Respuesta: {error_text}")

        image = Image.open(BytesIO(image_data))
        
        # --- FIN DE LA LÓGICA CORRECTA ---
        
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
        out_path = str(pathlib.Path(out_dir, f"img_{os.urandom(8).hex()}.png"))
        
        image.convert("RGB").save(out_path, "PNG")
        print(f"🖼️ Imagen guardada en: {out_path}")
        return out_path

    except Exception as e:
        print(f"🚨 ERROR al generar imagen con Gemini. Error: {e}")
        raise ConnectionError(f"Fallo en la API de Gemini: {e}")
