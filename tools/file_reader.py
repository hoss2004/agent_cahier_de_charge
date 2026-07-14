"""
tools/file_reader.py
--------------------
Outil 1 de l'Agent 1.
Lit n'importe quel fichier entrant et retourne son texte brut.
Supporte : .txt, .md, .pdf, .docx, et images (via OCR Gemini).
"""

import os
import base64
from pathlib import Path
from core.state import SharedState


# ── Extracteurs par type ───────────────────────────────────────────────────────

def _read_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _read_pdf(path: str) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        raise ImportError(
            "PyMuPDF non installé. Lance : pip install pymupdf"
        )


def _read_docx(path: str) -> str:
    try:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise ImportError(
            "python-docx non installé. Lance : pip install python-docx"
        )


def _read_image(path: str) -> str:
    """Utilise Gemini Vision pour extraire le texte d'une image."""
    import google.generativeai as genai
    from PIL import Image

    image = Image.open(path)
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content([
        "Extrais tout le texte visible dans cette image. "
        "Retourne uniquement le texte, sans commentaire.",
        image
    ])
    return response.text.strip()


# ── Fonction principale ────────────────────────────────────────────────────────

def file_reader(state: SharedState, file_path: str | None = None) -> SharedState:
    """
    Lit le fichier spécifié et stocke son contenu dans state['raw_input'].

    Args:
        state:      le SharedState courant
        file_path:  chemin vers le fichier à lire (None = utilise state['raw_input'] déjà rempli)

    Returns:
        state mis à jour avec raw_input rempli
    """
    if file_path is None:
        # Pas de fichier : le texte est déjà dans raw_input (saisie directe)
        return state

    path = Path(file_path)
    if not path.exists():
        state["errors"].append(f"Fichier introuvable : {file_path}")
        return state

    ext = path.suffix.lower()

    try:
        if ext in (".txt", ".md"):
            text = _read_txt(file_path)
        elif ext == ".pdf":
            text = _read_pdf(file_path)
        elif ext in (".docx", ".doc"):
            text = _read_docx(file_path)
        elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            text = _read_image(file_path)
        else:
            state["errors"].append(f"Format non supporté : {ext}")
            return state

        state["raw_input"] = text.strip()

    except Exception as e:
        state["errors"].append(f"Erreur lecture fichier : {e}")

    return state
