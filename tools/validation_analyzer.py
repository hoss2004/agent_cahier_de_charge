"""
tools/validation_analyzer.py
----------------------------
Agent 2 tool: detecte insuffisances, ambiguities et contradictions.

Regle importante:
Une ancienne reponse vague peut etre resolue par une reponse A2A plus recente.
Agent 2 doit donc verifier les clarifications dans l'ordre chronologique.
"""

import json
import os
import re

from core.knowledge_base import augment_prompt
from core.llm_client import call_llm_json
from core.state import SharedState
from prompts.prompt_validation import SYSTEM_PROMPT_VALIDATOR


VAGUE_PATTERNS = (
    "ca depend",
    "cela depend",
    "plusieurs types",
    "les services concernes",
    "des statistiques importantes",
    "je ne sais pas",
    "je sais pas",
    "normalement",
    "tous les types",
    "les statuts habituels",
    "pas encore",
    "a definir",
    "selon le cas",
    "n'importe",
    "n import",
    "nimporte",
    "peu importe",
    "comme vous voulez",
    "tous",
    "tout",
    "toutes",
)

QUESTION_SPECIFIC_RULES = (
    {
        "question_keywords": ("medecin", "medecins", "médecin", "médecins", "specialite", "spécialité", "specialites", "spécialités"),
        "vague_answers": ("tous les medecins", "tous les médecins", "tous", "tout", "toutes"),
        "label": "les medecins et specialites disponibles",
        "question": "Quels medecins ou specialites doivent etre disponibles au lancement ? Donnez une liste concrete ou une regle de gestion.",
    },
    {
        "question_keywords": ("statistique", "statistiques", "kpi", "indicateur", "indicateurs", "donnees", "données"),
        "vague_answers": ("n importe", "n'importe", "nimporte", "quelles statistiques", "toutes les statistiques", "des statistiques", "statistiques importantes", "tous", "tout"),
        "label": "les statistiques attendues",
        "question": "Quelles statistiques exactes voulez-vous suivre ? Exemple : nombre de rendez-vous, taux d'annulation, chiffre d'affaires, specialites les plus demandees.",
    },
    {
        "question_keywords": ("paiement", "modalites", "modalités", "payer", "passerelle"),
        "vague_answers": ("oui", "non", "en ligne", "passerelle", "paiement en ligne"),
        "label": "les modalites de paiement",
        "question": "Quelles modalites de paiement faut-il gerer exactement : carte bancaire, paiement sur place, Stripe, PayPal, remboursement ?",
    },
    {
        "question_keywords": ("systeme externe", "système externe", "integration", "intégration", "integrer", "intégrer"),
        "vague_answers": ("oui", "non", "des systemes", "des systèmes", "passerelle", "api"),
        "label": "les integrations externes",
        "question": "Quels systemes externes doivent etre integres et pour quel usage exact ?",
    },
)


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "oui", "1"}
    return bool(value)


def _normalize_validation(result: dict) -> dict:
    feedback = result.get("a2a_feedback") or {}
    return {
        "is_sufficient": _as_bool(result.get("is_sufficient", False)),
        "confidence": result.get("confidence", "low"),
        "ambiguities": result.get("ambiguities", []) or [],
        "contradictions": result.get("contradictions", []) or [],
        "missing_information": result.get("missing_information", []) or [],
        "a2a_feedback": {
            "needs_more_clarification": _as_bool(feedback.get("needs_more_clarification", False)),
            "reason": feedback.get("reason", ""),
            "suggested_questions": feedback.get("suggested_questions", []) or [],
        },
    }


def _normalize_text(text: str) -> str:
    normalized = str(text).strip().lower()
    normalized = normalized.replace("Ã©", "e").replace("é", "e")
    normalized = normalized.replace("Ã¨", "e").replace("è", "e")
    normalized = normalized.replace("Ã ", "a").replace("à", "a")
    normalized = normalized.replace("Ã§", "c").replace("ç", "c")
    normalized = normalized.replace("Ã´", "o").replace("ô", "o")
    return re.sub(r"\s+", " ", normalized)


def _keywords(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"\w+", _normalize_text(text))
        if len(word) >= 4
    }


def _has_substantive_answer(answer: str) -> bool:
    normalized = _normalize_text(answer)
    return bool(normalized) and normalized not in {
        "non renseigne",
        "non renseigné",
        "n/a",
        "na",
        "-",
    }


def _is_vague_answer(answer: str) -> bool:
    normalized = _normalize_text(answer)
    if not _has_substantive_answer(normalized):
        return True

    words = [word for word in re.findall(r"\w+", normalized) if len(word) > 2]
    looks_detailed = len(words) >= 12 and any(separator in normalized for separator in (":", ";", ","))
    if any(pattern in normalized for pattern in VAGUE_PATTERNS) and not looks_detailed:
        return True

    # "etc/ect" alone is vague, but a concrete list ending with etc is acceptable.
    if normalized in {"etc", "ect"}:
        return True
    if len(words) <= 4 and re.search(r"\b(et+c?|etc|ect)\b", normalized):
        return True

    return len(words) < 3


def _question_specific_insufficiency(item: dict) -> dict | None:
    question = _normalize_text(item.get("question", ""))
    answer = _normalize_text(item.get("answer", ""))
    words = [word for word in re.findall(r"\w+", answer) if len(word) > 2]
    looks_like_concrete_list = len(words) >= 5 and any(separator in answer for separator in (",", ";", ":"))

    for rule in QUESTION_SPECIFIC_RULES:
        if not any(keyword in question for keyword in rule["question_keywords"]):
            continue
        if any(vague in answer for vague in rule["vague_answers"]) and not looks_like_concrete_list:
            return {
                "label": rule["label"],
                "question": rule["question"],
            }
    return None


def _is_text_resolved_by_answer(text: str, clarifications: list[dict]) -> bool:
    text_keywords = _keywords(text)
    if not text_keywords:
        return False

    for item in clarifications:
        answer = item.get("answer", "")
        if _is_vague_answer(answer):
            continue

        question_keywords = _keywords(item.get("question", ""))
        answer_keywords = _keywords(answer)
        if len(text_keywords & question_keywords) >= 2:
            return True
        if len(text_keywords & answer_keywords) >= 2:
            return True

    return False


def _is_insufficient_answer_resolved(item: dict, later_items: list[dict]) -> bool:
    original_question = item.get("question", "")
    original_answer = _normalize_text(item.get("answer", ""))
    original_question_keywords = _keywords(original_question)

    for later_item in later_items:
        later_answer = later_item.get("answer", "")
        if _is_vague_answer(later_answer):
            continue

        later_question = _normalize_text(later_item.get("question", ""))
        later_question_keywords = _keywords(later_question)
        later_answer_keywords = _keywords(later_answer)

        if original_answer and original_answer in later_question:
            return True
        if len(original_question_keywords & later_question_keywords) >= 2:
            return True
        if len(original_question_keywords & later_answer_keywords) >= 2:
            return True

    return False


def _find_insufficient_answers(consolidated: dict) -> list[dict]:
    insufficient = []
    clarifications = consolidated.get("clarifications", [])
    for index, item in enumerate(clarifications):
        specific_issue = _question_specific_insufficiency(item)
        if specific_issue:
            enriched = dict(item)
            enriched["specific_issue"] = specific_issue
            insufficient.append(enriched)
            continue

        if _is_vague_answer(item.get("answer", "")) and not _is_insufficient_answer_resolved(
            item,
            clarifications[index + 1 :],
        ):
            insufficient.append(item)
    return insufficient


def _dedupe(items: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for item in items:
        text = str(item).strip()
        key = _normalize_text(text)
        if key and key not in seen:
            seen.add(key)
            deduped.append(text)
    return deduped


def _filter_resolved_items(items: list[str], consolidated: dict) -> list[str]:
    clarifications = consolidated.get("clarifications", [])
    return [
        item
        for item in items
        if not _is_text_resolved_by_answer(item, clarifications)
    ]


def _question_from_gap(gap: str) -> str:
    cleaned = str(gap).strip().rstrip(".?")
    if not cleaned:
        return "Pouvez-vous preciser cette information avec des exemples concrets ?"
    return f"Pouvez-vous preciser {cleaned} avec une reponse concrete et exploitable ?"


def _is_generic_question(question: str) -> bool:
    normalized = _normalize_text(question)
    generic_patterns = (
        "preciser les informations manquantes",
        "informations manquantes avec des reponses concretes",
        "preciser cette information",
        "donnez plus de details",
        "pouvez-vous preciser davantage",
    )
    return any(pattern in normalized for pattern in generic_patterns)


def _filter_specific_questions(questions: list[str]) -> list[str]:
    return [
        question
        for question in _dedupe(questions)
        if question and not _is_generic_question(question)
    ]


def _question_from_insufficient_answer(item: dict) -> str:
    specific_issue = item.get("specific_issue")
    if specific_issue:
        return specific_issue["question"]

    question = item.get("question", "cette information")
    answer = item.get("answer", "")
    return (
        f"Votre reponse '{answer}' est trop vague. "
        f"Pour la question '{question}', donnez une reponse precise "
        "avec des exemples, valeurs, roles, regles ou delais concrets."
    )


def _apply_strict_sufficiency_rules(validation: dict, consolidated: dict) -> dict:
    feedback = validation["a2a_feedback"]
    insufficient_answers = _find_insufficient_answers(consolidated)
    insufficient_ambiguities = []

    for item in insufficient_answers:
        insufficient_ambiguities.append(
            f"Reponse insuffisante a {item.get('id', 'question')}: "
            f"'{item.get('answer', '')}'"
        )

    validation["ambiguities"] = _dedupe(
        _filter_resolved_items(validation["ambiguities"], consolidated)
        + insufficient_ambiguities
    )
    validation["contradictions"] = _dedupe(
        _filter_resolved_items(validation["contradictions"], consolidated)
    )
    validation["missing_information"] = _dedupe(
        _filter_resolved_items(validation["missing_information"], consolidated)
    )

    feedback["suggested_questions"] = _filter_specific_questions(
        _filter_resolved_items(feedback.get("suggested_questions", []), consolidated)
    )

    has_real_blocker = (
        bool(validation["missing_information"])
        or bool(validation["ambiguities"])
        or bool(validation["contradictions"])
        or bool(insufficient_answers)
    )
    has_specific_feedback_question = bool(feedback["suggested_questions"])

    must_block = (
        has_real_blocker
        or has_specific_feedback_question
    )

    if must_block:
        validation["is_sufficient"] = False
        feedback["needs_more_clarification"] = True
        if not feedback.get("reason"):
            feedback["reason"] = (
                "Les informations contiennent encore des manques, ambiguities, "
                "contradictions ou reponses trop vagues."
            )

        insufficient_questions = [
            _question_from_insufficient_answer(item) for item in insufficient_answers
        ]
        gap_questions = []
        gap_questions.extend(
            _question_from_gap(gap) for gap in validation["missing_information"]
        )
        gap_questions.extend(
            _question_from_gap(ambiguity) for ambiguity in validation["ambiguities"]
        )

        feedback["suggested_questions"] = _filter_specific_questions(
            _filter_resolved_items(feedback["suggested_questions"], consolidated)
            + insufficient_questions
            + _filter_resolved_items(gap_questions, consolidated)
        )[:3]

        if not feedback["suggested_questions"]:
            validation["is_sufficient"] = True
            validation["confidence"] = "medium"
            validation["missing_information"] = []
            validation["ambiguities"] = []
            validation["contradictions"] = []
            feedback["needs_more_clarification"] = False
            feedback["reason"] = (
                "Agent 2 n'a detecte aucun manque precis a clarifier. "
                "Les requirements peuvent etre generes."
            )
            feedback["suggested_questions"] = []
    else:
        validation["is_sufficient"] = True
        if _normalize_text(validation.get("confidence", "")) == "low":
            validation["confidence"] = "medium"
        feedback["needs_more_clarification"] = False
        feedback["reason"] = "Les informations sont suffisantes pour generer les requirements MVP."
        feedback["suggested_questions"] = []

    return validation


def _local_validation(consolidated: dict) -> dict:
    return _apply_strict_sufficiency_rules(
        {
            "is_sufficient": True,
            "confidence": "medium",
            "ambiguities": [],
            "contradictions": [],
            "missing_information": [],
            "a2a_feedback": {
                "needs_more_clarification": False,
                "reason": "Validation locale effectuee par Agent 2.",
                "suggested_questions": [],
            },
        },
        consolidated,
    )


def _store_validation_result(state: SharedState, validation: dict) -> SharedState:
    feedback = validation["a2a_feedback"]
    state["consolidated_data"]["agent2_validation"] = validation
    state["conflicts"] = validation["ambiguities"] + validation["contradictions"]

    if feedback["needs_more_clarification"] or not validation["is_sufficient"]:
        state["a2a_feedback"] = json.dumps(feedback, ensure_ascii=False)
        state["workflow_status"] = "agent2_needs_more_clarification"
        state["next_agent"] = "Agent 1 - Intake & Clarification"
    else:
        state["a2a_feedback"] = None

    return state


def validation_analyzer(state: SharedState) -> SharedState:
    consolidated = state.get("consolidated_data")
    if not consolidated:
        state["errors"].append("validation_analyzer : consolidated_data absent.")
        return state

    if not _env_flag("AGENT2_VALIDATION_USE_LLM", default=True):
        validation = _local_validation(consolidated)
        return _store_validation_result(state, validation)

    try:
        user_message = (
            "SharedState consolide a valider :\n\n"
            f"{json.dumps(consolidated, ensure_ascii=False, indent=2)}"
        )
        prompt = augment_prompt(SYSTEM_PROMPT_VALIDATOR, "agent2_validator")
        result = call_llm_json(prompt, user_message)
        if not isinstance(result, dict):
            raise ValueError("La reponse de validation doit etre un objet JSON.")

        validation = _normalize_validation(result)
        validation = _apply_strict_sufficiency_rules(validation, consolidated)
        state = _store_validation_result(state, validation)

    except (ValueError, RuntimeError) as e:
        validation = _local_validation(consolidated)
        state = _store_validation_result(state, validation)
        if not validation["is_sufficient"]:
            state["errors"].append(f"validation_analyzer : fallback local apres erreur LLM ({e})")

    return state
