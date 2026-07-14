"""
agents/agent1_intake.py
-----------------------
Agent 1 - Intake & Clarification.

Flux:
    file_reader -> text_cleaner -> input_analyzer -> clarification_generator -> human answers
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from core.state import SharedState, initial_state
from core.tracing import add_trace, print_trace
from tools.clarification_generator import clarification_generator
from tools.answer_quality import find_answer_quality_issues, quality_feedback_message
from tools.file_reader import file_reader
from tools.input_analyzer import input_analyzer
from tools.text_cleaner import text_cleaner


DEFAULT_INPUT = (
    "Je veux creer une application pour gerer les absences et conges "
    "des employes de notre entreprise. Les managers doivent pouvoir "
    "approuver ou refuser les demandes."
)


WORKFLOW_STEPS = [
    "Recoit la demande client (texte, PDF, Word, image)",
    "Analyse le besoin : domaine, type de projet, acteurs probables",
    "Detecte les informations manquantes",
    "Genere des questions de clarification ciblees",
    "Attend les reponses humaines dans le terminal",
    "Stocke questions + reponses dans le SharedState",
    "Transmet l'etat enrichi a l'Agent 2",
]

MAX_ANSWER_ATTEMPTS = 3


def agent1_intake(
    state: SharedState,
    file_path: str | None = None,
    verbose: bool = False,
) -> SharedState:
    """
    Execute l'Agent 1 jusqu'a la generation des questions de clarification.
    La collecte des reponses humaines est separee : une interface web
    pourra lire human_input_required=True et afficher les questions.
    """
    state["current_agent"] = "Agent 1 - Intake & Clarification"
    state["next_agent"] = None
    state["human_input_required"] = False
    state["ready_for_agent2"] = False
    state["workflow_status"] = "agent1_started"
    state = add_trace(
        state,
        agent="Agent 1",
        step="Initialisation",
        observation="Une demande client brute doit etre comprise et clarifiee.",
        decision="Demarrer le workflow Intake & Clarification.",
        rationale="Agent 1 prepare un SharedState exploitable par Agent 2.",
    )

    if verbose:
        print("Etape 1/7 : reception et lecture de la demande client...", flush=True)
    state = file_reader(state, file_path=file_path)
    state = text_cleaner(state)
    state = add_trace(
        state,
        agent="Agent 1",
        step="Reception de la demande",
        observation=f"Texte recu apres lecture/nettoyage: {len(state.get('raw_input', ''))} caracteres.",
        decision="Utiliser ce texte comme base d'analyse.",
        rationale="Le texte nettoye reduit les fautes evidentes sans changer le besoin.",
    )

    if not state.get("raw_input", "").strip():
        state["workflow_status"] = "agent1_failed_empty_input"
        state["errors"].append(
            "Agent 1 : raw_input est vide apres file_reader. "
            "Verifie que le fichier est lisible ou que du texte a ete saisi."
        )
        return state

    if verbose:
        print("Etape 2/7 : analyse du besoin...", flush=True)
    state = input_analyzer(state)
    if state.get("extracted_info"):
        info = state["extracted_info"]
        state = add_trace(
            state,
            agent="Agent 1",
            step="Analyse du besoin",
            observation=(
                f"Domaine={info.get('domaine')}, type={info.get('type_projet')}, "
                f"acteurs={', '.join(info.get('acteurs', []))}."
            ),
            decision="Conserver cette analyse dans extracted_info.",
            rationale="Ces elements structurent la suite: questions, validation et requirements.",
        )

    if not state.get("extracted_info"):
        state["workflow_status"] = "agent1_failed_analysis"
        state["errors"].append(
            "Agent 1 : extracted_info absent, clarification_generator ignore."
        )
        return state

    if verbose:
        print("Etape 3/7 : detection des informations manquantes...", flush=True)
        print("Etape 4/7 : generation des questions de clarification...", flush=True)
    state = clarification_generator(state)
    state = add_trace(
        state,
        agent="Agent 1",
        step="Generation des clarifications",
        observation=f"{len(state.get('clarification_questions', []))} question(s) generee(s).",
        decision="Demander une intervention humaine avant Agent 2.",
        rationale="Les reponses du stakeholder completent les informations manquantes.",
    )

    if state.get("clarification_questions"):
        state["human_input_required"] = True
        state["ready_for_agent2"] = False
        state["next_agent"] = None
        state["workflow_status"] = "awaiting_human_input"
        state = add_trace(
            state,
            agent="Agent 1",
            step="Decision Human-in-the-loop",
            observation="Des questions de clarification existent.",
            decision="Mettre human_input_required=True et suspendre le passage a Agent 2.",
            rationale="Agent 2 ne doit pas travailler avant les reponses humaines.",
        )
    else:
        state["human_input_required"] = False
        state["ready_for_agent2"] = True
        state["next_agent"] = "Agent 2 - Validation & Analysis"
        state["workflow_status"] = "ready_for_agent2_no_questions"
        state = add_trace(
            state,
            agent="Agent 1",
            step="Decision Human-in-the-loop",
            observation="Aucune question de clarification n'a ete generee.",
            decision="Marquer le SharedState comme pret pour Agent 2.",
            rationale="Les informations semblent suffisantes pour l'analyse Agent 2.",
        )

    return state


def collect_stakeholder_answers(
    state: SharedState,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> SharedState:
    """Demande les reponses humaines et les stocke dans SharedState."""
    questions = state.get("clarification_questions", [])
    if not questions:
        output_func("\nAucune question de clarification a poser.")
        return state

    output_func("\nEtape 5/7 : attente des reponses humaines.")
    output_func("\n=== INTERACTION HUMAIN / STAKEHOLDER ===")
    output_func("Repondez aux questions. Laissez vide si l'information est inconnue.")

    answers: list[str] = []
    for index, question in enumerate(questions, 1):
        output_func(f"\nQ{index}. {question}")
        answer = collect_answer_with_agent1_quality_check(
            question=question,
            input_func=input_func,
            output_func=output_func,
        )
        answers.append(answer)

    return submit_stakeholder_answers(state, answers, output_func=output_func)


def collect_answer_with_agent1_quality_check(
    question: str,
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
) -> str:
    """Agent 1 garde la main tant que la reponse est trop faible."""
    last_answer = ""
    for attempt in range(1, MAX_ANSWER_ATTEMPTS + 1):
        try:
            answer = input_func("Votre reponse : ").strip()
        except EOFError:
            return "Non renseigne"

        last_answer = answer
        feedback = quality_feedback_message(question, answer)
        if not feedback:
            return answer

        output_func(feedback)
        if attempt < MAX_ANSWER_ATTEMPTS:
            output_func(
                "Essayez de preciser avec des exemples, roles, regles, statuts, "
                "delais, donnees ou canaux concrets."
            )

    return last_answer or "Non renseigne"


def submit_stakeholder_answers(
    state: SharedState,
    answers: list[str],
    output_func: Callable[[str], None] | None = None,
) -> SharedState:
    """Stocke les reponses humaines et prepare la transmission a l'Agent 2."""
    questions = state.get("clarification_questions", [])
    normalized_answers = [
        answer.strip() if isinstance(answer, str) and answer.strip() else "Non renseigne"
        for answer in answers
    ]

    if len(normalized_answers) < len(questions):
        normalized_answers.extend(["Non renseigne"] * (len(questions) - len(normalized_answers)))

    state["stakeholder_answers"] = normalized_answers[: len(questions)]
    quality_issues = find_answer_quality_issues(questions, state["stakeholder_answers"])
    state["answer_quality_issues"] = quality_issues

    if quality_issues:
        state["human_input_required"] = True
        state["ready_for_agent2"] = False
        state["next_agent"] = None
        state["workflow_status"] = "agent1_waiting_for_better_answers"
        state = add_trace(
            state,
            agent="Agent 1",
            step="Controle qualite des reponses humaines",
            observation=f"{len(quality_issues)} reponse(s) insuffisante(s) detectee(s).",
            decision="Ne pas transmettre le SharedState a Agent 2.",
            rationale=(
                "Agent 1 doit traiter les reponses vides, trop courtes ou vagues "
                "avant le passage a Agent 2."
            ),
        )

        if output_func:
            output_func("\nEtape 6/7 : questions + reponses stockees dans SharedState.")
            output_func("Agent 1 bloque le passage a Agent 2 : reponses insuffisantes.")
            for issue in quality_issues:
                output_func(
                    f"  - {issue['id']} : {issue['issue']} "
                    f"(reponse: {issue['answer']})"
                )
            output_func("Etape 7/7 : transmission a Agent 2 suspendue.")

        return state

    state["human_input_required"] = False
    state["ready_for_agent2"] = True
    state["next_agent"] = "Agent 2 - Validation & Analysis"
    state["workflow_status"] = "ready_for_agent2"
    state = add_trace(
        state,
        agent="Agent 1",
        step="Integration des reponses humaines",
        observation=f"{len(state['stakeholder_answers'])} reponse(s) stakeholder stockee(s).",
        decision="Marquer ready_for_agent2=True.",
        rationale="Le SharedState contient maintenant demande, analyse, questions et reponses.",
    )

    if output_func:
        output_func("\nEtape 6/7 : questions + reponses stockees dans SharedState.")
        output_func("Etape 7/7 : etat enrichi pret a etre transmis a l'Agent 2.")

    return state


def prepare_handoff_to_agent2(state: SharedState) -> SharedState:
    """Conserve la compatibilite avec l'ancien nom de fonction."""
    if state.get("answer_quality_issues"):
        return state
    if state.get("stakeholder_answers"):
        state["human_input_required"] = False
        state["ready_for_agent2"] = True
        state["next_agent"] = "Agent 2 - Validation & Analysis"
        state["workflow_status"] = "ready_for_agent2"
        state["current_agent"] = "Agent 1 termine - SharedState pret pour Agent 2"
    return state


def print_agent1_result(state: SharedState) -> None:
    """Affiche un resume lisible de l'etat produit par l'Agent 1."""
    print("\n=== WORKFLOW STATUS ===")
    print(f"  current_agent: {state.get('current_agent')}")
    print(f"  workflow_status: {state.get('workflow_status')}")
    print(f"  human_input_required: {state.get('human_input_required')}")
    print(f"  ready_for_agent2: {state.get('ready_for_agent2')}")
    print(f"  next_agent: {state.get('next_agent')}")
    print_trace(state)

    print("\n=== EXTRACTED INFO ===")
    print(json.dumps(state.get("extracted_info"), ensure_ascii=False, indent=2))

    print("\n=== QUESTIONS DE CLARIFICATION ===")
    for index, question in enumerate(state.get("clarification_questions", []), 1):
        print(f"  {index}. {question}")

    if state.get("stakeholder_answers"):
        print("\n=== REPONSES DU STAKEHOLDER ===")
        for index, (question, answer) in enumerate(
            zip(state["clarification_questions"], state["stakeholder_answers"]),
            1,
        ):
            print(f"  Q{index}. {question}")
            print(f"  R{index}. {answer}")

        if state.get("answer_quality_issues"):
            print("\n=== CONTROLE QUALITE AGENT 1 ===")
            for issue in state["answer_quality_issues"]:
                print(
                    f"  - {issue['id']} : {issue['issue']} "
                    f"(reponse: {issue['answer']})"
                )
            print("Agent 1 garde la main avant le passage a Agent 2.")
        elif state.get("ready_for_agent2"):
            print("\n=== HANDOFF VERS AGENT 2 ===")
            print("Etape 7/7 : SharedState enrichi pret a etre transmis a l'Agent 2.")

    if state.get("errors"):
        print("\n=== ERREURS ===")
        for error in state["errors"]:
            print(f"  - {error}")


def _prompt_for_input() -> str:
    print("Demande client :")
    while True:
        try:
            raw_input = input("> ").strip()
        except EOFError:
            return ""
        if raw_input:
            return raw_input
        print("La demande client est obligatoire. Saisis un texte ou utilise --file.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent 1 - Intake & Clarification")
    parser.add_argument("--input", help="Demande client en texte brut.")
    parser.add_argument("--file", help="Chemin vers un fichier client a analyser.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Utilise une demande d'exemple pour tester le pipeline.",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Ne demande pas les reponses du stakeholder dans le terminal.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Affiche le SharedState complet en JSON.",
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

    state = initial_state(raw_input=raw_input)
    state = agent1_intake(state, file_path=args.file, verbose=True)

    if not args.no_interactive and state.get("clarification_questions"):
        state = collect_stakeholder_answers(state)
        state = prepare_handoff_to_agent2(state)

    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        print_agent1_result(state)


if __name__ == "__main__":
    main()
