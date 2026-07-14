"""
tools/answer_consolidator.py
----------------------------
Agent 2 tool: consolide extracted_info + questions/reponses humaines.
"""

from core.state import SharedState


def answer_consolidator(state: SharedState) -> SharedState:
    questions = state.get("clarification_questions", [])
    answers = state.get("stakeholder_answers", [])

    clarifications = []
    for index, question in enumerate(questions):
        answer = answers[index] if index < len(answers) else "Non renseigne"
        clarifications.append(
            {
                "id": f"Q{index + 1}",
                "question": question,
                "answer": answer,
            }
        )

    state["consolidated_data"] = {
        "raw_input": state.get("raw_input", ""),
        "extracted_info": state.get("extracted_info"),
        "clarifications": clarifications,
    }
    return state
