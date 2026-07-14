"""
tools/requirement_generator.py
------------------------------
Agent 2 tool: genere les requirements structures.
"""

import json
import re

from core.knowledge_base import augment_prompt
from core.llm_client import call_llm_json
from core.state import SharedState
from prompts.prompt_validation import SYSTEM_PROMPT_REQUIREMENT_GENERATOR


PRIORITY_BY_TYPE = {
    "functional": "Must",
    "business_rule": "Should",
    "data": "Must",
    "security": "Should",
    "reporting": "Should",
    "integration": "Could",
    "ui_ux": "Should",
    "non_functional": "Should",
    "constraint": "Must",
}
PRIORITY_ORDER = {"Must": 1, "Should": 2, "Could": 3, "Won't": 4}
QUESTION_PREFIXES = (
    "quel ",
    "quelle ",
    "quels ",
    "quelles ",
    "qui ",
    "comment ",
    "pourquoi ",
    "avez-vous ",
    "pouvez-vous ",
    "faut-il ",
)


def _normalize_text(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = normalized.replace("à", "a").replace("â", "a")
    normalized = normalized.replace("é", "e").replace("è", "e").replace("ê", "e")
    normalized = normalized.replace("î", "i").replace("ï", "i")
    normalized = normalized.replace("ô", "o")
    normalized = normalized.replace("ù", "u").replace("û", "u")
    normalized = normalized.replace("ç", "c")
    normalized = normalized.replace("ã ", "a").replace("ã¢", "a")
    normalized = normalized.replace("ã©", "e").replace("ã¨", "e").replace("ãª", "e")
    normalized = normalized.replace("ã®", "i").replace("ã¯", "i")
    normalized = normalized.replace("ã´", "o")
    normalized = normalized.replace("ã¹", "u").replace("ã»", "u")
    normalized = normalized.replace("ã§", "c")
    return re.sub(r"\s+", " ", normalized)


def _is_question_like_title(title: str) -> bool:
    normalized = _normalize_text(title).strip()
    return normalized.endswith("?") or normalized.startswith(QUESTION_PREFIXES)


def _has_question_like_requirements(requirements: list[dict]) -> bool:
    return any(_is_question_like_title(req.get("title", "")) for req in requirements)


def _dedupe_requirements(requirements: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for requirement in requirements:
        title = _normalize_text(requirement.get("title", ""))
        description = _normalize_text(requirement.get("description", ""))
        key = (title, description)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(requirement)
    return deduped


def _make_requirement(
    title: str,
    description: str,
    req_type: str = "functional",
    priority: str | None = None,
    source: str = "SharedState",
    rationale: str = "",
) -> dict:
    return {
        "id": "",
        "title": title.strip(),
        "description": description.strip(),
        "type": req_type,
        "priority": priority or PRIORITY_BY_TYPE.get(req_type, "Should"),
        "source": source,
        "rationale": rationale.strip(),
        "acceptance_criteria": [],
    }


def _classify_from_text(text: str) -> str:
    normalized = _normalize_text(text)
    if any(word in normalized for word in ("statistique", "rapport", "dashboard", "tableau de bord", "indicateur")):
        return "reporting"
    if any(word in normalized for word in ("securite", "authentification", "connexion", "mot de passe", "role", "permission")):
        return "security"
    if any(word in normalized for word in ("donnee", "champ", "historique", "piece jointe", "document")):
        return "data"
    if any(word in normalized for word in ("notification", "email", "sms", "alerte")):
        return "functional"
    if any(word in normalized for word in ("regle", "statut", "validation", "priorite", "delai")):
        return "business_rule"
    return "functional"


def _description_for_feature(feature: str) -> str:
    cleaned = str(feature or "").strip().rstrip(".")
    if not cleaned:
        cleaned = "gerer la fonctionnalite demandee"
    return f"Le systeme doit permettre de {cleaned[0].lower() + cleaned[1:]}."


def build_requirements_from_consolidated(consolidated: dict) -> list[dict]:
    """Fallback deterministe quand le LLM renvoie un JSON invalide ou tronque."""
    extracted = consolidated.get("extracted_info") or {}
    raw_input = consolidated.get("raw_input", "")
    clarifications = consolidated.get("clarifications", []) or []
    requirements: list[dict] = []

    combined_text = " ".join(
        [raw_input]
        + [str(item.get("question", "")) for item in clarifications]
        + [str(item.get("answer", "")) for item in clarifications]
    )
    normalized = _normalize_text(combined_text)

    features = extracted.get("fonctionnalites_identifiees", []) or []
    if "reclamation" not in normalized:
        for feature in features[:5]:
            if _is_question_like_title(str(feature)):
                continue
            req_type = _classify_from_text(feature)
            requirements.append(
                _make_requirement(
                    title=str(feature).strip().capitalize(),
                    description=_description_for_feature(str(feature)),
                    req_type=req_type,
                    source="demande_initiale",
                    rationale="Fonctionnalite identifiee dans la demande client.",
                )
            )

    if "reclamation" in normalized:
        requirements.append(
            _make_requirement(
                title="Soumettre une reclamation",
                description="Le systeme doit permettre au client de soumettre une reclamation avec les informations necessaires au traitement.",
                req_type="functional",
                priority="Must",
                source="demande_initiale",
                rationale="La creation de reclamations est le besoin central du projet.",
            )
        )
        requirements.append(
            _make_requirement(
                title="Suivre le statut d'une reclamation",
                description="Le systeme doit permettre au client de consulter le statut et l'historique de ses reclamations.",
                req_type="functional",
                priority="Must",
                source="demande_initiale",
                rationale="Le suivi donne de la visibilite au client sur le traitement.",
            )
        )
        requirements.append(
            _make_requirement(
                title="Traiter et affecter les reclamations",
                description="Le systeme doit permettre aux agents autorises de traiter les reclamations et de les affecter aux services internes concernes.",
                req_type="functional",
                priority="Must",
                source="demande_initiale",
                rationale="Le service client doit organiser le traitement des reclamations.",
            )
        )

    if any(word in normalized for word in ("statistique", "rapport", "dashboard", "temps moyen", "frequente")):
        requirements.append(
            _make_requirement(
                title="Consulter les statistiques des reclamations",
                description="Le systeme doit afficher les reclamations les plus frequentes et le temps moyen de traitement.",
                req_type="reporting",
                priority="Should",
                source="demande_initiale",
                rationale="Les statistiques aident l'entreprise a piloter la qualite du service.",
            )
        )

    if any(word in normalized for word in ("notification", "email", "sms", "alerte", "reponse")):
        requirements.append(
            _make_requirement(
                title="Notifier les utilisateurs",
                description="Le systeme doit notifier les utilisateurs concernes lors des changements importants de statut ou des reponses.",
                req_type="functional",
                priority="Should",
                source="clarifications",
                rationale="Les notifications reduisent le besoin de verification manuelle.",
            )
        )

    if any(word in normalized for word in ("connexion", "authentification", "mot de passe", "role", "permission", "admin")):
        requirements.append(
            _make_requirement(
                title="Gerer les acces par role",
                description="Le systeme doit limiter les actions disponibles selon le role de l'utilisateur.",
                req_type="security",
                priority="Must",
                source="clarifications",
                rationale="La separation des droits protege les donnees et les actions sensibles.",
            )
        )

    if any(word in normalized for word in ("categorie", "catégorie", "priorite", "priorité", "type de reclamation")):
        requirements.append(
            _make_requirement(
                title="Classer les reclamations par categorie et priorite",
                description="Le systeme doit permettre de classer chaque reclamation par categorie, priorite, service responsable, statut et delai de traitement.",
                req_type="data",
                priority="Must",
                source="clarifications",
                rationale="Les categories et priorites structurent le traitement des reclamations.",
            )
        )

    if any(word in normalized for word in ("nouvelle", "en cours", "resolue", "rejetee", "cloturee", "en retard", "clôturée")):
        requirements.append(
            _make_requirement(
                title="Gerer le cycle de vie des reclamations",
                description="Le systeme doit gerer les statuts nouvelle, en cours de traitement, resolue, rejetee, cloturee et en retard.",
                req_type="business_rule",
                priority="Must",
                source="clarifications",
                rationale="Les statuts permettent de suivre clairement l'avancement du dossier.",
            )
        )

    if any(word in normalized for word in ("delai", "délai", "24", "48", "jours ouvrables", "retard")):
        requirements.append(
            _make_requirement(
                title="Suivre les delais de traitement",
                description="Le systeme doit suivre les delais de traitement prevus par type de reclamation et signaler les dossiers en retard.",
                req_type="business_rule",
                priority="Should",
                source="clarifications",
                rationale="Le suivi des delais aide a respecter les engagements de service.",
            )
        )

    if any(word in normalized for word in ("piece jointe", "pièce jointe", "document", "preuve")):
        requirements.append(
            _make_requirement(
                title="Ajouter des pieces jointes aux reclamations",
                description="Le systeme doit permettre au client d'ajouter des pieces jointes ou documents justificatifs a une reclamation.",
                req_type="data",
                priority="Should",
                source="clarifications",
                rationale="Les documents facilitent l'analyse et le traitement des reclamations.",
            )
        )

    if any(word in normalized for word in ("information complementaire", "informations complementaires", "dossier incomplet")):
        requirements.append(
            _make_requirement(
                title="Demander des informations complementaires",
                description="Le systeme doit permettre a l'agent de demander des informations complementaires au client lorsque le dossier est incomplet.",
                req_type="functional",
                priority="Should",
                source="clarifications",
                rationale="Les demandes complementaires permettent de completer les dossiers avant traitement.",
            )
        )

    if any(word in normalized for word in ("service interne", "service financier", "logistique", "service technique", "sav", "apres-vente")):
        requirements.append(
            _make_requirement(
                title="Configurer les services internes responsables",
                description="Le systeme doit permettre de configurer les services internes responsables du traitement des reclamations.",
                req_type="data",
                priority="Should",
                source="clarifications",
                rationale="La configuration des services facilite l'affectation des dossiers.",
            )
        )

    if any(word in normalized for word in ("satisfaction", "taux de resolution", "taux de rejet", "kpi", "indicateur")):
        requirements.append(
            _make_requirement(
                title="Mesurer les indicateurs de performance du service client",
                description="Le systeme doit calculer les indicateurs de performance tels que volume, statuts, temps moyen, taux de resolution, taux de rejet et satisfaction client.",
                req_type="reporting",
                priority="Should",
                source="clarifications",
                rationale="Les indicateurs permettent de piloter et ameliorer la qualite du service client.",
            )
        )

    fallback = sorted(
        _dedupe_requirements(requirements),
        key=lambda req: (PRIORITY_ORDER.get(req.get("priority", "Should"), 2), req.get("title", "")),
    )
    return fallback[:10]


def requirement_generator(state: SharedState) -> SharedState:
    if state.get("a2a_feedback"):
        return state

    consolidated = state.get("consolidated_data")
    if not consolidated:
        state["errors"].append("requirement_generator : consolidated_data absent.")
        return state

    user_message = (
        "Genere les requirements a partir de ces informations consolidees :\n\n"
        f"{json.dumps(consolidated, ensure_ascii=False, indent=2)}"
    )

    try:
        prompt = augment_prompt(
            SYSTEM_PROMPT_REQUIREMENT_GENERATOR,
            "agent2_requirement_generator",
        )
        requirements = call_llm_json(prompt, user_message)
        if not isinstance(requirements, list):
            raise ValueError("La reponse requirements doit etre un tableau JSON.")
        parsed_requirements = [req for req in requirements if isinstance(req, dict)]
        if not parsed_requirements:
            raise ValueError("La reponse requirements ne contient aucun objet requirement.")
        if _has_question_like_requirements(parsed_requirements):
            raise ValueError("La reponse requirements contient des questions au lieu d'exigences.")
        state["requirements"] = parsed_requirements
    except (ValueError, RuntimeError) as e:
        fallback_requirements = build_requirements_from_consolidated(consolidated)
        if fallback_requirements:
            state["requirements"] = fallback_requirements
        else:
            state["errors"].append(f"requirement_generator : {e}")

    return state
