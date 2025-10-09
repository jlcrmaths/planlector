#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import google.generativeai as genai
from PIL import Image
import io
import pathlib

# --- CONFIGURACIÓN DE LA API DE GEMINI ---
try:
    # Intenta obtener la clave desde los secrets de GitHub Actions
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    if not GOOGLE_API_KEY:
        # Fallback para pruebas locales (si tienes un archivo .env)
        from dotenv import load_dotenv
        load_dotenv()
        GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

    genai.configure(api_key=GOOGLE_API_KEY)
    print("✅ Cliente de Gemini configurado correctamente.")
except Exception as e:
    print(f"🚨 ERROR: No se pudo configurar la API de Gemini. Asegúrate de que el secret GOOGLE_API_KEY está configurado en GitHub. Error: {e}")
    genai = None

# --- FUNCIÓN PARA GENERAR IMÁGENES ---
def generate_image_with_gemini(prompt: str, out_dir: str) -> str:
    """
    Genera una imagen usando la API de Gemini (Nano Banana) y la guarda en un archivo.
    Devuelve la ruta al archivo de imagen guardado.
    """
    if not genai:
        raise ConnectionError("El cliente de Gemini no está configurado.")

    print(f"🎨 Enviando prompt a Gemini: '{prompt[:90]}...'")
    
    # Elige el modelo "Nano Banana"
    # Usamos un nombre de modelo estable. Revisa la documentación si cambia.
    model = genai.GenerativeModel('models/gemini-1.5-flash-latest') # Modelo actualizado y robusto
    
    # Llama a la API. Gemini prefiere prompts más descriptivos.
    # Añadimos un prefijo para guiar mejor al modelo.
    full_prompt = f"Genera una ilustración digital para un libro educativo con el siguiente concepto: {prompt}. Estilo claro, colores vivos, sin texto ni firmas."
    
    try:
        response = model.generate_content(
            full_prompt,
            generation_config={"candidate_count": 1}
        )
        
        # Extrae los datos de la imagen de la respuesta
        # La API devuelve los datos binarios de la imagen directamente
        image_data = response.parts[0].inline_data.data
        
        # Crea un objeto de imagen PIL a partir de los datos
        image = Image.open(io.BytesIO(image_data))
        
        # Guarda la imagen en un archivo temporal para devolver la ruta
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
        # Usamos un nombre aleatorio para evitar colisiones
        out_path = str(pathlib.Path(out_dir, f"img_{os.urandom(8).hex()}.png"))
        
        image.convert("RGB").save(out_path, "PNG")
        print(f"🖼️ Imagen guardada en: {out_path}")
        return out_path

    except Exception as e:
        print(f"🚨 ERROR al generar imagen con Gemini: {e}")
        # Lanza una excepción para que el script principal sepa que ha fallado
        raise ConnectionError(f"Fallo en la API de Gemini: {e}")
