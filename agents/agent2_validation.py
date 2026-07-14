"""
agents/agent2_validation.py
---------------------------
Agent 2 - Validation & Analysis.

Flux:
    answer_consolidator -> validation_analyzer -> requirement_generator
    -> requirement_validator
"""

from __future__ import annotations

import json

from core.state import SharedState
from core.tracing import add_trace, print_trace
from tools.answer_consolidator import answer_consolidator
from tools.requirement_generator import requirement_generator
from tools.requirement_validator import requirement_validator
from tools.validation_analyzer import validation_analyzer


def _is_generic_a2a_question(question: str) -> bool:
    normalized = str(question or "").strip().lower()
    generic_patterns = (
        "preciser les informations manquantes",
        "informations manquantes avec des reponses concretes",
        "preciser cette information",
        "donnez plus de details",
        "pouvez-vous preciser davantage",
    )
    return any(pattern in normalized for pattern in generic_patterns)


def agent2_validation(state: SharedState, verbose: bool = False) -> SharedState:
    """Execute Agent 2 depuis le SharedState enrichi par Agent 1."""
    state["current_agent"] = "Agent 2 - Validation & Analysis"
    state["workflow_status"] = "agent2_started"
    state["next_agent"] = None
    state = add_trace(
        state,
        agent="Agent 2",
        step="Demarrage Validation & Analysis",
        observation="Reception du SharedState enrichi par Agent 1.",
        decision="Verifier si les informations permettent de produire des requirements.",
        rationale="Agent 2 doit decider entre generation REQ et feedback A2A.",
    )

    if not state.get("ready_for_agent2"):
        state["workflow_status"] = "agent2_blocked_missing_agent1_handoff"
        state["errors"].append(
            "Agent 2 : SharedState pas pret. Agent 1 doit fournir les reponses humaines."
        )
        return state

    if verbose:
        print("\nAgent 2 - Etape 1/8 : lecture du SharedState Agent 1...", flush=True)
    state = answer_consolidator(state)
    clarifications = (state.get("consolidated_data") or {}).get("clarifications", [])
    state = add_trace(
        state,
        agent="Agent 2",
        step="Consolidation",
        observation=f"{len(clarifications)} clarification(s) consolidee(s) avec la demande initiale.",
        decision="Construire consolidated_data.",
        rationale="La validation doit se baser sur l'analyse A1 plus les reponses humaines.",
    )

    if verbose:
        print("Agent 2 - Etape 2/8 : consolidation des reponses stakeholder...", flush=True)
        print("Agent 2 - Etape 3/8 : verification de suffisance...", flush=True)
        print("Agent 2 - Etape 4/8 : detection ambiguities/contradictions...", flush=True)
    state = validation_analyzer(state)
    validation = (state.get("consolidated_data") or {}).get("agent2_validation", {})
    if validation:
        state = add_trace(
            state,
            agent="Agent 2",
            step="Decision qualite",
            observation=(
                f"is_sufficient={validation.get('is_sufficient')}, "
                f"ambiguities={len(validation.get('ambiguities', []))}, "
                f"contradictions={len(validation.get('contradictions', []))}."
            ),
            decision=(
                "Demander feedback A2A."
                if state.get("a2a_feedback")
                else "Continuer vers generation des requirements."
            ),
            rationale=(
                "Une information bloquante manque encore."
                if state.get("a2a_feedback")
                else "Le contexte MVP est suffisant pour produire des REQ."
            ),
        )

    if state.get("a2a_feedback"):
        state["requirements"] = []
        return state

    if verbose:
        print("Agent 2 - Etape 5/8 : generation des requirements...", flush=True)
        print("Agent 2 - Etape 6/8 : classification par type...", flush=True)
        print("Agent 2 - Etape 7/8 : priorisation MoSCoW...", flush=True)
    state = requirement_generator(state)

    if verbose:
        print("Agent 2 - Etape 8/8 : validation JSON et IDs REQ...", flush=True)
    state = requirement_validator(state)
    state = add_trace(
        state,
        agent="Agent 2",
        step="Generation requirements",
        observation=f"{len(state.get('requirements', []))} requirement(s) valide(s) produit(s).",
        decision="Transmettre a Agent 3 si des requirements existent.",
        rationale="Agent 3 transforme ensuite les REQ en epics, user stories et backlog.",
    )

    if state.get("requirements"):
        state["workflow_status"] = "agent2_requirements_generated"
        state["next_agent"] = "Agent 3 - Agile & Backlog"

    return state


def get_a2a_questions(state: SharedState) -> list[str]:
    """Retourne les questions de feedback A2A si Agent 2 bloque."""
    feedback = state.get("a2a_feedback")
    if not feedback:
        return []
    try:
        parsed = json.loads(feedback)
    except json.JSONDecodeError:
        questions = [feedback]
    else:
        questions = parsed.get("suggested_questions", []) or []
    return [
        question
        for question in questions
        if isinstance(question, str) and question.strip() and not _is_generic_a2a_question(question)
    ]


def print_agent2_result(state: SharedState) -> None:
    print("\n=== AGENT 2 STATUS ===")
    print(f"  current_agent: {state.get('current_agent')}")
    print(f"  workflow_status: {state.get('workflow_status')}")
    print(f"  next_agent: {state.get('next_agent')}")
    print_trace(state)

    validation = (state.get("consolidated_data") or {}).get("agent2_validation")
    if validation:
        print("\n=== VALIDATION & ANALYSIS ===")
        print(json.dumps(validation, ensure_ascii=False, indent=2))

    if state.get("a2a_feedback"):
        print("\n=== FEEDBACK A2A VERS AGENT 1 ===")
        print(state["a2a_feedback"])

    if state.get("conflicts"):
        print("\n=== AMBIGUITES / CONTRADICTIONS ===")
        for conflict in state["conflicts"]:
            print(f"  - {conflict}")

    if state.get("requirements"):
        print("\n=== REQUIREMENTS ===")
        for requirement in state["requirements"]:
            print(
                f"{requirement['id']} [{requirement['type']} | {requirement['priority']}] "
                f"{requirement['title']}"
            )
            print(f"  {requirement['description']}")

    if state.get("errors"):
        print("\n=== ERREURS ===")
        for error in state["errors"]:
            print(f"  - {error}")
