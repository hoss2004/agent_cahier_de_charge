"""
tools/input_analyzer.py
-----------------------
Outil 2 de l'Agent 1 — Premier appel LLM.
Analyse raw_input et extrait les infos structurées dans extracted_info.
"""

from core.state import SharedState, ExtractedInfo
from core.knowledge_base import augment_prompt
from core.llm_client import call_llm_json
from prompts.prompt_intake import SYSTEM_PROMPT_ANALYZER


def _normalize_text(text: str) -> str:
    normalized = str(text or "").lower()
    replacements = {
        "Ã©": "e",
        "Ã¨": "e",
        "Ãª": "e",
        "Ã ": "a",
        "Ã¢": "a",
        "Ã®": "i",
        "Ã´": "o",
        "Ã¹": "u",
        "Ã§": "c",
        "é": "e",
        "è": "e",
        "ê": "e",
        "à": "a",
        "ç": "c",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _apply_domain_overrides(result: dict, raw: str) -> dict:
    normalized = _normalize_text(raw)
    if "reclamation" in normalized or "service client" in normalized:
        result["domaine"] = "service client / gestion des reclamations"
        result["acteurs"] = [
            "client",
            "agent service client",
            "service interne",
            "responsable",
            "administrateur",
        ]
        result["type_projet"] = result.get("type_projet") or "application web"
    return result


def input_analyzer(state: SharedState) -> SharedState:
    """
    Appelle Gemini pour analyser state['raw_input'].
    Remplit state['extracted_info'] avec le résultat structuré.

    Returns:
        state mis à jour
    """
    raw = state.get("raw_input", "").strip()
    if not raw:
        state["errors"].append("input_analyzer : raw_input est vide.")
        return state

    user_message = f"Demande client à analyser :\n\n{raw}"

    try:
        prompt = augment_prompt(SYSTEM_PROMPT_ANALYZER, "agent1_analyzer")
        result = call_llm_json(prompt, user_message)
        result = _apply_domain_overrides(result, raw)

        # Validation minimale des clés attendues
        required_keys = {
            "domaine", "type_projet", "acteurs",
            "objectif_principal", "fonctionnalites_identifiees",
            "informations_manquantes"
        }
        missing = required_keys - set(result.keys())
        if missing:
            state["errors"].append(
                f"input_analyzer : clés manquantes dans la réponse LLM : {missing}"
            )
            # On remplit quand même avec ce qu'on a
        
        state["extracted_info"] = ExtractedInfo(
            domaine=result.get("domaine", "Non déterminé"),
            type_projet=result.get("type_projet", "Non déterminé"),
            acteurs=result.get("acteurs", []),
            objectif_principal=result.get("objectif_principal", ""),
            fonctionnalites_identifiees=result.get("fonctionnalites_identifiees", []),
            informations_manquantes=result.get("informations_manquantes", []),
        )

    except (ValueError, RuntimeError) as e:
        state["errors"].append(f"input_analyzer : {e}")

    return state
