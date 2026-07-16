from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Any

from src.application.agent.graph.state import AgentState
from src.application.agent.graph.nodes import (
    make_analyze_query_node,
    make_execute_text_to_sql_node,
    make_execute_rag_node,
    make_execute_hybrid_node,
    make_generate_response_node,
    make_assess_request_node,
    make_clarification_node,
    make_evaluate_context_node,
    make_replan_node,
    make_evaluate_response_node,
)
from src.application.agent.graph.edges import (
    route_after_analysis,
    route_after_request_assessment,
    route_after_context_evaluation,
    route_after_response_evaluation,
)
from src.application.services.intent_classifier import IntentClassifier
from src.application.services.query_analyzer import QueryAnalyzer
from src.application.services.query_contextualizer import QueryContextualizer
from src.application.agent.tools.text_to_sql import TextToSQLTool
from src.application.agent.tools.rag_tool import RAGTool
from src.domain.interfaces.i_llm_service import ILLMService


def build_agent_graph(
    classifier: IntentClassifier,
    query_analyzer: QueryAnalyzer,
    contextualizer: QueryContextualizer,
    text_to_sql_tool: TextToSQLTool,
    rag_tool: RAGTool,
    llm_service: ILLMService,
    checkpointer: Any = None,
):
    """Compile and return the agent StateGraph.

    Graph topology:
        analyze_query (IntentClassifier — routing only)
            ├─[text_to_sql]──► execute_text_to_sql ──[has_data]──► generate_response
            │     (QueryAnalyzer runs here)         └─[no data]──► execute_rag ──►┐
            ├─[rag]──────────► execute_rag ──────────────────────────────────────►┤
            │     (QueryAnalyzer runs here)                                       │
            └─[hybrid]───────► execute_hybrid (SQL + RAG merged) ────────────────►┤
                  (QueryAnalyzer runs here, shared)                               ▼
                                                                        generate_response → END
    """
    return _build_graph(
        classifier, query_analyzer, contextualizer, text_to_sql_tool,
        rag_tool, llm_service=llm_service, include_response=True, checkpointer=checkpointer,
    )


def build_context_graph(
    classifier: IntentClassifier,
    query_analyzer: QueryAnalyzer,
    contextualizer: QueryContextualizer,
    text_to_sql_tool: TextToSQLTool,
    rag_tool: RAGTool,
    checkpointer: Any = None,
):
    """Context-only graph: same routing and tool execution as build_agent_graph,
    but stops after the tool nodes (no generate_response call).
    Used by the streaming path so the LLM response can be streamed separately.

    Graph topology:
        analyze_query
            ├─[text_to_sql]──► execute_text_to_sql ──[has_data]──► END
            │                                        └─[no data]──► execute_rag → END
            ├─[rag]──────────► execute_rag → END
            └─[hybrid]───────► execute_hybrid → END
    """
    return _build_graph(
        classifier, query_analyzer, contextualizer, text_to_sql_tool,
        rag_tool, llm_service=None, include_response=False, checkpointer=checkpointer,
    )


def _build_graph(
    classifier: IntentClassifier,
    query_analyzer: QueryAnalyzer,
    contextualizer: QueryContextualizer,
    text_to_sql_tool: TextToSQLTool,
    rag_tool: RAGTool,
    *,
    llm_service: ILLMService | None,
    include_response: bool,
    checkpointer: Any = None,
):
    """Single topology factory shared by regular and streaming execution."""
    graph = StateGraph(AgentState)

    graph.add_node("assess_request",      make_assess_request_node())
    graph.add_node("request_clarification", make_clarification_node())
    graph.add_node("analyze_query",       make_analyze_query_node(classifier, query_analyzer))
    graph.add_node("execute_text_to_sql",  make_execute_text_to_sql_node(text_to_sql_tool, query_analyzer, contextualizer))
    graph.add_node("execute_rag",          make_execute_rag_node(rag_tool, query_analyzer, contextualizer))
    graph.add_node("execute_hybrid",       make_execute_hybrid_node(text_to_sql_tool, rag_tool, query_analyzer, contextualizer))
    graph.add_node("evaluate_context",      make_evaluate_context_node())
    graph.add_node("replan",                make_replan_node())
    terminal = END
    if include_response:
        if llm_service is None:
            raise ValueError("llm_service is required when include_response=True")
        graph.add_node("generate_response", make_generate_response_node(llm_service))
        graph.add_node("evaluate_response", make_evaluate_response_node())
        terminal = "generate_response"

    graph.set_entry_point("assess_request")

    graph.add_conditional_edges(
        "assess_request",
        route_after_request_assessment,
        {"continue": "analyze_query", "clarify": "request_clarification"},
    )
    graph.add_edge("request_clarification", END)

    graph.add_conditional_edges(
        "analyze_query",
        route_after_analysis,
        {
            "text_to_sql": "execute_text_to_sql",
            "rag":         "execute_rag",
            "hybrid":      "execute_hybrid",
        },
    )
    graph.add_edge("execute_text_to_sql", "evaluate_context")
    graph.add_edge("execute_rag", "evaluate_context")
    graph.add_edge("execute_hybrid", "evaluate_context")
    graph.add_conditional_edges(
        "evaluate_context",
        route_after_context_evaluation,
        {"respond": terminal, "replan": "replan", "clarify": "request_clarification"},
    )
    graph.add_conditional_edges(
        "replan",
        route_after_analysis,
        {"text_to_sql": "execute_text_to_sql", "rag": "execute_rag", "hybrid": "execute_hybrid"},
    )
    if include_response:
        graph.add_edge("generate_response", "evaluate_response")
        graph.add_conditional_edges(
            "evaluate_response",
            route_after_response_evaluation,
            {"retry": "generate_response", "done": END},
        )

    return graph.compile(checkpointer=checkpointer or MemorySaver())
