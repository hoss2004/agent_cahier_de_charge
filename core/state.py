"""
core/state.py
-------------
SharedState circule entre les agents.
Il contient la demande, l'analyse, les questions, les reponses humaines
et les indicateurs de routage vers l'agent suivant.
"""

from typing import Optional, TypedDict


class ExtractedInfo(TypedDict):
    domaine: str
    type_projet: str
    acteurs: list[str]
    objectif_principal: str
    fonctionnalites_identifiees: list[str]
    informations_manquantes: list[str]


class SharedState(TypedDict):
    # Agent 1 - Intake & Clarification
    raw_input: str
    extracted_info: Optional[ExtractedInfo]
    clarification_questions: list[str]
    stakeholder_answers: list[str]
    answer_quality_issues: list[dict]
    human_input_required: bool
    ready_for_agent2: bool

    # Agent 2 - Validation & Analysis
    consolidated_data: Optional[dict]
    conflicts: list[str]
    requirements: list[dict]
    a2a_feedback: Optional[str]

    # Agent 3 - Agile & Backlog
    epics: list[dict]
    features: list[dict]
    user_stories: list[dict]
    acceptance_criteria: list[dict]
    backlog: list[dict]
    traceability_matrix: list[dict]

    # Meta / routing
    current_agent: str
    next_agent: Optional[str]
    workflow_status: str
    agent_trace: list[dict]
    errors: list[str]


def initial_state(raw_input: str = "") -> SharedState:
    """Retourne un etat vide pret a etre injecte dans le pipeline."""
    return SharedState(
        raw_input=raw_input,
        extracted_info=None,
        clarification_questions=[],
        stakeholder_answers=[],
        answer_quality_issues=[],
        human_input_required=False,
        ready_for_agent2=False,
        consolidated_data=None,
        conflicts=[],
        requirements=[],
        a2a_feedback=None,
        epics=[],
        features=[],
        user_stories=[],
        acceptance_criteria=[],
        backlog=[],
        traceability_matrix=[],
        current_agent="",
        next_agent=None,
        workflow_status="initialized",
        agent_trace=[],
        errors=[],
    )
