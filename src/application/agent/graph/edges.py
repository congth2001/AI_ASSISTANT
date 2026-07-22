from src.application.agent.graph.state import AgentState


def route_after_analysis(state: AgentState) -> str:
    """Read the pre-computed route from analyze_query node."""
    return state.get("route") or "rag"


def route_after_text_to_sql(state: AgentState) -> str:
    """A successful SQL query is authoritative even when it returns no rows."""
    context = state.get("context") or {}
    if context.get("has_data", False) or state.get("tool_success"):
        return "generate_response"
    return "rag"


def route_after_request_assessment(state: AgentState) -> str:
    return "clarify" if state.get("needs_clarification") else "continue"


def route_after_context_evaluation(state: AgentState) -> str:
    decision = (state.get("evaluation") or {}).get("decision")
    if decision in {"respond", "replan", "clarify"}:
        return decision
    return "clarify"


def route_after_response_evaluation(state: AgentState) -> str:
    return "retry" if (state.get("evaluation") or {}).get("decision") == "retry_response" else "done"
