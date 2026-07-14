"""
tools/text_cleaner.py
---------------------
Outil de pretraitement pour Agent 1.
Il corrige legerement le texte brut sans changer le sens de la demande.
"""

import re

from core.state import SharedState


COMMON_CORRECTIONS = {
    "consernve": "conserve",
    "conserne": "concerne",
    "partrimoine": "patrimoine",
    "patrimoine culturelle": "patrimoine culturel",
    "siteweb": "site web",
}


def text_cleaner(state: SharedState) -> SharedState:
    raw = state.get("raw_input", "")
    if not raw:
        return state

    cleaned = raw.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    lowered = cleaned.lower()
    for wrong, correct in COMMON_CORRECTIONS.items():
        lowered = lowered.replace(wrong, correct)

    # Preserve sentence casing enough for display, while applying typo fixes.
    cleaned = lowered[0].upper() + lowered[1:] if lowered else lowered
    state["raw_input"] = cleaned
    return state
