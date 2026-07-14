"""
tools/clarification_generator.py
---------------------------------
Outil 3 de l'Agent 1 — Deuxième appel LLM.
Génère les questions de clarification à partir de extracted_info.
"""

import json
from core.state import SharedState
from core.knowledge_base import augment_prompt
from core.llm_client import call_llm_json
from prompts.prompt_intake import SYSTEM_PROMPT_CLARIFIER


def clarification_generator(state: SharedState) -> SharedState:
    """
    Appelle Gemini pour générer 3–5 questions de clarification.
    Remplit state['clarification_questions'].

    Returns:
        state mis à jour
    """
    info = state.get("extracted_info")
    if not info:
        state["errors"].append(
            "clarification_generator : extracted_info est vide, "
            "input_analyzer doit être exécuté avant."
        )
        return state

    user_message = (
        f"Voici l'analyse structurée de la demande client :\n\n"
        f"{json.dumps(info, ensure_ascii=False, indent=2)}\n\n"
        f"Demande originale :\n{state.get('raw_input', '')}"
    )

    try:
        prompt = augment_prompt(SYSTEM_PROMPT_CLARIFIER, "agent1_clarifier")
        questions = call_llm_json(prompt, user_message)

        if not isinstance(questions, list):
            raise ValueError("La réponse doit être une liste JSON de questions.")

        # Nettoyage : filtrer les questions vides
        questions = [q.strip() for q in questions if isinstance(q, str) and q.strip()]

        if not questions:
            state["errors"].append("clarification_generator : aucune question générée.")
        else:
            state["clarification_questions"] = questions

    except (ValueError, RuntimeError) as e:
        state["errors"].append(f"clarification_generator : {e}")

    return state
