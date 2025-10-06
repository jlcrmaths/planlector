#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from typing import List, Tuple
import re
import os

USE_SPACY = False
nlp = None
try:
    import spacy
    _model = os.getenv("SPACY_ES_MODEL", "es_core_news_md")
    nlp = spacy.load(_model)
    USE_SPACY = True
except Exception: USE_SPACY = False

ABSTRACT_STOP = {"idea","concepto","teoría","historia","cultura","sistema","proceso","método","información","cantidad","tiempo","serie","conjunto","uso","necesidad","tecnología","herramienta","algoritmo","posicional","invención","viaje","origen","números","matemáticas","clase","práctica","registro"}

# --- INICIO DE LA MODIFICACIÓN ---
# Lista de prompts negativos mucho más potente
NEGATIVE_CUES = [
    "feo", "deforme", "mal dibujado", "múltiples figuras", "mala anatomía", "extremidades extra", 
    "dedos extra", "mala calidad", "borroso", "texto", "letras", "firmas", "marcas de agua", 
    "UI", "interfaz", "bocadillo de diálogo", "subtítulos", "mutilado"
]
# --- FIN DE LA MODIFICACIÓN ---

def _clean_text(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s); s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def _top_items(seq: List[str], k: int) -> List[str]:
    from collections import Counter
    return [w for w,_ in Counter(seq).most_common(k)]

def _tokens_heuristic(text: str) -> Tuple[List[str], List[str], List[str]]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\-']{3,}", text)
    words_lower = [w.lower() for w in words]
    verbs = [w for w in words_lower if w.endswith(("ar","er","ir","ando","endo","iendo","ado","ido"))]
    nouns = [w for w in words_lower if w not in verbs and w not in ABSTRACT_STOP]
    return _top_items(nouns, 5), _top_items(verbs, 2), []

def build_visual_prompt(text: str, doc_title: str = "") -> str:
    raw = _clean_text(f"{doc_title}. {text}") if doc_title else _clean_text(text)
    subjects, verbs, _ = _tokens_heuristic(raw)
    
    if not subjects: subjects = ["concepto clave del tema"]
    
    scene = ", ".join(subjects[:4])
    
    prompt = (
        f"arte conceptual, ilustración digital para libro educativo, colores vivos, estilo simple y claro. "
        f"Escena principal sobre {scene}. "
        f"Enfoque en claridad pedagógica. Sin texto. "
        f"Evitar: {', '.join(NEGATIVE_CUES)}."
    )
    
    return re.sub(r"\s{2,}", " ", prompt).strip()

