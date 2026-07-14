"""
core/tracing.py
---------------
Trace explicable des decisions des agents.
Ce n'est pas une chaine de pensee brute: c'est un journal lisible
des observations, decisions et justifications utiles au debug.
"""

from core.state import SharedState


def add_trace(
    state: SharedState,
    agent: str,
    step: str,
    observation: str,
    decision: str,
    rationale: str = "",
) -> SharedState:
    state.setdefault("agent_trace", [])
    state["agent_trace"].append(
        {
            "agent": agent,
            "step": step,
            "observation": observation,
            "decision": decision,
            "rationale": rationale,
        }
    )
    return state


def print_trace(state: SharedState) -> None:
    trace = state.get("agent_trace", [])
    if not trace:
        return

    print("\n=== TRACE DE RAISONNEMENT EXPLICABLE ===")
    for index, item in enumerate(trace, 1):
        print(f"{index}. [{item.get('agent')}] {item.get('step')}")
        print(f"   Observation : {item.get('observation')}")
        print(f"   Decision    : {item.get('decision')}")
        if item.get("rationale"):
            print(f"   Pourquoi    : {item.get('rationale')}")
