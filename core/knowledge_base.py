"""
core/knowledge_base.py
----------------------
Charge le referentiel metier utilise par les agents.
"""

from __future__ import annotations

import json
from pathlib import Path


_KB_DIR = Path(__file__).resolve().parents[1] / "knowledge_base"


def _read_text(filename: str) -> str:
    path = _KB_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _read_json(filename: str) -> dict:
    text = _read_text(filename)
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _compact_json(filename: str) -> str:
    data = _read_json(filename)
    if not data:
        return ""
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_knowledge_context(agent_role: str) -> str:
    """
    Retourne uniquement le contexte utile au role demande.

    Le contexte reste volontairement court pour ne pas saturer les petits
    modeles locaux comme qwen2.5:3b.
    """
    template = _read_text("cahier_des_charges_template.md")
    question_taxonomy = _compact_json("question_taxonomy.json")
    requirement_types = _compact_json("requirement_types.json")
    requirement_schema = _compact_json("requirement_schema.json")
    agile_schema = _compact_json("agile_schema.json")

    if agent_role in {"agent1_analyzer", "agent1_clarifier"}:
        parts = [
            "REFERENTIEL AGENT 1",
            "Utilise ce referentiel comme grille de controle, sans le recopier.",
            "Taxonomie des questions:",
            question_taxonomy,
            "Structure cible du cahier des charges:",
            template,
        ]
    elif agent_role == "agent2_validator":
        parts = [
            "REFERENTIEL AGENT 2 - VALIDATION",
            "Utilise ce referentiel pour verifier si les informations sont exploitables.",
            "Types de requirements:",
            requirement_types,
            "Schema attendu:",
            requirement_schema,
            "Structure cible du cahier des charges:",
            template,
        ]
    elif agent_role == "agent2_requirement_generator":
        parts = [
            "REFERENTIEL AGENT 2 - REQUIREMENTS",
            "Utilise ce referentiel pour generer des requirements complets et classes.",
            "Types de requirements:",
            requirement_types,
            "Schema attendu:",
            requirement_schema,
        ]
    elif agent_role == "agent3_agile_generator":
        parts = [
            "REFERENTIEL AGENT 3 - AGILE & BACKLOG",
            "Utilise ce referentiel pour transformer les requirements en artefacts agiles.",
            "Schema Agile attendu:",
            agile_schema,
            "Structure cible du cahier des charges:",
            template,
        ]
    else:
        parts = [
            "REFERENTIEL GENERAL",
            template,
            question_taxonomy,
            requirement_types,
            requirement_schema,
            agile_schema,
        ]

    return "\n\n".join(part for part in parts if part)


def augment_prompt(system_prompt: str, agent_role: str) -> str:
    context = build_knowledge_context(agent_role)
    if not context:
        return system_prompt
    return f"{system_prompt}\n\n---\n\n{context}".strip()
