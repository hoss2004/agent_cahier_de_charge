"""
exporters/cahier_des_charges_exporter.py
----------------------------------------
Exporte le SharedState final en cahier des charges Markdown et PDF.
"""

from __future__ import annotations

import re
import textwrap
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import fitz

from core.state import SharedState


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 50
BODY_SIZE = 10.5
TITLE_SIZE = 18
HEADING_SIZE = 14
LINE_HEIGHT = 14


def _clean_filename(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.strip())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", ascii_text.lower())
    return cleaned.strip("_")[:60] or "cahier_des_charges"


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _line(label: str, value) -> str:
    if value in (None, "", []):
        value = "Non renseigne"
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value) or "Non renseigne"
    return f"- **{label}** : {value}"


def _as_text(value) -> str:
    if value in (None, "", []):
        return "Non renseigne"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "Non renseigne"
    return str(value)


def _norm(text: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def _contains_any(text: str, keywords: list[str]) -> bool:
    normalized = _norm(text)
    return any(keyword in normalized for keyword in keywords)


def _unique(items: list[object]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for item in items:
        text = str(item or "").strip()
        key = _norm(text)
        if text and key not in seen:
            seen.add(key)
            results.append(text)
    return results


def _all_project_text(state: SharedState) -> str:
    parts: list[str] = [state.get("raw_input", "")]
    extracted = state.get("extracted_info") or {}
    parts.extend(
        [
            extracted.get("domaine", ""),
            extracted.get("type_projet", ""),
            extracted.get("objectif_principal", ""),
            " ".join(_as_list(extracted.get("acteurs"))),
            " ".join(_as_list(extracted.get("fonctionnalites_identifiees"))),
        ]
    )
    for req in state.get("requirements", []):
        parts.extend(
            [
                req.get("title", ""),
                req.get("description", ""),
                req.get("rationale", ""),
                req.get("type", ""),
            ]
        )
    for story in state.get("user_stories", []):
        parts.append(story.get("story", ""))
    return " ".join(parts)


def _project_title(state: SharedState, extracted: dict) -> str:
    objective = str(extracted.get("objectif_principal") or "").strip().rstrip(".")
    if objective:
        return objective[:110]
    raw_input = str(state.get("raw_input") or "").strip().rstrip(".")
    if raw_input:
        return raw_input[:110]
    return "Projet logiciel"


def _clarification_pairs(state: SharedState) -> list[tuple[str, str]]:
    questions = state.get("clarification_questions", [])
    answers = state.get("stakeholder_answers", [])
    pairs: list[tuple[str, str]] = []
    for index, question in enumerate(questions):
        answer = answers[index] if index < len(answers) else "Non renseigne"
        pairs.append((str(question), str(answer)))
    return pairs


def _requirements_by_type(requirements: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for req in requirements:
        grouped[str(req.get("type") or "unspecified")].append(req)
    return dict(grouped)


def _display_requirement_type(raw_type: str) -> str:
    labels = {
        "functional": "Fonctionnel",
        "non_functional": "Non fonctionnel",
        "business_rule": "Regle metier",
        "reporting": "Reporting / statistiques",
        "data": "Donnees",
        "security": "Securite",
        "integration": "Integration",
        "unspecified": "Non classe",
    }
    return labels.get(_norm(raw_type), raw_type.replace("_", " ").title())


def _actor_responsibility(actor: str, project_text: str) -> str:
    actor_norm = _norm(actor)
    if "agent" in actor_norm or "service client" in actor_norm:
        return "traite les demandes, qualifie les dossiers et communique avec les utilisateurs."
    if any(word in actor_norm for word in ["client", "utilisateur", "user"]):
        return "utilise la solution, cree des demandes ou consulte les informations qui le concernent."
    if any(word in actor_norm for word in ["admin", "administrateur"]):
        return "configure la plateforme, gere les utilisateurs, les roles et les parametres."
    if any(word in actor_norm for word in ["manager", "responsable", "rh"]):
        return "supervise le processus, valide les decisions et consulte les indicateurs."
    if "artisan" in actor_norm:
        return "publie ses produits ou evenements et suit son activite sur la plateforme."
    if _contains_any(project_text, ["reclamation"]) and "service" in actor_norm:
        return "recoit les reclamations affectees et participe a leur resolution."
    return "intervient dans le processus metier selon les droits qui lui sont attribues."


def _actor_lines(state: SharedState, extracted: dict) -> list[str]:
    actors = _unique(_as_list(extracted.get("acteurs")))
    for story in state.get("user_stories", []):
        match = re.search(r"En tant qu(?:e|')\s*([^,]+)", str(story.get("story", "")), re.I)
        if match:
            actors.append(match.group(1).strip())
    actors = _unique(actors)

    if not actors:
        return ["- Parties prenantes a confirmer avec le stakeholder."]

    project_text = _all_project_text(state)
    return [
        f"- **{actor}** : {_actor_responsibility(actor, project_text)}"
        for actor in actors
    ]


def _technical_specs(state: SharedState, extracted: dict) -> list[str]:
    project_text = _all_project_text(state)
    actors = _as_list(extracted.get("acteurs"))
    solution_type = extracted.get("type_projet") or "solution logicielle"
    specs = [
        f"- **Type de solution** : {solution_type}.",
        "- **Architecture applicative** : application structuree autour d'une interface utilisateur, d'une couche metier et d'une couche de persistance des donnees.",
    ]

    if actors:
        specs.append(
            "- **Gestion des roles** : controle d'acces par profil utilisateur "
            f"({', '.join(str(actor) for actor in actors)})."
        )
    else:
        specs.append("- **Gestion des roles** : profils utilisateurs a confirmer.")

    if _contains_any(project_text, ["reclamation"]):
        specs.append(
            "- **Donnees principales** : clients, reclamations, categories, priorites, statuts, services internes, pieces jointes, reponses et indicateurs."
        )
    elif _contains_any(project_text, ["conge", "absence"]):
        specs.append(
            "- **Donnees principales** : employes, demandes d'absence, soldes, validations, notifications et historique."
        )
    elif _contains_any(project_text, ["artisan", "commerce", "paiement", "evenement"]):
        specs.append(
            "- **Donnees principales** : artisans, produits, commandes, paiements, evenements, reservations et contenus culturels."
        )
    else:
        specs.append(
            "- **Donnees principales** : entites metier deduites des requirements et a confirmer pendant la conception."
        )

    if _contains_any(project_text, ["notification", "email", "mail"]):
        specs.append("- **Notifications** : mecanisme d'alerte a prevoir selon les evenements metier.")
    if _contains_any(project_text, ["paiement", "carte bancaire", "payant"]):
        specs.append("- **Paiement** : integration d'un service de paiement securise a confirmer.")
    if _contains_any(project_text, ["piece jointe", "document", "pdf", "image", "fichier"]):
        specs.append("- **Fichiers** : stockage et consultation de pieces jointes avec controle d'acces.")
    if _contains_any(project_text, ["statistique", "dashboard", "indicateur", "temps moyen"]):
        specs.append("- **Reporting** : tableaux de bord avec indicateurs, filtres et donnees agregees.")

    specs.extend(
        [
            "- **Securite** : authentification, autorisation par role, protection des donnees et journalisation des actions sensibles.",
            "- **Qualite attendue** : exigences tracables, testables et reliees aux user stories via la matrice REQ -> US -> AC.",
        ]
    )
    return specs


def _constraint_lines(state: SharedState) -> list[str]:
    project_text = _all_project_text(state)
    validation = (state.get("consolidated_data") or {}).get("agent2_validation") or {}
    constraints = [
        "- **Perimetre MVP** : prioriser les exigences Must avant les exigences Should/Could.",
        "- **Validation metier** : les regles de gestion doivent etre confirmees par le stakeholder avant developpement.",
        "- **Confidentialite** : les donnees utilisateurs et les donnees metier doivent etre protegees selon les droits d'acces.",
    ]

    if validation.get("missing_information"):
        constraints.append(
            "- **Points ouverts** : certaines informations restent a confirmer avant figement complet du perimetre."
        )
    if _contains_any(project_text, ["paiement", "carte bancaire"]):
        constraints.append("- **Paiement** : respect des contraintes de securite liees aux transactions.")
    if _contains_any(project_text, ["piece jointe", "document", "image", "pdf"]):
        constraints.append("- **Documents** : taille, format et duree de conservation des fichiers a definir.")
    if _contains_any(project_text, ["statistique", "temps moyen", "indicateur"]):
        constraints.append("- **Indicateurs** : les statistiques doivent etre calculees sur des donnees fiables et historisees.")

    constraints.append("- **Technologies et budget** : choix techniques, hebergement et budget a valider avec l'equipe projet.")
    return constraints


def _deliverable_lines(state: SharedState) -> list[str]:
    deliverables = [
        "- Cahier des charges fonctionnel et technique au format Markdown et PDF.",
        "- Liste structuree des requirements avec IDs REQ, types et priorites.",
        "- Backlog agile initial avec epics, features, user stories et story points.",
        "- Criteres d'acceptation au format Given / When / Then.",
        "- Matrice de tracabilite REQ -> US -> AC.",
        "- Rapport de clarification humaine et decisions A2A entre agents.",
        "- Jeu initial de cas d'usage de test pour la recette fonctionnelle.",
    ]
    if state.get("requirements"):
        deliverables.append("- Base exploitable pour la conception technique et la planification sprint.")
    return deliverables


def _planning_lines(state: SharedState) -> list[str]:
    backlog = state.get("backlog", [])
    total_points = sum(int(item.get("story_points", 0) or 0) for item in backlog)
    backlog_size = len(backlog) or len(state.get("requirements", []))
    dev_weeks = 2 if backlog_size <= 6 else 3 if backlog_size <= 12 else 4 if backlog_size <= 20 else 6
    test_weeks = 1 if backlog_size <= 10 else 2

    return [
        "- **Phase 1 - Cadrage et validation** : 1 semaine pour valider le cahier des charges, le perimetre MVP et les questions ouvertes.",
        "- **Phase 2 - Conception fonctionnelle et technique** : 1 semaine pour definir les ecrans, donnees, roles, workflows et architecture.",
        f"- **Phase 3 - Developpement MVP** : environ {dev_weeks} semaine(s), a ajuster selon l'equipe et la velocite.",
        f"- **Phase 4 - Tests et recette** : environ {test_weeks} semaine(s) pour verifier les cas d'usage, corrections et validation stakeholder.",
        "- **Phase 5 - Deploiement et accompagnement** : 1 semaine pour mise en production, formation et documentation.",
        f"- **Charge agile indicative** : {backlog_size} item(s) backlog, {total_points or 'story points a confirmer'} point(s) estime(s).",
    ]


def _test_use_case_lines(state: SharedState) -> list[str]:
    stories = state.get("user_stories", [])
    if stories:
        lines = []
        for index, story in enumerate(stories[:12], 1):
            story_text = story.get("story") or story.get("title") or "User story a verifier"
            lines.append(f"- **CU-{index:03d} / {story.get('id', 'US-XXX')}** : {story_text}")
            acceptance_criteria = story.get("acceptance_criteria", [])
            if acceptance_criteria:
                ac = acceptance_criteria[0]
                lines.append(f"  - Given {ac.get('given', 'contexte valide')}")
                lines.append(f"  - When {ac.get('when', 'action utilisateur')}")
                lines.append(f"  - Then {ac.get('then', 'resultat attendu')}")
        return lines

    requirements = state.get("requirements", [])
    if requirements:
        return [
            f"- **CU-{index:03d} / {req.get('id', 'REQ-XXX')}** : verifier que {str(req.get('title', 'le requirement')).lower()} fonctionne selon sa description."
            for index, req in enumerate(requirements[:12], 1)
        ]
    return ["- Cas d'usage de test a generer apres production des user stories."]


def _risk_lines(state: SharedState) -> list[str]:
    project_text = _all_project_text(state)
    risks = [
        "- **Risque de perimetre flou** : certaines decisions metier peuvent changer apres validation. Mitigation : conserver la boucle A2A et tracer les reponses stakeholder.",
        "- **Risque d'adoption utilisateur** : les acteurs peuvent ne pas utiliser correctement la plateforme. Mitigation : prevoir ergonomie simple, formation et feedback utilisateur.",
        "- **Risque de qualite des donnees** : donnees incompletes ou mal classees. Mitigation : formulaires controles, champs obligatoires et regles de validation.",
        "- **Risque de securite** : acces non autorise a des donnees sensibles. Mitigation : authentification, roles et journalisation.",
    ]
    if _contains_any(project_text, ["paiement", "carte bancaire"]):
        risks.append("- **Risque paiement** : integration ou transaction echouee. Mitigation : prestataire fiable, tests de paiement et gestion des erreurs.")
    if _contains_any(project_text, ["statistique", "dashboard", "indicateur", "temps moyen"]):
        risks.append("- **Risque reporting** : indicateurs inexacts si les statuts ou dates ne sont pas bien historises. Mitigation : modele de donnees auditable.")
    if _contains_any(project_text, ["notification", "email"]):
        risks.append("- **Risque notification** : messages non recus ou trop nombreux. Mitigation : suivi d'envoi, preferences et templates valides.")
    return risks


def _evolution_lines(state: SharedState) -> list[str]:
    project_text = _all_project_text(state)
    evolutions = [
        "- Amelioration des tableaux de bord et exports decisionnels.",
        "- Application mobile ou interface responsive avancee.",
        "- Automatisation de certaines decisions metier apres validation humaine.",
        "- Integration avec des outils externes de l'organisation.",
    ]
    if _contains_any(project_text, ["reclamation"]):
        evolutions.extend(
            [
                "- Classification automatique des reclamations par theme et priorite.",
                "- Mesure de satisfaction apres cloture d'une reclamation.",
                "- Integration CRM ou centre de support.",
            ]
        )
    elif _contains_any(project_text, ["artisan", "patrimoine", "commerce"]):
        evolutions.extend(
            [
                "- Recommandations de produits artisanaux et mise en avant du patrimoine.",
                "- Gestion avancee des evenements, reservations et ateliers.",
                "- Version multilingue pour toucher un public international.",
            ]
        )
    elif _contains_any(project_text, ["conge", "absence"]):
        evolutions.extend(
            [
                "- Integration calendrier et paie.",
                "- Regles avancees de soldes et workflows multi-niveaux.",
            ]
        )
    return evolutions


def _agent_trace_lines(state: SharedState) -> list[str]:
    traces = state.get("agent_trace", [])
    if not traces:
        return ["- Aucun journal operationnel disponible."]

    lines = []
    for index, trace in enumerate(traces, 1):
        lines.append(
            f"- **Trace {index} - {trace.get('agent', 'Agent')}** : "
            f"{trace.get('step', 'etape non renseignee')}"
        )
        if trace.get("observation"):
            lines.append(f"  - Observation : {trace.get('observation')}")
        if trace.get("decision"):
            lines.append(f"  - Decision : {trace.get('decision')}")
        if trace.get("rationale"):
            lines.append(f"  - Justification : {trace.get('rationale')}")
    return lines


def build_cahier_markdown(state: SharedState) -> str:
    extracted = state.get("extracted_info") or {}
    requirements = state.get("requirements", [])
    validation = (state.get("consolidated_data") or {}).get("agent2_validation") or {}
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    project_title = _project_title(state, extracted)
    grouped_requirements = _requirements_by_type(requirements)

    lines: list[str] = [
        f"# Cahier des charges - {project_title}",
        "",
        f"Genere le : {generated_at}",
        "",
        "## 1. Presentation generale du projet",
        _line("Nom / resume du projet", project_title),
        _line("Domaine metier", extracted.get("domaine")),
        _line("Type de projet", extracted.get("type_projet")),
        _line("Objectif principal", extracted.get("objectif_principal")),
        _line("Acteurs identifies", extracted.get("acteurs", [])),
        "",
        "### Demande client initiale",
        state.get("raw_input", "Non renseigne"),
        "",
        "## 2. Description des besoins",
        "### Besoin principal",
        extracted.get("objectif_principal") or "Besoin principal a confirmer.",
        "",
        "### Fonctionnalites identifiees",
    ]

    features = _as_list(extracted.get("fonctionnalites_identifiees"))
    if features:
        lines.extend(f"- {feature}" for feature in features)
    else:
        lines.append("- Fonctionnalites a consolider depuis les requirements.")

    lines.extend(["", "### Clarifications stakeholder"])
    pairs = _clarification_pairs(state)
    if pairs:
        for index, (question, answer) in enumerate(pairs, 1):
            lines.append(f"- **Q{index}.** {question}")
            lines.append(f"  **R{index}.** {answer}")
    else:
        lines.append("- Aucune clarification humaine enregistree.")

    lines.extend(["", "### Synthese de suffisance Agent 2"])
    if validation:
        lines.append(_line("Informations suffisantes", validation.get("is_sufficient")))
        lines.append(_line("Niveau de confiance", validation.get("confidence")))
        lines.append(_line("Informations manquantes", validation.get("missing_information", [])))
        lines.append(_line("Ambiguites", validation.get("ambiguities", [])))
        lines.append(_line("Contradictions", validation.get("contradictions", [])))
    else:
        lines.append("- Validation Agent 2 non disponible.")

    lines.extend(["", "## 3. Parties prenantes"])
    lines.extend(_actor_lines(state, extracted))

    lines.extend(["", "## 4. Specifications techniques"])
    lines.extend(_technical_specs(state, extracted))

    lines.extend(["", "## 5. Contraintes du projet"])
    lines.extend(_constraint_lines(state))

    lines.extend(["", "## 6. Livrables attendus"])
    lines.extend(_deliverable_lines(state))

    lines.extend(["", "## 7. Planning previsionnel"])
    lines.extend(_planning_lines(state))

    lines.extend(["", "## 8. Cas d'usage de test"])
    lines.extend(_test_use_case_lines(state))

    lines.extend(["", "## 9. Risques du projet"])
    lines.extend(_risk_lines(state))

    lines.extend(["", "## 10. Perspectives d'evolution"])
    lines.extend(_evolution_lines(state))

    lines.extend(["", "## 11. Requirements detailles"])
    if requirements:
        for raw_type, reqs in grouped_requirements.items():
            lines.append(f"### {_display_requirement_type(raw_type)}")
            for req in reqs:
                lines.append(
                    f"- **{req.get('id')}** [{req.get('priority')}] {req.get('title')}"
                )
                lines.append(f"  - Description : {req.get('description')}")
                if req.get("rationale"):
                    lines.append(f"  - Justification : {req.get('rationale')}")
                if req.get("source"):
                    lines.append(f"  - Source : {req.get('source')}")
    else:
        lines.append("- Aucun requirement genere.")

    lines.extend(["", "## 12. Epics et features"])
    epics = state.get("epics", [])
    features_state = state.get("features", [])
    if epics:
        for epic in epics:
            lines.append(
                f"- **{epic.get('id')}** [{epic.get('priority')}] {epic.get('title')} "
                f"(REQ: {', '.join(epic.get('requirement_ids', []))})"
            )
            if epic.get("description"):
                lines.append(f"  - {epic.get('description')}")
            related_features = [
                feature for feature in features_state if feature.get("epic_id") == epic.get("id")
            ]
            for feature in related_features:
                lines.append(
                    f"  - **{feature.get('id')}** [{feature.get('priority')}] "
                    f"{feature.get('title')}"
                )
    else:
        lines.append("- Aucun epic genere.")

    lines.extend(["", "## 13. User stories et criteres d'acceptation"])
    user_stories = state.get("user_stories", [])
    if user_stories:
        for story in user_stories:
            lines.append(
                f"- **{story.get('id')}** [{story.get('priority')} | "
                f"{story.get('story_points')} pts] {story.get('story')}"
            )
            lines.append(f"  - Epic : {story.get('epic_id')} | Feature : {story.get('feature_id')}")
            lines.append(f"  - Requirements : {', '.join(story.get('requirement_ids', []))}")
            for ac in story.get("acceptance_criteria", []):
                lines.append(f"  - **{ac.get('id')}**")
                lines.append(f"    - Given {ac.get('given')}")
                lines.append(f"    - When {ac.get('when')}")
                lines.append(f"    - Then {ac.get('then')}")
    else:
        lines.append("- Aucune user story generee.")

    lines.extend(["", "## 14. Backlog initial"])
    backlog = state.get("backlog", [])
    if backlog:
        for item in backlog:
            lines.append(
                f"{item.get('rank')}. **{item.get('item_id')}** "
                f"[{item.get('priority')} | {item.get('story_points')} pts] "
                f"{item.get('title')}"
            )
    else:
        lines.append("- Aucun item backlog genere.")

    lines.extend(["", "## 15. Matrice de tracabilite"])
    traceability = state.get("traceability_matrix", [])
    if traceability:
        for row in traceability:
            lines.append(
                f"- **{row.get('requirement_id')}** -> "
                f"{', '.join(row.get('user_story_ids', []))} -> "
                f"{', '.join(row.get('acceptance_criteria_ids', []))}"
            )
    else:
        lines.append("- Aucune tracabilite generee.")

    lines.extend(["", "## 16. Journal operationnel des agents"])
    lines.extend(_agent_trace_lines(state))

    lines.extend(["", "## 17. Notes techniques"])
    if state.get("errors"):
        for error in state["errors"]:
            lines.append(f"- {error}")
    else:
        lines.append("- Aucune erreur technique signalee.")

    return "\n".join(lines).strip() + "\n"


def _markdown_to_pdf(markdown: str, pdf_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = MARGIN

    def ensure_space(required: float = LINE_HEIGHT) -> None:
        nonlocal page, y
        if y + required > PAGE_HEIGHT - MARGIN:
            page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            y = MARGIN

    def write_text(text: str, size: float = BODY_SIZE, bold: bool = False, indent: int = 0) -> None:
        nonlocal y
        font = "helv"
        prefix = ""
        clean = text.strip()
        if clean.startswith("# "):
            clean = clean[2:].strip()
            size = TITLE_SIZE
            bold = True
        elif clean.startswith("## "):
            clean = clean[3:].strip()
            size = HEADING_SIZE
            bold = True
        elif clean.startswith("### "):
            clean = clean[4:].strip()
            size = BODY_SIZE + 1
            bold = True
        elif clean.startswith("- "):
            indent += 10
            clean = "- " + text.strip()[2:].strip()

        clean = re.sub(r"\*\*(.*?)\*\*", r"\1", clean)
        max_chars = max(45, int((PAGE_WIDTH - 2 * MARGIN - indent) / (size * 0.48)))
        wrapped = textwrap.wrap(clean, width=max_chars) or [""]

        for line in wrapped:
            ensure_space(LINE_HEIGHT)
            page.insert_text(
                (MARGIN + indent, y),
                prefix + line,
                fontsize=size,
                fontname=font,
                fill=(0, 0, 0),
            )
            y += LINE_HEIGHT if not bold else LINE_HEIGHT + 2

    for raw_line in markdown.splitlines():
        if not raw_line.strip():
            y += LINE_HEIGHT / 2
            continue
        indent = 12 if raw_line.startswith("  ") else 0
        write_text(raw_line, indent=indent)

    doc.save(pdf_path)
    doc.close()


def export_cahier_des_charges(
    state: SharedState,
    output_dir: str | Path = "outputs",
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    extracted = state.get("extracted_info") or {}
    base_name = _clean_filename(
        extracted.get("objectif_principal")
        or extracted.get("domaine")
        or state.get("raw_input", "")
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    markdown_path = output_path / f"{base_name}_{timestamp}.md"
    pdf_path = output_path / f"{base_name}_{timestamp}.pdf"

    markdown = build_cahier_markdown(state)
    markdown_path.write_text(markdown, encoding="utf-8")
    _markdown_to_pdf(markdown, pdf_path)

    return {
        "markdown": str(markdown_path.resolve()),
        "pdf": str(pdf_path.resolve()),
    }
