#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador avanzado de prompts para AI Horde / Stable Diffusion.
Convierte cualquier texto en un prompt visual coherente, estilo ilustración, listo para generar imágenes.
"""

import re
from collections import Counter
from typing import List, Tuple

# ----------------------------------------
# Configuración de palabras no útiles
# ----------------------------------------
ABSTRACT_STOP = {
    "idea","concepto","teoría","historia","cultura","sistema","proceso","método",
    "información","cantidad","tiempo","serie","conjunto","uso","necesidad",
    "tecnología","herramienta","algoritmo","invención","origen","números",
    "matemáticas","clase","práctica","registro"
}

STOPWORDS = {
    "el","la","los","las","un","una","unos","unas","de","del","en","por","para",
    "a","y","o","que","se","con","su","sus","al","como","es","son","lo","más"
}

NEGATIVE_CUES = [
    "text","letters","words","signature","watermark","UI","interface","screenshot",
    "speech bubble","subtitle","logo","blurry","deformed","cropped","ugly","bad anatomy"
]

# ----------------------------------------
# Funciones internas
# ----------------------------------------
def _clean_text(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def _top_items(seq: List[str], k: int) -> List[str]:
    return [w for w,_ in Counter(seq).most_common(k)]

def _dedup(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in seq:
        if x not in seen and x.strip():
            seen.add(x)
            out.append(x)
    return out

# ----------------------------------------
# Heurística avanzada de tokens
# ----------------------------------------
def _tokens_heuristic(text: str) -> Tuple[List[str], List[str], List[str], List[str]]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\-']{3,}", text)
    words_lower = [w.lower() for w in words if w.lower() not in STOPWORDS]
    verbs = [w for w in words_lower if w.endswith(("ar","er","ir","ando","iendo","ado","ido"))]
    nouns = [w for w in words_lower if w not in verbs and w not in ABSTRACT_STOP]
    # heurística de lugares
    places = [w for w in nouns if w.endswith(("ia","cio","cia","polis","desa","landia"))]
    return (
        _top_items(_dedup(nouns), 6),    # subjects
        _top_items(_dedup(verbs), 3),    # verbs
        _top_items(_dedup(nouns), 8),    # objects
        _top_items(_dedup(places), 3)    # places
    )

# ----------------------------------------
# Función principal de generación de prompt
# ----------------------------------------
def build_ultimate_prompt(text: str, doc_title: str = "") -> str:
    raw = _clean_text(f"{doc_title}. {text}") if doc_title else _clean_text(text)
    subjects, verbs, objects_, places = _tokens_heuristic(raw)

    if not subjects and not objects_: objects_ = ["main concept"]
    if not verbs: verbs = ["illustrating"]

    # Componer escena principal
    scene_elements = _dedup(subjects + objects_ + places)
    scene = ", ".join(scene_elements[:10])
    action = verbs[0]

    # Añadimos detalles visuales para máxima calidad
    prompt_positive = (
        f"illustration, highly detailed, concept art, cinematic lighting, bright colors, "
        f"{action}, {scene}, child-friendly, clean composition, professional artstation style, "
        f"soft shadows, realistic proportions, high quality, 4k"
    )
    prompt_negative = ", ".join(NEGATIVE_CUES)

    return f"({prompt_positive}) --neg ({prompt_negative})"

# ----------------------------------------
# Ejemplo de uso
# ----------------------------------------
if __name__ == "__main__":
    example_text = """
    Misión Matemática: Los Números de Nuestra Tierra.
    Los niños trabajan en equipo para resolver retos usando números y analizar la producción en su pueblo.
    """
    prompt = build_ultimate_prompt(example_text)
    print(prompt)


