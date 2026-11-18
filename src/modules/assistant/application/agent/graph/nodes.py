import asyncio
import logging
import time
from typing import Awaitable, Callable

from src.modules.assistant.application.agent.graph.state import AgentState
from src.modules.assistant.application.agent.tools.text_to_sql_tool import TextToSQLTool
from src.modules.assistant.application.agent.tools.rag_tool import RAGTool
from src.modules.assistant.application.agent.tools.tool_result import ToolResult
from src.modules.assistant.application.services.intent_classifier import IntentClassifier
from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.application.services.query_contextualizer import QueryContextualizer
from src.modules.assistant.domain.constants.search_config import SearchConfig
from src.modules.assistant.domain.ports.i_llm_service import ILLMService
from src.modules.assistant.application.agent.runtime import run_with_policy, node_metric
from src.modules.assistant.domain.errors import (
    DocumentRetrievalFailedError,
    SQLGenerationFailedError, SQLPlanValidationFailedError, SQLExecutionFailedError,
)

_SQL_TOOL_ERRORS = (SQLGenerationFailedError, SQLPlanValidationFailedError, SQLExecutionFailedError)


def _tool_error_message(error_code: str | None, *, tool_name: str | None) -> str:
    """User-facing message for a failed data tool; never exposes internals."""
    sql_error = next((error for error in _SQL_TOOL_ERRORS if error.code == error_code), None)
    if sql_error is not None:
        return sql_error().message + " Vui lòng thử lại sau."
    if tool_name == "text_to_sql":
        return SQLExecutionFailedError().message + " Vui lòng thử lại sau."
    return DocumentRetrievalFailedError().message + " Vui lòng thử lại sau."


def _tool_error_evaluation(context: dict, reason: str, message: str) -> dict:
    return {
        "evaluation": {"decision": "respond", "reason": reason},
        "context": {**context, "response_mode": "tool_error"},
        "response": message,
    }

logger = logging.getLogger(__name__)


async def _run_node(
    state: AgentState,
    name: str,
    operation: Callable[[], Awaitable[dict]],
    *,
    timeout_seconds: float,
    retries: int = 0,
) -> dict:
    started = time.perf_counter()
    try:
        updates = await run_with_policy(
            operation, name=name, timeout_seconds=timeout_seconds, retries=retries
        )
        metric = node_metric(name, started, True)
        logger.info("Agent node completed", extra={"trace_id": state.get("trace_id"), **metric})
        updates["node_metrics"] = [*state.get("node_metrics", []), metric]
        return updates
    except Exception as exc:
        metric = node_metric(name, started, False, type(exc).__name__)
        logger.exception("Agent node failed", extra={"trace_id": state.get("trace_id"), **metric})
        raise


# ─────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────

def _conversation_history(state: AgentState) -> list[dict]:
    """Recent turns oldest-first (the repository returns newest-first)."""
    return [
        {"role": message.role, "content": message.content}
        for message in reversed(state["messages"][:SearchConfig.HISTORY_WINDOW])
    ]


def _sql_citations(sql_queries: list[str]) -> list[dict]:
    return [
        {"id": f"sql:{index + 1}", "type": "sql", "query": sql}
        for index, sql in enumerate(sql_queries)
    ]


def _document_citations(documents: list[dict]) -> list[dict]:
    return [
        {
            "id": f"doc:{doc.get('doc_id')}",
            "type": "document",
            "doc_id": doc.get("doc_id"),
            "score": doc.get("score"),
            "metadata": doc.get("metadata", {}),
        }
        for doc in documents
    ]


def _tool_call(name: str, result: ToolResult) -> dict:
    return {
        "tool": name,
        "success": result.success,
        "has_data": result.has_data,
        "error_code": result.error_code,
    }


def _data_context(
    state: AgentState,
    *,
    retrieved_text: str,
    intent: str,
    has_data: bool,
    citations: list[dict],
    **extra,
) -> dict:
    """Context dict consumed by the LLM for SQL/hybrid nodes."""
    return {
        "retrieved_text": retrieved_text,
        "conversation_history": _conversation_history(state),
        "current_query": state["query"],
        "intent": intent,
        "has_data": has_data,
        "used_fallback": False,
        "fallback_warning": None,
        "sources": citations,
        **extra,
    }


# ─────────────────────────────────────────────
# Layer 1 — routing
# ─────────────────────────────────────────────

def make_assess_request_node():
    async def node(state: AgentState) -> dict:
        async def operation():
            query = state["query"].strip()
            ambiguous = {"cái đó", "việc đó", "thế nào", "còn nó", "như thế nào"}
            needs_clarification = not query or (
                query.lower() in ambiguous and not state["messages"]
            )
            question = None
            if needs_clarification:
                question = (
                    "Bạn có thể nói rõ dữ liệu hoặc vấn đề muốn phân tích không? "
                    "Ví dụ: doanh thu theo thời gian, công nợ khách hàng, hoặc mặt hàng cần tìm."
                )
            return {
                "needs_clarification": needs_clarification,
                "clarification_question": question,
            }
        return await _run_node(state, "assess_request", operation, timeout_seconds=2)
    return node


def make_clarification_node():
    async def node(state: AgentState) -> dict:
        async def operation():
            question = state.get("clarification_question") or (
                "Mình chưa tìm thấy đủ dữ liệu để trả lời chính xác. "
                "Bạn có thể bổ sung thời gian, khách hàng, mặt hàng hoặc chỉ số cần phân tích không?"
            )
            return {
                "needs_clarification": True,
                "clarification_question": question,
                "response": question,
            }
        return await _run_node(state, "request_clarification", operation, timeout_seconds=2)
    return node

def make_analyze_query_node(classifier: IntentClassifier, query_analyzer: QueryAnalyzer):
    """Lightweight routing only — no entity extraction."""
    async def node(state: AgentState) -> dict:
        async def operation():
            await query_analyzer.ensure_fresh()
            route = await classifier.classify(state["query"])
            return {
                "route": route,
            }
        return await _run_node(state, "analyze_query", operation, timeout_seconds=15)
    return node


def make_prepare_conversation_node():
    """Prepare a direct conversational response without querying SQL or RAG."""
    async def node(state: AgentState) -> dict:
        async def operation():
            context = {
                "conversation_history": _conversation_history(state),
                "current_query": state["query"],
                "intent": "conversation",
                "has_data": True,
                "used_fallback": False,
                "fallback_warning": None,
                "sources": [],
                "response_mode": "conversation",
            }
            return {
                "context": context,
                "tool_name": None,
                "tool_success": True,
                "tool_error_code": None,
            }

        return await _run_node(
            state,
            "prepare_conversation",
            operation,
            timeout_seconds=2,
        )

    return node


# ─────────────────────────────────────────────
# Layer 2 — execution
# Full QueryAnalyzer runs here, not at routing level.
# ─────────────────────────────────────────────

def make_execute_text_to_sql_node(
    tool: TextToSQLTool,
    query_analyzer: QueryAnalyzer,
    contextualizer: QueryContextualizer,
):
    async def node(state: AgentState) -> dict:
        async def operation():
            resolved = await contextualizer.resolve(state["query"], state["messages"])
            analyzed = query_analyzer.analyze(resolved)
            result = await tool.run(analyzed=analyzed)
            sql_queries = result.metadata.get("sql_queries", [])
            citations = _sql_citations(sql_queries)
            context = _data_context(
                state,
                retrieved_text=result.content,
                intent=analyzed.primary_intent.value,
                has_data=result.has_data,
                citations=citations,
            )
            return {
                "tool_name": "text_to_sql",
                "tool_result": result.content,
                "tool_success": result.success,
                "tool_error_code": result.error_code,
                "context": context,
                "analyzed": analyzed,
                "sql_query": sql_queries,
                "citations": citations,
                "tool_calls": [*state.get("tool_calls", []), _tool_call("text_to_sql", result)],
            }
        return await _run_node(state, "execute_text_to_sql", operation, timeout_seconds=45)
    return node


def make_execute_rag_node(
    tool: RAGTool,
    query_analyzer: QueryAnalyzer,
    contextualizer: QueryContextualizer,
):
    async def node(state: AgentState) -> dict:
        async def operation():
            if state.get("analyzed"):
                analyzed = state["analyzed"]
            else:
                resolved = await contextualizer.resolve(state["query"], state["messages"])
                analyzed = query_analyzer.analyze(resolved)
            result = await tool.run(
                analyzed=analyzed,
                messages=state["messages"],
                current_query=state["query"],
            )
            context = result.metadata["context"]
            citations = [
                *state.get("citations", []),
                *_document_citations(context.get("retrieved_documents", [])),
            ]
            context["sources"] = citations
            return {
                "tool_name": "rag",
                "tool_result": result.content,
                "tool_success": result.success,
                "tool_error_code": result.error_code,
                "context": context,
                "analyzed": analyzed,
                "citations": citations,
                "tool_calls": [*state.get("tool_calls", []), _tool_call("rag", result)],
            }
        return await _run_node(state, "execute_rag", operation, timeout_seconds=30, retries=1)
    return node


def make_execute_hybrid_node(
    sql_tool: TextToSQLTool,
    rag_tool: RAGTool,
    query_analyzer: QueryAnalyzer,
    contextualizer: QueryContextualizer,
):
    async def node(state: AgentState) -> dict:
        async def operation():
            resolved = await contextualizer.resolve(state["query"], state["messages"])
            analyzed = query_analyzer.analyze(resolved)

            sql_result, rag_result = await asyncio.gather(
                sql_tool.run(analyzed=analyzed),
                rag_tool.run(
                    analyzed=analyzed,
                    messages=state["messages"],
                    current_query=state["query"],
                ),
            )
            rag_context = rag_result.metadata["context"]
            rag_documents = rag_context.get("retrieved_documents", [])
            merged_text = "\n\n".join(filter(None, [sql_result.content, rag_result.content]))
            sql_queries = sql_result.metadata.get("sql_queries", [])
            citations = [*_sql_citations(sql_queries), *_document_citations(rag_documents)]
            context = _data_context(
                state,
                retrieved_text=merged_text,
                intent=analyzed.primary_intent.value,
                has_data=sql_result.has_data or rag_result.has_data,
                citations=citations,
                sql_context={"queries": sql_queries, "result": sql_result.content},
                rag_context={"documents": rag_documents, "result": rag_result.content},
            )
            if rag_result.error_code and rag_context.get("fallback_warning"):
                # SQL data can still answer; tell the LLM documents were unavailable
                # (adapters read retrieved_text, not fallback_warning).
                context["fallback_warning"] = rag_context["fallback_warning"]
                warning = f"Lưu ý: {rag_context['fallback_warning']}"
                context["retrieved_text"] = "\n\n".join(filter(None, [merged_text, warning]))
            calls = [_tool_call("text_to_sql", sql_result), _tool_call("rag", rag_result)]
            return {
                "tool_name": "hybrid",
                "tool_result": merged_text,
                "tool_success": sql_result.success or rag_result.success,
                "tool_error_code": sql_result.error_code or rag_result.error_code,
                "context": context,
                "analyzed": analyzed,
                "sql_query": sql_queries,
                "citations": citations,
                "tool_calls": [*state.get("tool_calls", []), *calls],
            }
        return await _run_node(state, "execute_hybrid", operation, timeout_seconds=50)
    return node


def make_evaluate_context_node():
    async def node(state: AgentState) -> dict:
        async def operation():
            context = state.get("context") or {}
            if context.get("has_data"):
                return {"evaluation": {"decision": "respond", "reason": "grounded_context_available"}}

            if (
                state.get("tool_name") == "text_to_sql"
                and state.get("tool_success")
            ):
                return {
                    "evaluation": {
                        "decision": "respond",
                        "reason": "sql_completed_without_matching_rows",
                    }
                }
            tool_name = state.get("tool_name")
            error_code = state.get("tool_error_code")
            if tool_name == "text_to_sql" and not state.get("tool_success"):
                return _tool_error_evaluation(
                    context, "sql_tool_failed", _tool_error_message(error_code, tool_name=tool_name)
                )
            # A failed vector search must not read as "no matching documents":
            # report the outage instead of asking the user to clarify.
            if tool_name in ("rag", "hybrid") and error_code:
                return _tool_error_evaluation(
                    context, f"{tool_name}_tool_failed", _tool_error_message(error_code, tool_name=tool_name)
                )

            return {
                "evaluation": {"decision": "clarify", "reason": "insufficient_grounding"},
                "clarification_question": (
                    "Mình chưa tìm thấy dữ liệu phù hợp. Bạn có thể bổ sung phạm vi thời gian, "
                    "tên khách hàng, mặt hàng hoặc số phiếu cụ thể không?"
                ),
            }
        return await _run_node(state, "evaluate_context", operation, timeout_seconds=2)
    return node


# ─────────────────────────────────────────────
# Response generation
# ─────────────────────────────────────────────

def make_generate_response_node(llm_service: ILLMService):
    async def node(state: AgentState) -> dict:
        async def operation():
            if (state.get("context") or {}).get("response_mode") == "tool_error":
                return {"response": state["response"], "response_attempts": 1}
            response = await llm_service.generate_response(state["query"], state["context"])
            return {"response": response, "response_attempts": state.get("response_attempts", 0) + 1}
        return await _run_node(state, "generate_response", operation, timeout_seconds=60, retries=1)
    return node


def make_evaluate_response_node():
    async def node(state: AgentState) -> dict:
        async def operation():
            response = (state.get("response") or "").strip()
            source_ids = [
                source.get("id") for source in state.get("citations", [])
                if source.get("id") and (state.get("context") or {}).get("response_mode") != "tool_error"
            ]
            missing_citation = bool(source_ids) and not any(f"[{source_id}]" in response for source_id in source_ids)
            if (not response or missing_citation) and state.get("response_attempts", 0) < 2:
                context = dict(state.get("context") or {})
                context["verification_feedback"] = (
                    "Câu trả lời trước thiếu nội dung hoặc citation hợp lệ. "
                    "Hãy tạo lại và dùng ít nhất một source ID được cung cấp."
                )
                return {
                    "evaluation": {"decision": "retry_response", "reason": "missing_grounding_or_content"},
                    "context": context,
                }
            return {
                "evaluation": {
                    "decision": "done",
                    "reason": "response_verified" if response and not missing_citation else "retry_budget_exhausted",
                    "citation_verified": not missing_citation,
                }
            }
        return await _run_node(state, "evaluate_response", operation, timeout_seconds=2)
    return node
