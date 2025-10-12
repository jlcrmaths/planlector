#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_pdfs_comic.py

Genera uno o varios PDFs a partir de imágenes (cómics, historias, tiras).
- Acepta --input-folder y --output-folder (con alias).
- Modos: auto | per-subfolder | per-folder
- Ordenación natural por defecto (01, 02, 10...).

Requisitos:
    pip install pillow

Ejemplos:
    # Auto: si hay subcarpetas, un PDF por subcarpeta; si no, un único PDF
    python generar_pdfs_comic.py --input-folder historias --output-folder pdfs_generados

    # Un PDF por subcarpeta explícitamente
    python generar_pdfs_comic.py --input-folder historias --output-folder pdfs --mode per-subfolder

    # Un único PDF con TODAS las imágenes (recursivo)
    python generar_pdfs_comic.py --input-folder historias --output-folder pdfs --mode per-folder --recursive --output-name todo_en_uno.pdf
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Iterable, Tuple
import re
from PIL import Image


# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("generar_pdfs_comic")


# ---------------------------
# Utilidades
# ---------------------------
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def natural_key(s: str):
    """
    Clave de ordenación natural: divide cadenas en bloques [texto|número].
    'page10.png' > ['page', 10, '.png']
    """
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"([0-9]+)", s)]


def iter_image_files(folder: Path, pattern: str, recursive: bool) -> Iterable[Path]:
    """
    Itera imágenes en 'folder' respetando el patrón (varios separados por ';').
    """
    patterns = [p.strip() for p in pattern.split(";") if p.strip()]
    if not patterns:
        patterns = ["*"]

    for pat in patterns:
        if recursive:
            yield from folder.rglob(pat)
        else:
            yield from folder.glob(pat)


def collect_images(folder: Path, pattern: str, recursive: bool) -> List[Path]:
    """
    Devuelve lista de rutas de imagen válidas (por extensión), sin duplicados, existentes.
    """
    seen = set()
    files = []
    for p in iter_image_files(folder, pattern, recursive):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        files.append(rp)
    return files


def sort_images(files: List[Path], how: str = "natural") -> List[Path]:
    """
    Ordena la lista de imágenes por:
      - 'natural' (por defecto): por nombre con ordenación natural
      - 'name': por nombre simple (lexicográfico)
      - 'mtime': por fecha de modificación
    """
    if how == "natural":
        return sorted(files, key=lambda p: natural_key(p.name))
    if how == "name":
        return sorted(files, key=lambda p: p.name.lower())
    if how == "mtime":
        return sorted(files, key=lambda p: p.stat().st_mtime)
    return files


def save_as_pdf(images: List[Path], out_pdf: Path) -> None:
    """
    Guarda una lista de imágenes en un PDF de varias páginas.
    Convierte todo a RGB para evitar problemas con transparencias.
    """
    if not images:
        raise ValueError("No hay imágenes para exportar.")

    pil_images = []
    for idx, img_path in enumerate(images):
        try:
            im = Image.open(img_path)
            if im.mode in ("RGBA", "LA"):
                im = im.convert("RGB")
            elif im.mode not in ("RGB", "L"):
                # Normalizamos a RGB
                im = im.convert("RGB")
            # Importante: Pillow requiere que la primera imagen sea distinta de las append_images
            pil_images.append(im)
        except Exception as e:
            raise RuntimeError(f"Error abriendo {img_path}: {e}") from e

    first, rest = pil_images[0], pil_images[1:]
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    first.save(out_pdf, "PDF", resolution=300.0, save_all=True, append_images=rest)


def make_pdf_name_from_folder(folder: Path) -> str:
    """
    Crea un nombre de PDF a partir del nombre de la carpeta.
    """
    base = folder.name.strip() or "salida"
    return f"{base}.pdf"


def find_immediate_subfolders(folder: Path) -> List[Path]:
    return sorted([p for p in folder.iterdir() if p.is_dir()], key=lambda p: natural_key(p.name))


# ---------------------------
# CLI
# ---------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Genera PDFs a partir de imágenes (un PDF por carpeta o por subcarpeta)."
    )
    # Aliases para compatibilidad: --input-folder / --input_dir / --in / -i
    p.add_argument(
        "--input-folder", "--input_dir", "--in", "-i",
        dest="input_folder",
        required=True,
        help="Carpeta de entrada con imágenes y/o subcarpetas.",
    )
    # Aliases: --output-folder / --output_dir / --out / -o
    p.add_argument(
        "--output-folder", "--output_dir", "--out", "-o",
        dest="output_folder",
        required=True,
        help="Carpeta de salida para los PDFs generados.",
    )
    p.add_argument(
        "--mode",
        choices=["auto", "per-subfolder", "per-folder"],
        default="auto",
        help="Modo de generación: auto (por defecto), per-subfolder (un PDF por subcarpeta), per-folder (un único PDF).",
    )
    p.add_argument(
        "--recursive",
        action="store_true",
        help="Si se usa con per-folder, busca imágenes recursivamente.",
    )
    p.add_argument(
        "--pattern",
        default="*.jpg;*.jpeg;*.png;*.webp;*.bmp;*.tif;*.tiff",
        help="Patrón(es) glob separados por ';' para seleccionar imágenes.",
    )
    p.add_argument(
        "--sort",
        choices=["natural", "name", "mtime"],
        default="natural",
        help="Orden de páginas: natural (def), name o mtime.",
    )
    p.add_argument(
        "--output-name",
        default=None,
        help="Nombre del PDF de salida (solo aplica en modo per-folder o cuando no hay subcarpetas).",
    )
    return p


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
    except SystemExit as e:
        # Mantiene el comportamiento de argparse pero permite que CI vea el exit code
        return e.code

    in_dir = Path(args.input_folder).resolve()
    out_dir = Path(args.output_folder).resolve()

    if not in_dir.exists() or not in_dir.is_dir():
        log.error(f"La carpeta de entrada no existe o no es un directorio: {in_dir}")
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    mode = args.mode
    subfolders = find_immediate_subfolders(in_dir)

    if mode == "auto":
        mode = "per-subfolder" if subfolders else "per-folder"

    log.info(f"Modo: {mode}")
    log.info(f"Entrada: {in_dir}")
    log.info(f"Salida:  {out_dir}")

    try:
        if mode == "per-subfolder":
            if not subfolders:
                log.warning("No se encontraron subcarpetas; no hay nada que procesar en 'per-subfolder'.")
                return 0

            total = 0
            for sf in subfolders:
                imgs = sort_images(collect_images(sf, args.pattern, recursive=False), args.sort)
                if not imgs:
                    log.warning(f"[{sf.name}] Sin imágenes válidas, se omite.")
                    continue
                pdf_name = make_pdf_name_from_folder(sf)
                out_pdf = out_dir / pdf_name
                log.info(f"[{sf.name}] {len(imgs)} imágenes -> {out_pdf.name}")
                save_as_pdf(imgs, out_pdf)
                total += 1

            log.info(f"Listo. PDFs generados: {total}")
            return 0

        elif mode == "per-folder":
            imgs = sort_images(collect_images(in_dir, args.pattern, recursive=args.recursive), args.sort)
            if not imgs:
                log.error("No se encontraron imágenes en la carpeta de entrada.")
                return 2

            pdf_name = args.output_name or make_pdf_name_from_folder(in_dir)
            out_pdf = out_dir / pdf_name
            log.info(f"{len(imgs)} imágenes -> {out_pdf.name}")
            save_as_pdf(imgs, out_pdf)
            log.info("Listo.")
            return 0

        else:
            log.error(f"Modo no reconocido: {mode}")
            return 2

    except Exception as e:
        log.exception(f"Fallo durante la generación de PDFs: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

