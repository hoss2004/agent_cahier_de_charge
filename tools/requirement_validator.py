"""
tools/requirement_validator.py
------------------------------
Agent 2 tool: normalise et valide la liste des requirements.
"""

from core.state import SharedState


ALLOWED_TYPES = {
    "functional",
    "non_functional",
    "business_rule",
    "business",
    "data",
    "security",
    "reporting",
    "integration",
    "ui_ux",
    "constraint",
}
ALLOWED_PRIORITIES = {"Must", "Should", "Could", "Won't"}


def requirement_validator(state: SharedState) -> SharedState:
    if state.get("a2a_feedback"):
        return state

    normalized = []
    for index, requirement in enumerate(state.get("requirements", []), 1):
        req_type = requirement.get("type", "functional")
        priority = requirement.get("priority", "Should")

        if req_type == "business":
            req_type = "business_rule"
        if req_type not in ALLOWED_TYPES:
            req_type = "functional"
        if priority not in ALLOWED_PRIORITIES:
            priority = "Should"

        description = requirement.get("description", "").strip()
        if not description:
            description = requirement.get("title", "Requirement a preciser").strip()
        lowered_description = description.lower()
        already_starts_with_requirement = lowered_description.startswith(
            ("le systeme doit", "le système doit")
        )
        if description and not already_starts_with_requirement:
            description = f"Le systeme doit {description[0].lower() + description[1:]}"

        normalized.append(
            {
                "id": f"REQ-{index:03d}",
                "title": requirement.get("title", f"Requirement {index}").strip(),
                "description": description,
                "type": req_type,
                "priority": priority,
                "source": requirement.get("source", "SharedState Agent 1").strip(),
                "rationale": requirement.get("rationale", "").strip(),
                "acceptance_criteria": requirement.get("acceptance_criteria", []) or [],
            }
        )

    state["requirements"] = normalized

    if not normalized:
        state["errors"].append("requirement_validator : aucun requirement valide genere.")
    return state
