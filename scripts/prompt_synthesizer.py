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
except Exception:
    USE_SPACY = False

# Palabras abstractas que no deben aparecer en la escena
ABSTRACT_STOP = {
    "idea","concepto","teoría","historia","cultura","sistema","proceso","método",
    "información","cantidad","tiempo","serie","conjunto","uso","necesidad","tecnología",
    "herramienta","algoritmo","posicional","invención","viaje","origen","números",
    "matemáticas","clase","práctica","registro"
}

# Palabras a evitar en la descripción visual
NEGATIVE_CUES = [
    "texto", "palabras", "letras", "firmas", "marcas de agua", "UI", "interfaz",
    "screenshot", "bocadillo de diálogo", "subtítulos"
]

# Stopwords básicas para limpiar sujetos y objetos
STOPWORDS = {
    "el","la","los","las","un","una","unos","unas","de","del","en","por","para",
    "a","y","o","que","se","con","su","sus","al","como","es","son"
}

def _clean_text(s: str) -> str:
    """Limpia texto de markdown y espacios"""
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = s.replace(r'\(', '(').replace(r'\)', ')').replace(r'\*', '*')
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def _top_items(seq: List[str], k: int) -> List[str]:
    """Devuelve los k elementos más frecuentes"""
    from collections import Counter
    return [w for w,_ in Counter(seq).most_common(k)]

def _tokens_heuristic(text: str) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Heurística sencilla si no hay spaCy"""
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\-']{3,}", text)
    words_lower = [w.lower() for w in words if w.lower() not in STOPWORDS]
    verbs = [w for w in words_lower if w.endswith(("ar","er","ir","ando","endo","iendo","ado","ido"))]
    nouns = [w for w in words_lower if w not in verbs]
    places = [w for w in nouns if w.endswith(("ia","cio","cia","polis","desa","landia")) or w in {"egipto","roma","india","babilonia"}]
    subjects = [w for w in nouns if w not in ABSTRACT_STOP]
    objects_ = [w for w in nouns if w not in ABSTRACT_STOP]
    return _top_items(subjects, 3), _top_items(verbs, 2), _top_items(objects_, 4), _top_items(places, 2)

def _tokens_spacy(text: str):
    """Extracción usando spaCy"""
    doc = nlp(text)
    verbs, subjects, objects_, places = [], [], [], []
    for t in doc:
        if t.pos_ == "VERB":
            verbs.append(t.lemma_.lower())
        elif t.dep_ in ("nsubj", "nsubj:pass") and t.pos_ in ("NOUN", "PROPN"):
            if t.lemma_.lower() not in ABSTRACT_STOP and t.text.lower() not in STOPWORDS:
                subjects.append(t.text.lower())
        elif t.dep_ in ("obj", "dobj", "iobj") and t.pos_ in ("NOUN", "PROPN"):
            if t.lemma_.lower() not in ABSTRACT_STOP and t.text.lower() not in STOPWORDS:
                objects_.append(t.text.lower())
    for ent in doc.ents:
        if ent.label_ in ("GPE","LOC"):
            places.append(ent.text.lower())
    return _top_items(subjects, 3), _top_items(verbs, 2), _top_items(objects_, 4), _top_items(places, 2)

def build_visual_prompt(text: str, doc_title: str = "") -> str:
    """Construye el prompt visual final"""
    raw = _clean_text(f"{doc_title}. {text}") if doc_title else _clean_text(text)
    if USE_SPACY:
        subjects, verbs, objects_, places = _tokens_spacy(raw)
    else:
        subjects, verbs, objects_, places = _tokens_heuristic(raw)
    
    if not subjects and not objects_:
        objects_ = ["concepto clave del tema"]
    if not verbs:
        verbs = ["representando"]
    
    scene_elements = list(dict.fromkeys(subjects + objects_ + places))
    scene = ", ".join(_top_items(scene_elements, 4))
    action = verbs[0]

    prompt = (
        f"Arte conceptual, ilustración digital educativa, colores vivos, estilo libro infantil. "
        f"Escena principal que muestra {scene} {action}. "
        f"Claridad y simplicidad. Sin texto ni marcas. "
        f"Evitar: {', '.join(NEGATIVE_CUES)}."
    )
    return re.sub(r"\s{2,}", " ", prompt).strip()

