from src.modules.assistant.application.agent.graph.state import AgentState


def route_after_analysis(state: AgentState) -> str:
    """Read the pre-computed route from analyze_query node."""
    return state.get("route") or "rag"


def route_after_request_assessment(state: AgentState) -> str:
    return "clarify" if state.get("needs_clarification") else "continue"


def route_after_context_evaluation(state: AgentState) -> str:
    decision = (state.get("evaluation") or {}).get("decision")
    if decision in {"respond", "clarify"}:
        return decision
    return "clarify"


def route_after_response_evaluation(state: AgentState) -> str:
    return "retry" if (state.get("evaluation") or {}).get("decision") == "retry_response" else "done"
