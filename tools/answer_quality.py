"""
tools/answer_quality.py
-----------------------
Controle simple de qualite des reponses humaines pour Agent 1.
"""

from __future__ import annotations

import re


VAGUE_PATTERNS = (
    "je sais pas",
    "je ne sais pas",
    "jsp",
    "ca depend",
    "cela depend",
    "plusieurs types",
    "des statistiques importantes",
    "les services concernes",
    "normalement",
    "a definir",
    "pas encore",
    "n'importe",
    "n import",
    "nimporte",
    "comme vous voulez",
    "tous",
    "tout",
    "toutes",
    "peu importe",
    "au choix",
    "etc",
    "ect",
)

EMPTY_VALUES = {
    "",
    "non renseigne",
    "non renseigné",
    "n/a",
    "na",
    "-",
}

SPECIFIC_SHORT_TERMS = {
    "admin",
    "manager",
    "rh",
    "client",
    "agent",
    "email",
    "sms",
    "web",
    "mobile",
    "pdf",
    "excel",
    "stripe",
    "paypal",
}

QUESTION_SPECIFIC_RULES = (
    {
        "question_keywords": ("medecin", "medecins", "médecin", "médecins", "specialite", "spécialité", "specialites", "spécialités"),
        "vague_answers": ("tous les medecins", "tous les médecins", "tous", "tout", "toutes"),
        "message": "liste de medecins ou specialites trop vague",
        "hint": "Donnez des exemples de specialites ou une regle de gestion, par exemple generaliste, cardiologue, pediatre, dentiste.",
    },
    {
        "question_keywords": ("statistique", "statistiques", "kpi", "indicateur", "indicateurs", "donnees", "données"),
        "vague_answers": ("n importe", "n'importe", "nimporte", "quelles statistiques", "toutes les statistiques", "des statistiques", "statistiques importantes", "tous", "tout"),
        "message": "statistiques demandees trop vagues",
        "hint": "Precisez les indicateurs attendus, par exemple nombre de rendez-vous, taux d'annulation, chiffre d'affaires, specialites les plus demandees.",
    },
    {
        "question_keywords": ("paiement", "modalites", "modalités", "payer", "passerelle"),
        "vague_answers": ("oui", "non", "en ligne", "passerelle", "paiement en ligne"),
        "message": "modalites de paiement insuffisamment precises",
        "hint": "Precisez au moins le mode ou la passerelle : carte bancaire, Stripe, PayPal, paiement sur place, remboursement.",
    },
    {
        "question_keywords": ("systeme externe", "système externe", "integration", "intégration", "integrer", "intégrer"),
        "vague_answers": ("oui", "non", "des systemes", "des systèmes", "passerelle", "api"),
        "message": "integration externe insuffisamment precise",
        "hint": "Nommez le systeme externe ou son role, par exemple passerelle de paiement Stripe, calendrier Google, SMS, dossier patient.",
    },
)


def normalize_answer(answer: str) -> str:
    normalized = str(answer or "").strip().lower()
    normalized = normalized.replace("à", "a").replace("â", "a")
    normalized = normalized.replace("é", "e").replace("è", "e").replace("ê", "e")
    normalized = normalized.replace("î", "i").replace("ï", "i")
    normalized = normalized.replace("ô", "o")
    normalized = normalized.replace("ù", "u").replace("û", "u")
    normalized = normalized.replace("ç", "c")
    return re.sub(r"\s+", " ", normalized)


def _words(answer: str) -> list[str]:
    return re.findall(r"\w+", normalize_answer(answer))


def _contains_vague_pattern(normalized: str) -> bool:
    words = re.findall(r"\w+", normalized)
    looks_detailed = len(words) >= 12 and any(separator in normalized for separator in (":", ";", ","))
    for pattern in VAGUE_PATTERNS:
        if pattern in {"etc", "ect", "jsp"}:
            if re.search(rf"\b{re.escape(pattern)}\b", normalized):
                return True
        elif pattern in {
            "plusieurs types",
            "les services concernes",
            "des statistiques importantes",
            "tous",
            "tout",
            "toutes",
        }:
            if pattern in normalized and not looks_detailed:
                return True
        elif pattern in normalized:
            return True
    return False


def _question_specific_issue(question: str, answer: str) -> str | None:
    normalized_question = normalize_answer(question)
    normalized_answer = normalize_answer(answer)
    words = _words(answer)
    looks_like_concrete_list = len(words) >= 5 and any(separator in normalized_answer for separator in (",", ";", ":"))

    for rule in QUESTION_SPECIFIC_RULES:
        if not any(keyword in normalized_question for keyword in rule["question_keywords"]):
            continue
        if any(vague in normalized_answer for vague in rule["vague_answers"]) and not looks_like_concrete_list:
            return f"{rule['message']}. {rule['hint']}"

    return None


def answer_quality_issue(question: str, answer: str) -> str | None:
    normalized = normalize_answer(answer)
    words = _words(answer)

    if normalized in EMPTY_VALUES:
        return "reponse vide ou non renseignee"

    question_issue = _question_specific_issue(question, answer)
    if question_issue:
        return question_issue

    if _contains_vague_pattern(normalized):
        return "reponse trop vague ou non exploitable"

    if len(words) == 1 and words[0] not in SPECIFIC_SHORT_TERMS:
        return "reponse trop courte"

    if len(words) == 2 and normalized in {"oui", "non", "oui oui", "non non"}:
        return "reponse trop courte"

    if len(words) < 2:
        return "reponse trop courte"

    return None


def is_answer_insufficient(question: str, answer: str) -> bool:
    return answer_quality_issue(question, answer) is not None


def find_answer_quality_issues(questions: list[str], answers: list[str]) -> list[dict]:
    issues = []
    for index, question in enumerate(questions):
        answer = answers[index] if index < len(answers) else "Non renseigne"
        issue = answer_quality_issue(question, answer)
        if issue:
            issues.append(
                {
                    "id": f"Q{index + 1}",
                    "question": question,
                    "answer": answer,
                    "issue": issue,
                }
            )
    return issues


def quality_feedback_message(question: str, answer: str) -> str | None:
    issue = answer_quality_issue(question, answer)
    if not issue:
        return None
    return (
        f"Agent 1 garde la main: {issue}. "
        "Donnez une reponse plus precise avant le passage a Agent 2."
    )
