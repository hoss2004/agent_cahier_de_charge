"""
tools/agile_artifact_generator.py
---------------------------------
Agent 3 tool: genere epics, features, user stories, backlog et tracabilite.
"""

from __future__ import annotations

import json
import os
import re

from core.knowledge_base import augment_prompt
from core.llm_client import call_llm_json
from core.state import SharedState
from prompts.prompt_agile import SYSTEM_PROMPT_AGILE_GENERATOR


PRIORITY_ORDER = {"Must": 1, "Should": 2, "Could": 3, "Won't": 4}


THEME_BY_TYPE = {
    "functional": "Fonctionnalites principales",
    "non_functional": "Qualite de service",
    "business_rule": "Regles metier",
    "data": "Donnees et historique",
    "security": "Securite et acces",
    "reporting": "Reporting et statistiques",
    "integration": "Integrations externes",
    "ui_ux": "Experience utilisateur",
    "constraint": "Contraintes techniques",
}


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_text(text: str) -> str:
    normalized = str(text or "").strip().lower()
    replacements = {
        "à": "a",
        "â": "a",
        "é": "e",
        "è": "e",
        "ê": "e",
        "î": "i",
        "ï": "i",
        "ô": "o",
        "ù": "u",
        "û": "u",
        "ç": "c",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"\s+", " ", normalized)


def _priority(requirement: dict) -> str:
    priority = requirement.get("priority", "Should")
    return priority if priority in PRIORITY_ORDER else "Should"


def _estimate_story_points(requirement: dict) -> int:
    req_type = requirement.get("type", "functional")
    description = requirement.get("description", "")
    words = len(description.split())

    if req_type in {"security", "integration", "reporting"}:
        return 5
    if req_type in {"non_functional", "constraint"}:
        return 3
    if words > 28:
        return 5
    return 3


def _theme_for_requirement(requirement: dict) -> str:
    return THEME_BY_TYPE.get(requirement.get("type"), "Fonctionnalites principales")


def _role_for_requirement(requirement: dict, state: SharedState) -> str:
    text = f"{requirement.get('title', '')} {requirement.get('description', '')}".lower()
    normalized = _normalize_text(text)
    title_normalized = _normalize_text(requirement.get("title", ""))
    if title_normalized.startswith("suivre le statut"):
        return "client"
    if any(word in normalized for word in ("notifier", "notification", "email", "alerte")):
        return "client"
    if any(word in normalized for word in ("statistique", "indicateur", "temps moyen", "taux de resolution", "reporting")):
        return "responsable"
    if any(word in normalized for word in ("classer", "categorie", "priorite", "cycle de vie", "statut", "affecter")):
        return "agent service client"
    if any(word in normalized for word in ("service interne", "configurer les services")):
        return "administrateur"
    if any(word in normalized for word in ("information complementaire", "dossier incomplet")):
        return "agent service client"
    role_keywords = [
        ("admin", "administrateur"),
        ("responsable", "responsable"),
        ("manager", "manager"),
        ("agent", "agent service client"),
        ("employe", "employe"),
        ("artisan", "artisan"),
        ("rh", "RH"),
        ("client", "client"),
    ]
    for keyword, role in role_keywords:
        if keyword in text:
            return role

    actors = (state.get("extracted_info") or {}).get("acteurs", [])
    if actors:
        actor = str(actors[0]).strip().lower()
        return actor[:-1] if actor.endswith("s") else actor
    return "utilisateur"


def _action_from_requirement(requirement: dict) -> str:
    title = requirement.get("title", "utiliser la fonctionnalite").strip()
    normalized = _normalize_text(title)

    if normalized.startswith("notifier"):
        return "recevoir des notifications sur les changements importants"
    if normalized.startswith("mesurer les indicateurs"):
        return "consulter les indicateurs de performance du service client"
    if normalized.startswith("gerer le cycle de vie"):
        return "mettre a jour le cycle de vie des reclamations"
    if normalized.startswith("configurer les services"):
        return "configurer les services internes responsables"

    def build_action(target: str, suffix: str) -> str:
        suffix = suffix.strip()
        if not suffix:
            return target.strip()
        normalized_suffix = _normalize_text(suffix)
        if normalized_suffix.startswith(
            ("un ", "une ", "des ", "du ", "de la ", "de l'", "le ", "la ", "les ", "l'")
        ):
            return re.sub(r"\s+", " ", f"{target} {suffix}".strip())
        if target in {"creer", "ajouter"}:
            article = "des" if normalized_suffix.endswith("s") else "un"
            return re.sub(r"\s+", " ", f"{target} {article} {suffix}".strip())
        return re.sub(r"\s+", " ", f"{target} {suffix}".strip())

    replacements = [
        ("creation de", "creer"),
        ("creation d'", "creer "),
        ("creation du", "creer le"),
        ("creation des", "creer les"),
        ("soumission de", "soumettre"),
        ("soumission d'", "soumettre "),
        ("choix du", "choisir le"),
        ("choix de", "choisir"),
        ("ajout de", "ajouter"),
        ("ajout d'", "ajouter "),
        ("suivi du", "suivre le"),
        ("suivi de", "suivre"),
        ("consultation des", "consulter les"),
        ("consultation de", "consulter"),
        ("gestion des", "gerer les"),
        ("gestion de", "gerer"),
        ("affichage des", "afficher les"),
        ("affichage de", "afficher"),
    ]
    for source, target in replacements:
        if normalized.startswith(source):
            suffix = title[len(source) :].strip()
            suffix = re.split(r"\s+par\s+", suffix, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            return build_action(target, suffix)
    return title[0].lower() + title[1:] if title else "utiliser la fonctionnalite"


def _benefit_from_requirement(requirement: dict) -> str:
    text = _normalize_text(
        f"{requirement.get('title', '')} {requirement.get('description', '')}"
    )
    if any(keyword in text for keyword in ("statistique", "temps moyen", "rapport", "indicateur", "taux de resolution", "taux de rejet", "satisfaction")):
        return "analyser la qualite du service client"
    if any(keyword in text for keyword in ("notifier", "notification", "email", "alerte")):
        return "etre informe des changements importants"
    if any(keyword in text for keyword in ("information complementaire", "informations complementaires", "dossier incomplet")):
        return "completer les dossiers avant traitement"
    if any(keyword in text for keyword in ("categorie", "priorite", "classer")):
        return "orienter correctement le traitement de la reclamation"
    if "cycle de vie" in text:
        return "assurer un traitement coherent des reclamations"
    if any(keyword in text for keyword in ("compte", "authentification", "connexion")):
        return "acceder a l'application de maniere securisee"
    if any(keyword in text for keyword in ("piece jointe", "pieces jointes", "document")):
        return "fournir les preuves ou documents utiles au traitement"
    if any(keyword in text for keyword in ("statut", "suivi")):
        return "connaitre l'avancement de ma reclamation"
    if "type de probleme" in text or "type de reclamation" in text:
        return "orienter correctement le traitement de ma demande"
    if "agent" in text and "reclamation" in text:
        return "traiter rapidement les demandes entrantes"
    if any(keyword in text for keyword in ("service interne", "services internes")):
        return "affecter les dossiers au bon service"
    if "responsable" in text and "reclamation" in text:
        return "piloter le traitement des reclamations"
    if any(keyword in text for keyword in ("soumission", "soumettre")) and "reclamation" in text:
        return "transmettre mon probleme au service concerne"

    rationale = requirement.get("rationale", "").strip()
    if rationale:
        cleaned = rationale
        prefixes = [
            "Cette exigence est essentielle pour ",
            "Cette exigence couvre le besoin principal de ",
            "Cette exigence couvre la possibilité pour ",
            "Cette exigence couvre la possibilite pour ",
            "Cette exigence couvre ",
            "Cette exigence permet de ",
        ]
        for prefix in prefixes:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix) :]
                break
        cleaned = cleaned.strip().rstrip(".")
        if _normalize_text(cleaned).startswith("les utilisateurs"):
            return "repondre au besoin utilisateur"
        if cleaned:
            return cleaned[0].lower() + cleaned[1:]
    return "atteindre l'objectif metier attendu"


def _story_connector(benefit: str) -> str:
    benefit = benefit.strip().rstrip(".")
    if not benefit:
        return "afin de produire de la valeur metier"
    if benefit[0].lower() in {"a", "e", "i", "o", "u", "y"}:
        return f"afin d'{benefit}"
    return f"afin de {benefit}"


def _role_clause(role: str) -> str:
    role = role.strip()
    if not role:
        return "En tant qu'utilisateur"
    if role[0].lower() in {"a", "e", "i", "o", "u", "y"}:
        return f"En tant qu'{role}"
    return f"En tant que {role}"


def _fallback_acceptance_criterion(requirement: dict, ac_id: str, user_story_id: str) -> dict:
    action = _action_from_requirement(requirement)
    return {
        "id": ac_id,
        "user_story_id": user_story_id,
        "given": "un utilisateur autorise et connecte",
        "when": f"il veut {action}",
        "then": "le systeme execute l'action et affiche un resultat clair",
    }


def build_agile_artifacts_from_requirements(state: SharedState) -> dict:
    """Construit un backlog minimal et tracable sans appel LLM."""
    requirements = state.get("requirements", [])
    sorted_requirements = sorted(
        requirements,
        key=lambda req: (PRIORITY_ORDER.get(req.get("priority", "Should"), 2), req.get("id", "")),
    )

    theme_to_epic: dict[str, dict] = {}
    epics: list[dict] = []
    features: list[dict] = []
    user_stories: list[dict] = []
    backlog: list[dict] = []
    traceability: list[dict] = []
    ac_counter = 1

    for requirement in sorted_requirements:
        theme = _theme_for_requirement(requirement)
        if theme not in theme_to_epic:
            epic_id = f"EPIC-{len(epics) + 1:02d}"
            epic = {
                "id": epic_id,
                "title": theme,
                "description": f"Regroupe les exigences liees a {theme.lower()}.",
                "requirement_ids": [],
                "priority": _priority(requirement),
            }
            theme_to_epic[theme] = epic
            epics.append(epic)

        epic = theme_to_epic[theme]
        requirement_id = requirement.get("id", f"REQ-{len(features) + 1:03d}")
        epic["requirement_ids"].append(requirement_id)

        feature_id = f"FEAT-{len(features) + 1:02d}"
        feature = {
            "id": feature_id,
            "epic_id": epic["id"],
            "title": requirement.get("title", f"Feature {len(features) + 1}"),
            "description": requirement.get("description", ""),
            "requirement_ids": [requirement_id],
            "priority": _priority(requirement),
        }
        features.append(feature)

        user_story_id = f"US-{len(user_stories) + 1:03d}"
        role = _role_for_requirement(requirement, state)
        action = _action_from_requirement(requirement)
        benefit = _benefit_from_requirement(requirement)
        benefit_clause = _story_connector(benefit)
        role_clause = _role_clause(role)
        ac_id = f"AC-{ac_counter:03d}"
        ac_counter += 1
        ac = _fallback_acceptance_criterion(requirement, ac_id, user_story_id)

        story = {
            "id": user_story_id,
            "epic_id": epic["id"],
            "feature_id": feature_id,
            "requirement_ids": [requirement_id],
            "role": role,
            "story": f"{role_clause}, je veux {action}, {benefit_clause}.",
            "priority": _priority(requirement),
            "story_points": _estimate_story_points(requirement),
            "acceptance_criteria": [ac],
        }
        user_stories.append(story)

        backlog.append(
            {
                "rank": len(backlog) + 1,
                "item_id": user_story_id,
                "title": requirement.get("title", f"User story {len(backlog) + 1}"),
                "priority": story["priority"],
                "story_points": story["story_points"],
                "epic_id": epic["id"],
                "feature_id": feature_id,
                "requirement_ids": [requirement_id],
            }
        )

        traceability.append(
            {
                "requirement_id": requirement_id,
                "epic_id": epic["id"],
                "feature_id": feature_id,
                "user_story_ids": [user_story_id],
                "acceptance_criteria_ids": [ac_id],
            }
        )

    return {
        "epics": epics,
        "features": features,
        "user_stories": user_stories,
        "backlog": backlog,
        "traceability_matrix": traceability,
    }


def _apply_artifacts(state: SharedState, artifacts: dict) -> SharedState:
    state["epics"] = artifacts.get("epics", []) or []
    state["features"] = artifacts.get("features", []) or []
    state["user_stories"] = artifacts.get("user_stories", []) or []
    state["backlog"] = artifacts.get("backlog", []) or []
    state["traceability_matrix"] = artifacts.get("traceability_matrix", []) or []
    return state


def agile_artifact_generator(state: SharedState) -> SharedState:
    requirements = state.get("requirements", [])
    if not requirements:
        state["errors"].append("agile_artifact_generator : requirements absents.")
        return state

    context = {
        "extracted_info": state.get("extracted_info"),
        "consolidated_data": state.get("consolidated_data"),
    }
    user_message = (
        "Transforme ces requirements en artefacts agiles :\n\n"
        f"{json.dumps(requirements, ensure_ascii=False, indent=2)}\n\n"
        "Contexte Agent 1 / Agent 2 :\n\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )

    if not _env_flag("AGENT3_USE_LLM", default=True):
        return _apply_artifacts(state, build_agile_artifacts_from_requirements(state))

    prompt = augment_prompt(SYSTEM_PROMPT_AGILE_GENERATOR, "agent3_agile_generator")

    try:
        artifacts = call_llm_json(prompt, user_message)
        if not isinstance(artifacts, dict) or not artifacts.get("user_stories"):
            raise ValueError("La reponse Agent 3 doit etre un objet JSON Agile complet.")
    except (ValueError, RuntimeError) as e:
        artifacts = build_agile_artifacts_from_requirements(state)
        if not artifacts.get("user_stories"):
            state["errors"].append(f"agile_artifact_generator : {e}")

    return _apply_artifacts(state, artifacts)
