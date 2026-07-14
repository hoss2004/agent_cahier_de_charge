"""
tools/agile_artifact_validator.py
---------------------------------
Agent 3 tool: normalise les artefacts agiles et garantit la tracabilite.
"""

from __future__ import annotations

from core.state import SharedState
from tools.agile_artifact_generator import build_agile_artifacts_from_requirements


ALLOWED_PRIORITIES = {"Must", "Should", "Could", "Won't"}
PRIORITY_ORDER = {"Must": 1, "Should": 2, "Could": 3, "Won't": 4}
ALLOWED_STORY_POINTS = {1, 2, 3, 5, 8, 13}


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _priority(value: str | None) -> str:
    return value if value in ALLOWED_PRIORITIES else "Should"


def _story_points(value) -> int:
    try:
        points = int(value)
    except (TypeError, ValueError):
        return 3
    if points in ALLOWED_STORY_POINTS:
        return points
    if points <= 1:
        return 1
    if points <= 2:
        return 2
    if points <= 3:
        return 3
    if points <= 5:
        return 5
    if points <= 8:
        return 8
    return 13


def _text(value, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _normalize_requirement_ids(value, valid_req_ids: set[str]) -> list[str]:
    ids = [
        str(item).strip()
        for item in _as_list(value)
        if isinstance(item, (str, int)) and str(item).strip()
    ]
    if valid_req_ids:
        ids = [item for item in ids if item in valid_req_ids]
    return list(dict.fromkeys(ids))


def _default_acceptance_criterion(user_story_id: str, story_title: str) -> dict:
    return {
        "id": "",
        "user_story_id": user_story_id,
        "given": "un utilisateur autorise et connecte",
        "when": f"il realise l'action de la user story {story_title}",
        "then": "le systeme affiche un resultat clair et enregistre les donnees necessaires",
    }


def _normalize_epics(epics: list[dict]) -> tuple[list[dict], dict[str, str]]:
    normalized = []
    id_map = {}
    for index, epic in enumerate(epics, 1):
        if not isinstance(epic, dict):
            continue
        old_id = _text(epic.get("id"), f"EPIC-{index:02d}")
        new_id = f"EPIC-{len(normalized) + 1:02d}"
        id_map[old_id] = new_id
        normalized.append(
            {
                "id": new_id,
                "title": _text(epic.get("title"), f"Epic {len(normalized) + 1}"),
                "description": _text(epic.get("description"), ""),
                "requirement_ids": _as_list(epic.get("requirement_ids")),
                "priority": _priority(epic.get("priority")),
            }
        )
    return normalized, id_map


def _normalize_features(
    features: list[dict],
    epic_id_map: dict[str, str],
    default_epic_id: str,
) -> tuple[list[dict], dict[str, str]]:
    normalized = []
    id_map = {}
    for index, feature in enumerate(features, 1):
        if not isinstance(feature, dict):
            continue
        old_id = _text(feature.get("id"), f"FEAT-{index:02d}")
        new_id = f"FEAT-{len(normalized) + 1:02d}"
        id_map[old_id] = new_id
        old_epic_id = _text(feature.get("epic_id"), default_epic_id)
        normalized.append(
            {
                "id": new_id,
                "epic_id": epic_id_map.get(old_epic_id, old_epic_id if old_epic_id else default_epic_id),
                "title": _text(feature.get("title"), f"Feature {len(normalized) + 1}"),
                "description": _text(feature.get("description"), ""),
                "requirement_ids": _as_list(feature.get("requirement_ids")),
                "priority": _priority(feature.get("priority")),
            }
        )
    return normalized, id_map


def agile_artifact_validator(state: SharedState) -> SharedState:
    if not state.get("requirements"):
        state["errors"].append("agile_artifact_validator : requirements absents.")
        return state

    if not state.get("user_stories"):
        artifacts = build_agile_artifacts_from_requirements(state)
        state["epics"] = artifacts["epics"]
        state["features"] = artifacts["features"]
        state["user_stories"] = artifacts["user_stories"]
        state["backlog"] = artifacts["backlog"]
        state["traceability_matrix"] = artifacts["traceability_matrix"]

    valid_req_ids = {req.get("id") for req in state.get("requirements", []) if req.get("id")}

    epics, epic_id_map = _normalize_epics(state.get("epics", []))
    if not epics:
        epics = [
            {
                "id": "EPIC-01",
                "title": "Fonctionnalites principales",
                "description": "Regroupe les exigences principales du MVP.",
                "requirement_ids": list(valid_req_ids),
                "priority": "Must",
            }
        ]
        epic_id_map["EPIC-01"] = "EPIC-01"

    features, feature_id_map = _normalize_features(
        state.get("features", []),
        epic_id_map,
        epics[0]["id"],
    )
    if not features:
        features = [
            {
                "id": "FEAT-01",
                "epic_id": epics[0]["id"],
                "title": "Fonctionnalites MVP",
                "description": "Regroupe les user stories initiales.",
                "requirement_ids": list(valid_req_ids),
                "priority": "Must",
            }
        ]
        feature_id_map["FEAT-01"] = "FEAT-01"

    normalized_stories = []
    acceptance_criteria = []
    ac_counter = 1

    for story_index, story in enumerate(state.get("user_stories", []), 1):
        if not isinstance(story, dict):
            continue

        old_epic_id = _text(story.get("epic_id"), epics[0]["id"])
        old_feature_id = _text(story.get("feature_id"), features[0]["id"])
        user_story_id = f"US-{len(normalized_stories) + 1:03d}"
        story_text = _text(
            story.get("story"),
            f"En tant que utilisateur, je veux realiser la fonctionnalite {story_index}, afin de produire de la valeur metier.",
        )
        req_ids = _normalize_requirement_ids(story.get("requirement_ids"), valid_req_ids)

        normalized_ac = []
        for raw_ac in _as_list(story.get("acceptance_criteria")):
            if isinstance(raw_ac, str):
                raw_ac = {
                    "given": "un contexte valide",
                    "when": raw_ac,
                    "then": "le resultat attendu est observable",
                }
            if not isinstance(raw_ac, dict):
                continue
            ac_id = f"AC-{ac_counter:03d}"
            ac_counter += 1
            ac = {
                "id": ac_id,
                "user_story_id": user_story_id,
                "given": _text(raw_ac.get("given"), "un contexte valide"),
                "when": _text(raw_ac.get("when"), "une action est realisee"),
                "then": _text(raw_ac.get("then"), "un resultat observable se produit"),
            }
            normalized_ac.append(ac)
            acceptance_criteria.append(ac)

        if not normalized_ac:
            ac = _default_acceptance_criterion(user_story_id, story_text)
            ac["id"] = f"AC-{ac_counter:03d}"
            ac_counter += 1
            normalized_ac.append(ac)
            acceptance_criteria.append(ac)

        normalized_stories.append(
            {
                "id": user_story_id,
                "epic_id": epic_id_map.get(old_epic_id, old_epic_id),
                "feature_id": feature_id_map.get(old_feature_id, old_feature_id),
                "requirement_ids": req_ids,
                "role": _text(story.get("role"), "utilisateur"),
                "story": story_text,
                "priority": _priority(story.get("priority")),
                "story_points": _story_points(story.get("story_points")),
                "acceptance_criteria": normalized_ac,
            }
        )

    state["epics"] = epics
    state["features"] = features
    state["user_stories"] = normalized_stories
    state["acceptance_criteria"] = acceptance_criteria

    sorted_stories = sorted(
        normalized_stories,
        key=lambda item: (PRIORITY_ORDER.get(item["priority"], 2), item["id"]),
    )
    state["backlog"] = [
        {
            "rank": index,
            "item_id": story["id"],
            "title": story["story"],
            "priority": story["priority"],
            "story_points": story["story_points"],
            "epic_id": story["epic_id"],
            "feature_id": story["feature_id"],
            "requirement_ids": story["requirement_ids"],
        }
        for index, story in enumerate(sorted_stories, 1)
    ]

    traceability = []
    for requirement_id in sorted(valid_req_ids):
        linked_stories = [
            story
            for story in normalized_stories
            if requirement_id in story.get("requirement_ids", [])
        ]
        if not linked_stories:
            continue

        ac_ids = []
        for story in linked_stories:
            ac_ids.extend(ac["id"] for ac in story.get("acceptance_criteria", []))

        traceability.append(
            {
                "requirement_id": requirement_id,
                "epic_id": linked_stories[0]["epic_id"],
                "feature_id": linked_stories[0]["feature_id"],
                "user_story_ids": [story["id"] for story in linked_stories],
                "acceptance_criteria_ids": list(dict.fromkeys(ac_ids)),
            }
        )

    state["traceability_matrix"] = traceability

    if not state["user_stories"]:
        state["errors"].append("agile_artifact_validator : aucune user story valide generee.")

    return state
