#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_synthesizer.py
Crea prompts visuales automáticamente a partir de cualquier texto (ES).
No requiere reglas por tema: extrae sujetos, acciones, objetos y contexto
con spaCy (si está disponible) o con un fallback heurístico.

Uso:
    from prompt_synthesizer import build_visual_prompt
    p = build_visual_prompt(paragraph_text, doc_title)
"""

from typing import List, Tuple
import re
import os

# Intentamos usar spaCy si está disponible; si no, fallback.
USE_SPACY = False
nlp = None
try:
    import spacy
    # Permite ajustar por entorno: es_core_news_md > es_core_news_sm
    _model = os.getenv("SPACY_ES_MODEL", "es_core_news_md")
    nlp = spacy.load(_model)
    USE_SPACY = True
except Exception:
    USE_SPACY = False


# Palabras poco visuales (evitamos centrarlas en la escena)
ABSTRACT_STOP = {
    "idea","concepto","teoría","historia","cultura","sistema","proceso","método",
    "información","cantidad","tiempo","serie","conjunto","uso","necesidad",
    "tecnología","herramienta","algoritmo","posicional","invención","viaje",
    "origen","números","matemáticas","clase","práctica","registro"
}

# Términos de seguridad/negativos a desalentar en la imagen
NEGATIVE_CUES = [
    "watermark","logo","text overlay","subtítulos","texto","marcas de agua",
    "bocadillos", "caption", "screenshot", "panel de interfaz"
]

def _clean_text(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)  # **negrita**
    s = re.sub(r'__(.+?)__', r'\1', s)      # __subrayado__
    s = s.replace(r'\(', '(').replace(r'\)', ')').replace(r'\*', '*')
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def _top_items(seq: List[str], k: int) -> List[str]:
    from collections import Counter
    return [w for w,_ in Counter(seq).most_common(k)]

def _tokens_heuristic(text: str) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Fallback sin spaCy: extrae listas aproximadas de sujetos, verbos, objetos y lugares.
    Muy sencilla pero suficiente como red de seguridad.
    """
    # Partimos por comas y puntos, y extraemos palabras con minúsculas
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\-']{3,}", text)
    words_lower = [w.lower() for w in words]
    # Verbos aproximados por terminaciones comunes en ES (grosero, pero útil)
    verbs = [w for w in words_lower if w.endswith(("ar","er","ir","ando","endo","iendo","ado","ido"))]
    nouns = [w for w in words_lower if w not in verbs]
    # Posibles lugares (heurística) por pistas léxicas
    places = [w for w in nouns if w.endswith(("ia","cio","cia","polis","desa","landia")) or w in {"egipto","roma","india","babilonia"}]
    subjects = [w for w in nouns if w not in ABSTRACT_STOP]
    objects_ = [w for w in nouns if w not in ABSTRACT_STOP]
    return _top_items(subjects, 3), _top_items(verbs, 2), _top_items(objects_, 4), _top_items(places, 2)

def _tokens_spacy(text: str):
    """
    Con spaCy: extrae sujetos (suj/nsubj), verbos (VERB), objetos (dobj/obj),
    nombres propios/entidades y lugares (GPE/LOC), además de fechas.
    """
    doc = nlp(text)
    verbs, subjects, objects_, places, dates, ents = [], [], [], [], [], []

    for t in doc:
        if t.pos_ == "VERB":
            verbs.append(t.lemma_.lower())
        # sujetos y objetos (dep puede variar según modelo)
        if t.dep_ in ("nsubj","nsubj:pass") and t.pos_ in ("NOUN","PROPN"):
            if t.lemma_.lower() not in ABSTRACT_STOP:
                subjects.append(t.text)
        if t.dep_ in ("obj","dobj","iobj") and t.pos_ in ("NOUN","PROPN"):
            if t.lemma_.lower() not in ABSTRACT_STOP:
                objects_.append(t.text)

    for ent in doc.ents:
        ents.append((ent.text, ent.label_))
        if ent.label_ in ("GPE","LOC"):
            places.append(ent.text)
        if ent.label_ in ("DATE",):
            dates.append(ent.text)

    # Noun chunks para reforzar sujetos/objetos visuales
    for nc in doc.noun_chunks:
        head = nc.root.lemma_.lower()
        if head not in ABSTRACT_STOP and len(nc.text) <= 60:
            # heurística simple: si el head es sujeto u objeto potencial
            if nc.root.dep_ in ("nsubj","nsubj:pass"):
                subjects.append(nc.text)
            else:
                objects_.append(nc.text)

    subjects = _top_items([s.strip() for s in subjects if s.strip()], 3)
    verbs    = _top_items([v.strip() for v in verbs if v.strip()], 2)
    objects_ = _top_items([o.strip() for o in objects_ if o.strip()], 4)
    places   = _top_items([p.strip() for p in places if p.strip()], 2)
    dates    = _top_items([d.strip() for d in dates if d.strip()], 2)

    return subjects, verbs, objects_, places, dates, ents

def build_visual_prompt(text: str, doc_title: str = "") -> str:
    """
    Devuelve un prompt visual (ES) genérico a partir de cualquier texto.
    Sin nombres hardcodeados; usa lo que encuentre en el propio párrafo.
    """
    raw = _clean_text(f"{doc_title}. {text}") if doc_title else _clean_text(text)

    if USE_SPACY:
        subjects, verbs, objects_, places, dates, _ = _tokens_spacy(raw)
    else:
        subjects, verbs, objects_, places = _tokens_heuristic(raw)
        dates = []

    # Si no se encontró nada visual, reforzamos con términos genéricos
    if not subjects and not objects_:
        objects_ = ["elementos clave del tema"]
    if not verbs:
        verbs = ["representar"]
    # Estilo: infografía si el texto parece conceptual; ilustración si hay sujetos/acciones
    style = "infografía didáctica minimalista" if len(objects_) >= 3 and not places else "ilustración educativa contemporánea"

    # Construimos piezas
    subj_str  = ", ".join(subjects[:2]) if subjects else ""
    verb_str  = ", ".join(verbs[:2])
    obj_str   = ", ".join(objects_[:4])
    place_str = f" Ambientación: {', '.join(places[:2])}." if places else ""
    date_str  = f" Contexto temporal: {', '.join(dates[:1])}." if dates else ""

    negative = ", ".join(NEGATIVE_CUES)

    prompt = (
        f"{style}, clara y legible, sin texto ni marcas. "
        f"Enfoque educativo (12–16 años). "
        f"Escena principal: {subj_str} {verb_str}. "
        f"Elementos visuales clave: {obj_str}.{place_str}{date_str} "
        f"Composición limpia, colores equilibrados, fondo neutro, alta nitidez. "
        f"Evitar: {negative}."
    ).strip()

    # Limpieza final de espacios dobles/puntuación
    prompt = re.sub(r"\s{2,}", " ", prompt)
    prompt = prompt.replace("..", ".")
    return prompt
