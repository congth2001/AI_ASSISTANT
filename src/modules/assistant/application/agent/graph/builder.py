from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Any

from src.modules.assistant.application.agent.graph.state import AgentState
from src.modules.assistant.application.agent.graph.nodes import (
    make_analyze_query_node,
    make_prepare_conversation_node,
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
from src.modules.assistant.application.agent.graph.edges import (
    route_after_analysis,
    route_after_request_assessment,
    route_after_context_evaluation,
    route_after_response_evaluation,
)
from src.modules.assistant.application.services.intent_classifier import IntentClassifier
from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.application.services.query_contextualizer import QueryContextualizer
from src.modules.assistant.application.agent.tools.text_to_sql_tool import TextToSQLTool
from src.modules.assistant.application.agent.tools.rag_tool import RAGTool
from src.modules.assistant.domain.ports.i_llm_service import ILLMService
from src.modules.assistant.domain.errors import (
    LLMServiceRequiredError,
)


def build_agent_graph(
    classifier: IntentClassifier,
    query_analyzer: QueryAnalyzer,
    contextualizer: QueryContextualizer,
    text_to_sql_tool: TextToSQLTool,
    rag_tool: RAGTool,
    llm_service: ILLMService,
    checkpointer: Any = None,
):
    """Compile the full agent graph.

    assess_request -> clarify or analyze_query
    analyze_query -> conversation | text_to_sql | rag | hybrid
    tool node -> evaluate_context -> respond or clarify
    generate_response -> evaluate_response -> retry or END

    Successful empty SQL results are authoritative. SQL failures produce an
    explicit tool error; document retrieval does not replace failed analytics.
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
    """Build the same routing and tool pipeline without response generation.

    After evaluate_context, return context to the caller for token streaming,
    or return the prepared clarification/tool error without another LLM call.
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
    graph.add_node("prepare_conversation", make_prepare_conversation_node())
    graph.add_node("execute_text_to_sql",  make_execute_text_to_sql_node(text_to_sql_tool, query_analyzer, contextualizer))
    graph.add_node("execute_rag",          make_execute_rag_node(rag_tool, query_analyzer, contextualizer))
    graph.add_node("execute_hybrid",       make_execute_hybrid_node(text_to_sql_tool, rag_tool, query_analyzer, contextualizer))
    graph.add_node("evaluate_context",      make_evaluate_context_node())
    graph.add_node("replan",                make_replan_node())
    terminal = END
    if include_response:
        if llm_service is None:
            raise LLMServiceRequiredError()
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
            "conversation": "prepare_conversation",
        },
    )
    graph.add_edge("prepare_conversation", "evaluate_context")
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
        {
            "text_to_sql": "execute_text_to_sql",
            "rag": "execute_rag",
            "hybrid": "execute_hybrid",
            "conversation": "prepare_conversation",
        },
    )
    if include_response:
        graph.add_edge("generate_response", "evaluate_response")
        graph.add_conditional_edges(
            "evaluate_response",
            route_after_response_evaluation,
            {"retry": "generate_response", "done": END},
        )

    return graph.compile(checkpointer=checkpointer or MemorySaver())
