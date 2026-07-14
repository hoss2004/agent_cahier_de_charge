"""
agents/agent3_agile.py
----------------------
Agent 3 - Agile & Backlog.

Flux:
    requirements -> epics -> features -> user stories
    -> acceptance criteria -> backlog -> traceability matrix
"""

from __future__ import annotations

import json

from core.state import SharedState
from core.tracing import add_trace, print_trace
from tools.agile_artifact_generator import agile_artifact_generator
from tools.agile_artifact_validator import agile_artifact_validator


def agent3_agile(state: SharedState, verbose: bool = False) -> SharedState:
    """Execute Agent 3 depuis les requirements produits par Agent 2."""
    state["current_agent"] = "Agent 3 - Agile & Backlog"
    state["workflow_status"] = "agent3_started"
    state["next_agent"] = None
    state = add_trace(
        state,
        agent="Agent 3",
        step="Demarrage Agile & Backlog",
        observation="Reception des requirements produits par Agent 2.",
        decision="Transformer les requirements en artefacts agiles.",
        rationale="L'equipe projet a besoin d'epics, user stories, backlog et tracabilite.",
    )

    if not state.get("requirements"):
        state["workflow_status"] = "agent3_blocked_missing_requirements"
        state["errors"].append(
            "Agent 3 : requirements absents. Agent 2 doit generer les exigences avant Agent 3."
        )
        return state

    if verbose:
        print("\nAgent 3 - Etape 1/10 : lecture des requirements Agent 2...", flush=True)
        print("Agent 3 - Etape 2/10 : regroupement par themes...", flush=True)
        print("Agent 3 - Etape 3/10 : creation des Epics...", flush=True)
        print("Agent 3 - Etape 4/10 : decomposition en Features...", flush=True)
        print("Agent 3 - Etape 5/10 : generation des User Stories...", flush=True)
        print("Agent 3 - Etape 6/10 : generation des criteres Given/When/Then...", flush=True)
        print("Agent 3 - Etape 7/10 : priorisation MoSCoW...", flush=True)
        print("Agent 3 - Etape 8/10 : estimation story points...", flush=True)
        print("Agent 3 - Etape 9/10 : construction du backlog initial...", flush=True)
        print("Agent 3 - Etape 10/10 : matrice de tracabilite REQ -> US -> AC...", flush=True)

    state = agile_artifact_generator(state)
    state = add_trace(
        state,
        agent="Agent 3",
        step="Generation artefacts agiles",
        observation=(
            f"{len(state.get('epics', []))} epic(s), "
            f"{len(state.get('features', []))} feature(s), "
            f"{len(state.get('user_stories', []))} user storie(s) generee(s)."
        ),
        decision="Normaliser les artefacts et garantir la tracabilite.",
        rationale="Les IDs, priorites, story points et liens REQ-US-AC doivent etre coherents.",
    )

    state = agile_artifact_validator(state)
    state = add_trace(
        state,
        agent="Agent 3",
        step="Validation backlog et tracabilite",
        observation=(
            f"{len(state.get('backlog', []))} item(s) backlog et "
            f"{len(state.get('traceability_matrix', []))} ligne(s) de tracabilite."
        ),
        decision="Marquer les artefacts agiles comme disponibles.",
        rationale="Le cahier des charges final pourra reutiliser ces artefacts.",
    )

    if state.get("user_stories"):
        state["workflow_status"] = "agent3_backlog_generated"
        state["next_agent"] = "Export JSON / Markdown - Cahier des charges"

    return state


def print_agent3_result(state: SharedState) -> None:
    print("\n=== AGENT 3 STATUS ===")
    print(f"  current_agent: {state.get('current_agent')}")
    print(f"  workflow_status: {state.get('workflow_status')}")
    print(f"  next_agent: {state.get('next_agent')}")
    print_trace(state)

    if state.get("epics"):
        print("\n=== EPICS ===")
        for epic in state["epics"]:
            print(
                f"{epic['id']} [{epic.get('priority', 'Should')}] "
                f"{epic.get('title', '')}"
            )
            print(f"  REQ: {', '.join(epic.get('requirement_ids', []))}")

    if state.get("features"):
        print("\n=== FEATURES ===")
        for feature in state["features"]:
            print(
                f"{feature['id']} -> {feature.get('epic_id')} "
                f"[{feature.get('priority', 'Should')}] {feature.get('title', '')}"
            )

    if state.get("user_stories"):
        print("\n=== USER STORIES ===")
        for story in state["user_stories"]:
            print(
                f"{story['id']} [{story.get('priority', 'Should')} | "
                f"{story.get('story_points', 3)} pts] {story.get('story', '')}"
            )
            for ac in story.get("acceptance_criteria", []):
                print(f"  {ac['id']}:")
                print(f"    Given {ac.get('given', '')}")
                print(f"    When {ac.get('when', '')}")
                print(f"    Then {ac.get('then', '')}")

    if state.get("backlog"):
        print("\n=== BACKLOG INITIAL ===")
        for item in state["backlog"]:
            print(
                f"{item['rank']}. {item['item_id']} "
                f"[{item.get('priority', 'Should')} | {item.get('story_points', 3)} pts] "
                f"{item.get('title', '')}"
            )

    if state.get("traceability_matrix"):
        print("\n=== TRACEABILITY MATRIX REQ -> US -> AC ===")
        for row in state["traceability_matrix"]:
            print(
                f"{row['requirement_id']} -> "
                f"{', '.join(row.get('user_story_ids', []))} -> "
                f"{', '.join(row.get('acceptance_criteria_ids', []))}"
            )

    if state.get("errors"):
        print("\n=== ERREURS / NOTES ===")
        for error in state["errors"]:
            print(f"  - {error}")


def print_agent3_json(state: SharedState) -> None:
    print(json.dumps(state, ensure_ascii=False, indent=2))
