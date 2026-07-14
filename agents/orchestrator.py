"""
agents/orchestrator.py
----------------------
Orchestrateur terminal Agent 1 -> Agent 2 -> Agent 3.
"""

from __future__ import annotations

import argparse
import json
import sys

from langgraph.graph import END, StateGraph

from agents.agent1_intake import (
    DEFAULT_INPUT,
    agent1_intake,
    collect_stakeholder_answers,
    collect_answer_with_agent1_quality_check,
    prepare_handoff_to_agent2,
    print_agent1_result,
    submit_stakeholder_answers,
)
from agents.agent2_validation import agent2_validation, get_a2a_questions, print_agent2_result
from agents.agent3_agile import agent3_agile, print_agent3_result
from core.state import SharedState, initial_state
from core.tracing import add_trace
from exporters.cahier_des_charges_exporter import export_cahier_des_charges


def _prompt_for_input() -> str:
    print("Demande client :")
    while True:
        try:
            raw_input = input("> ").strip()
        except EOFError:
            return ""
        if raw_input:
            return raw_input
        print("La demande client est obligatoire.")


def _append_a2a_answers(state: SharedState, questions: list[str]) -> SharedState:
    print("\n=== A2A FEEDBACK : AGENT 2 DEMANDE PLUS DE CLARIFICATION ===")
    answers = []
    for index, question in enumerate(questions, 1):
        print(f"\nA2A-Q{index}. {question}")
        answer = collect_answer_with_agent1_quality_check(
            question=question,
            input_func=input,
            output_func=print,
        )
        answers.append(answer)

    state["clarification_questions"].extend(questions)
    combined_answers = state.get("stakeholder_answers", []) + answers
    state = submit_stakeholder_answers(state, combined_answers)
    state["a2a_feedback"] = None
    state["conflicts"] = []
    state["requirements"] = []
    return state


def _route_to_agent2(state: SharedState, observation: str) -> SharedState:
    return add_trace(
        state,
        agent="Orchestrateur LangGraph",
        step="Routage vers Agent 2",
        observation=observation,
        decision="Executer le noeud Agent 2.",
        rationale="Les reponses humaines sont integrees au SharedState.",
    )


def _build_langgraph(
    file_path: str | None,
    max_a2a_rounds: int | None,
    json_output: bool,
    export_cdc: bool,
    export_dir: str,
):
    a2a_round = {"value": 0}

    def agent1_node(state: SharedState) -> SharedState:
        print("\n========== LANGGRAPH NODE : AGENT 1 ==========")
        return agent1_intake(state, file_path=file_path, verbose=True)

    def human_clarification_node(state: SharedState) -> SharedState:
        state = collect_stakeholder_answers(state)
        return prepare_handoff_to_agent2(state)

    def route_agent2_node(state: SharedState) -> SharedState:
        return _route_to_agent2(state, observation="ready_for_agent2=True.")

    def agent2_node(state: SharedState) -> SharedState:
        print("\n========== LANGGRAPH NODE : AGENT 2 ==========")
        return agent2_validation(state, verbose=True)

    def agent3_node(state: SharedState) -> SharedState:
        print("\n========== LANGGRAPH NODE : AGENT 3 ==========")
        return agent3_agile(state, verbose=True)

    def a2a_human_node(state: SharedState) -> SharedState:
        questions = get_a2a_questions(state)
        state = _append_a2a_answers(state, questions)
        a2a_round["value"] += 1
        return add_trace(
            state,
            agent="Orchestrateur LangGraph",
            step="Boucle A2A",
            observation=f"{len(questions)} question(s) de feedback A2A traitee(s).",
            decision="Relancer le noeud Agent 2 avec le SharedState enrichi.",
            rationale="Agent 2 avait detecte des informations bloquantes.",
        )

    def agent1_failure_node(state: SharedState) -> SharedState:
        if state.get("workflow_status") == "agent1_waiting_for_better_answers":
            print(
                "\nPipeline suspendu : Agent 1 attend des reponses humaines "
                "plus precises avant Agent 2."
            )
        else:
            print("\nPipeline arrete : Agent 1 n'a pas produit un etat pret pour Agent 2.")
        print_agent1_result(state)
        return state

    def max_a2a_reached_node(state: SharedState) -> SharedState:
        print("\nPipeline arrete : nombre maximal de feedbacks A2A atteint.")
        return add_trace(
            state,
            agent="Orchestrateur LangGraph",
            step="Limite A2A atteinte",
            observation=f"{a2a_round['value']} boucle(s) A2A deja effectuee(s).",
            decision="Arreter la boucle et afficher l'etat courant.",
            rationale="Une limite explicite a ete fournie via --max-a2a-rounds.",
        )

    def final_output_node(state: SharedState) -> SharedState:
        if json_output:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        elif state.get("user_stories"):
            print_agent3_result(state)
        else:
            print_agent2_result(state)

        if export_cdc and state.get("requirements"):
            try:
                paths = export_cahier_des_charges(state, output_dir=export_dir)
                print("\n=== EXPORT CAHIER DES CHARGES ===")
                print(f"Markdown : {paths['markdown']}")
                print(f"PDF      : {paths['pdf']}")
            except Exception as exc:
                state["errors"].append(f"export_cahier_des_charges : {exc}")
                print(f"\nErreur export cahier des charges : {exc}")
        return state

    def route_after_agent1(state: SharedState) -> str:
        if state.get("clarification_questions") and not state.get("stakeholder_answers"):
            return "human_clarification"
        if state.get("ready_for_agent2"):
            return "route_agent2"
        return "agent1_failure"

    def route_after_human(state: SharedState) -> str:
        if state.get("ready_for_agent2"):
            return "route_agent2"
        return "agent1_failure"

    def route_after_agent2(state: SharedState) -> str:
        questions = get_a2a_questions(state)
        if not questions:
            if state.get("requirements"):
                return "agent3"
            return "final_output"
        if max_a2a_rounds is not None and a2a_round["value"] >= max_a2a_rounds:
            return "max_a2a_reached"
        return "a2a_human"

    graph = StateGraph(SharedState)
    graph.add_node("agent1", agent1_node)
    graph.add_node("human_clarification", human_clarification_node)
    graph.add_node("route_agent2", route_agent2_node)
    graph.add_node("agent2", agent2_node)
    graph.add_node("agent3", agent3_node)
    graph.add_node("a2a_human", a2a_human_node)
    graph.add_node("agent1_failure", agent1_failure_node)
    graph.add_node("max_a2a_reached", max_a2a_reached_node)
    graph.add_node("final_output", final_output_node)

    graph.set_entry_point("agent1")
    graph.add_conditional_edges(
        "agent1",
        route_after_agent1,
        {
            "human_clarification": "human_clarification",
            "route_agent2": "route_agent2",
            "agent1_failure": "agent1_failure",
        },
    )
    graph.add_conditional_edges(
        "human_clarification",
        route_after_human,
        {
            "route_agent2": "route_agent2",
            "agent1_failure": "agent1_failure",
        },
    )
    graph.add_edge("route_agent2", "agent2")
    graph.add_conditional_edges(
        "agent2",
        route_after_agent2,
        {
            "a2a_human": "a2a_human",
            "agent3": "agent3",
            "max_a2a_reached": "max_a2a_reached",
            "final_output": "final_output",
        },
    )
    graph.add_edge("agent3", "final_output")
    graph.add_conditional_edges(
        "a2a_human",
        route_after_human,
        {
            "route_agent2": "route_agent2",
            "agent1_failure": "agent1_failure",
        },
    )
    graph.add_edge("max_a2a_reached", "final_output")
    graph.add_edge("agent1_failure", END)
    graph.add_edge("final_output", END)

    return graph.compile()


def run_pipeline(
    raw_input: str,
    file_path: str | None = None,
    max_a2a_rounds: int | None = None,
    json_output: bool = False,
    export_cdc: bool = True,
    export_dir: str = "outputs",
) -> SharedState:
    state = initial_state(raw_input=raw_input)
    state = add_trace(
        state,
        agent="Orchestrateur LangGraph",
        step="Demarrage pipeline",
        observation="Pipeline Agent 1 -> Human -> Agent 2 -> Agent 3 lance avec LangGraph.",
        decision="Executer le graphe depuis le noeud Agent 1.",
        rationale="LangGraph gere le routage conditionnel et la boucle A2A.",
    )

    graph = _build_langgraph(
        file_path=file_path,
        max_a2a_rounds=max_a2a_rounds,
        json_output=json_output,
        export_cdc=export_cdc,
        export_dir=export_dir,
    )
    return graph.invoke(state, config={"recursion_limit": 100})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orchestrateur Agent 1 -> Agent 2 -> Agent 3")
    parser.add_argument("--input", help="Demande client en texte brut.")
    parser.add_argument("--file", help="Chemin vers un fichier client a analyser.")
    parser.add_argument("--demo", action="store_true", help="Utilise une demande d'exemple.")
    parser.add_argument("--json", action="store_true", help="Affiche le SharedState complet.")
    parser.add_argument(
        "--export-cdc",
        action="store_true",
        dest="export_cdc",
        help="Exporte le cahier des charges en Markdown et PDF. Active par defaut.",
    )
    parser.add_argument(
        "--no-export-cdc",
        action="store_false",
        dest="export_cdc",
        help="Desactive l'export automatique du cahier des charges.",
    )
    parser.set_defaults(export_cdc=True)
    parser.add_argument(
        "--export-dir",
        default="outputs",
        help="Dossier de sortie pour les exports. Par defaut: outputs.",
    )
    parser.add_argument(
        "--max-a2a-rounds",
        type=int,
        default=None,
        help="Limite optionnelle des boucles A2A. Par defaut: boucle jusqu'a suffisance.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.demo:
        raw_input = DEFAULT_INPUT
    else:
        raw_input = args.input or ""

    if not raw_input and not args.file and sys.stdin.isatty():
        raw_input = _prompt_for_input()
    elif not raw_input and not args.file:
        print("Erreur : aucune demande client fournie. Utilise --input, --file ou --demo.")
        sys.exit(1)

    run_pipeline(
        raw_input=raw_input,
        file_path=args.file,
        max_a2a_rounds=args.max_a2a_rounds,
        json_output=args.json,
        export_cdc=args.export_cdc,
        export_dir=args.export_dir,
    )


if __name__ == "__main__":
    main()
