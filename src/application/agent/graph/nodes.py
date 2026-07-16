import asyncio
import logging
import time
from typing import Awaitable, Callable

from src.application.agent.graph.state import AgentState
from src.application.agent.tools.text_to_sql import TextToSQLTool
from src.application.agent.tools.rag_tool import RAGTool
from src.application.services.intent_classifier import IntentClassifier
from src.application.services.query_analyzer import QueryAnalyzer
from src.application.services.query_contextualizer import QueryContextualizer
from src.domain.constants.search_config import SearchConfig
from src.domain.interfaces.i_llm_service import ILLMService
from src.application.agent.runtime import run_with_policy, node_metric

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
                "plan": [f"route:{route}", f"execute:{route}", "evaluate", "respond"],
                "iteration": state.get("iteration", 0) + 1,
            }
        return await _run_node(state, "analyze_query", operation, timeout_seconds=15)
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
            citations = [{"id": f"sql:{i + 1}", "type": "sql", "query": sql} for i, sql in enumerate(sql_queries)]
            context = {
            "retrieved_text": f"[sql:1]\n{result.content}" if result.content else "",
            "conversation_history": [
                {"role": m.role, "content": m.content}
                for m in reversed(state["messages"][:SearchConfig.HISTORY_WINDOW])
            ],
            "current_query": state["query"],
            "intent": analyzed.primary_intent.value,
            "has_data": result.has_data,
            "used_fallback": False,
            "fallback_warning": None,
            "sources": citations,
            }
            tool_call = {"tool": "text_to_sql", "success": result.success, "has_data": result.has_data, "error_code": result.error_code}
            return {
            "tool_name": "text_to_sql", "tool_result": result.content,
            "tool_success": result.success, "tool_error_code": result.error_code,
            "context": context, "analyzed": analyzed,
            "sql_query": sql_queries, "citations": citations,
            "tool_calls": [*state.get("tool_calls", []), tool_call],
            "attempted_routes": [*state.get("attempted_routes", []), "text_to_sql"],
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
            document_citations = [
                {"id": f"doc:{doc.get('doc_id')}", "type": "document", "doc_id": doc.get("doc_id"), "score": doc.get("score"), "metadata": doc.get("metadata", {})}
                for doc in context.get("retrieved_documents", [])
            ]
            citations = [*state.get("citations", []), *document_citations]
            context["sources"] = citations
            tool_call = {"tool": "rag", "success": result.success, "has_data": result.has_data, "error_code": result.error_code}
            return {
            "tool_name": "rag",
            "tool_result": result.content,
            "tool_success": result.success,
            "tool_error_code": result.error_code,
            "context": context,
            "analyzed": analyzed,
            "citations": citations,
            "tool_calls": [*state.get("tool_calls", []), tool_call],
            "attempted_routes": [*state.get("attempted_routes", []), "rag"],
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
            sql_text = f"[sql:1]\n{sql_result.content}" if sql_result.content else ""
            merged_text = "\n\n".join(filter(None, [sql_text, rag_result.content]))
            sql_queries = sql_result.metadata.get("sql_queries", [])
            citations = [{"id": f"sql:{i + 1}", "type": "sql", "query": sql} for i, sql in enumerate(sql_queries)]
            citations.extend({"id": f"doc:{doc.get('doc_id')}", "type": "document", "doc_id": doc.get("doc_id"), "score": doc.get("score"), "metadata": doc.get("metadata", {})} for doc in rag_context.get("retrieved_documents", []))

            context = {
            "retrieved_text": merged_text,
            "conversation_history": [
                {"role": m.role, "content": m.content}
                for m in reversed(state["messages"][:SearchConfig.HISTORY_WINDOW])
            ],
            "current_query": state["query"],
            "intent": analyzed.primary_intent.value,
            "has_data": sql_result.has_data or rag_result.has_data,
            "used_fallback": False,
            "fallback_warning": None,
            "sources": citations,
            "sql_context": {"queries": sql_queries, "result": sql_result.content},
            "rag_context": {"documents": rag_context.get("retrieved_documents", []), "result": rag_result.content},
            }
            calls = [
                {"tool": "text_to_sql", "success": sql_result.success, "has_data": sql_result.has_data, "error_code": sql_result.error_code},
                {"tool": "rag", "success": rag_result.success, "has_data": rag_result.has_data, "error_code": rag_result.error_code},
            ]
            return {
            "tool_name": "hybrid", "tool_result": merged_text,
            "tool_success": sql_result.success or rag_result.success,
            "tool_error_code": sql_result.error_code or rag_result.error_code,
            "context": context, "analyzed": analyzed,
            "sql_query": sql_queries, "citations": citations,
            "tool_calls": [*state.get("tool_calls", []), *calls],
            "attempted_routes": [*state.get("attempted_routes", []), "hybrid"],
            }
        return await _run_node(state, "execute_hybrid", operation, timeout_seconds=50)
    return node


def make_evaluate_context_node():
    async def node(state: AgentState) -> dict:
        async def operation():
            context = state.get("context") or {}
            if context.get("has_data"):
                return {"evaluation": {"decision": "respond", "reason": "grounded_context_available"}}

            attempted = state.get("attempted_routes", [])
            can_retry = state.get("iteration", 0) < state.get("max_iterations", 3)
            if can_retry and "text_to_sql" in attempted and "rag" not in attempted:
                return {
                    "evaluation": {"decision": "replan", "reason": "sql_returned_no_data"},
                    "route": "rag",
                    "iteration": state.get("iteration", 0) + 1,
                    "plan": [*state.get("plan", []), "fallback:rag", "evaluate"],
                }

            return {
                "evaluation": {"decision": "clarify", "reason": "insufficient_grounding"},
                "clarification_question": (
                    "Mình chưa tìm thấy dữ liệu phù hợp. Bạn có thể bổ sung phạm vi thời gian, "
                    "tên khách hàng, mặt hàng hoặc số phiếu cụ thể không?"
                ),
            }
        return await _run_node(state, "evaluate_context", operation, timeout_seconds=2)
    return node


def make_replan_node():
    async def node(state: AgentState) -> dict:
        async def operation():
            return {"route": state.get("route") or "rag"}
        return await _run_node(state, "replan", operation, timeout_seconds=2)
    return node


# ─────────────────────────────────────────────
# Response generation
# ─────────────────────────────────────────────

def make_generate_response_node(llm_service: ILLMService):
    async def node(state: AgentState) -> dict:
        async def operation():
            response = await llm_service.generate_response(state["query"], state["context"])
            return {"response": response, "response_attempts": state.get("response_attempts", 0) + 1}
        return await _run_node(state, "generate_response", operation, timeout_seconds=60, retries=1)
    return node


def make_evaluate_response_node():
    async def node(state: AgentState) -> dict:
        async def operation():
            response = (state.get("response") or "").strip()
            source_ids = [source.get("id") for source in state.get("citations", []) if source.get("id")]
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
