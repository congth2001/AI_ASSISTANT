"""Regression tests for issues found in the post-hardening review."""
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import InterfaceError

from src.modules.analytics.domain.models.dashboard import DashboardFilters
from src.modules.analytics.infrastructure.repositories.dashboard_analytics_repository import (
    DashboardAnalyticsRepository,
)
from src.modules.assistant.application.agent import agent_service as agent_service_module
from src.modules.assistant.application.agent.graph.nodes import make_evaluate_context_node
from src.modules.assistant.application.agent.tools.rag_tool import RAGTool
from src.modules.assistant.application.services.sql_service import SQLService
from src.modules.assistant.application.use_cases.chat_use_case import ChatUseCase, _StreamTurn
from src.modules.assistant.domain.entities.search_documents_result import SearchDocumentsResult
from src.modules.assistant.domain.errors import (
    AgentOperationTimeout,
    DocumentRetrievalFailedError,
    SQLDatabaseConnectionLostError,
    SQLKeywordForbiddenError,
)
from src.modules.assistant.infrastructure.database.postgres_sql_executor import PostgresSQLExecutor
from src.modules.conversations.domain.repositories.i_conversation_repository import (
    IConversationRepository,
)


def _validator() -> SQLService:
    return SQLService.__new__(SQLService)


# ── 1-2. Vector store failure is reported, not turned into "no data" ──────────

def _state(tool_name: str, error_code: str | None, success: bool) -> dict:
    return {
        "context": {"has_data": False},
        "tool_name": tool_name,
        "tool_success": success,
        "tool_error_code": error_code,
        "trace_id": "t",
        "node_metrics": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["rag", "hybrid"])
async def test_vector_store_failure_is_reported_instead_of_asking_to_clarify(tool_name):
    updates = await make_evaluate_context_node()(_state(tool_name, "vector_store_query", False))

    assert updates["evaluation"]["decision"] == "respond"
    assert updates["context"]["response_mode"] == "tool_error"
    assert updates["response"].startswith(DocumentRetrievalFailedError().message)
    assert "clarification_question" not in updates


@pytest.mark.asyncio
async def test_empty_rag_result_without_error_still_asks_to_clarify():
    updates = await make_evaluate_context_node()(_state("rag", None, True))
    assert updates["evaluation"]["decision"] == "clarify"


@pytest.mark.asyncio
async def test_rag_tool_reports_failure_in_tool_result():
    search = MagicMock()
    search.execute_analyzed.return_value = SearchDocumentsResult(
        results=[], analyzed_query=MagicMock(), used_fallback=False, error_code="vector_store_query"
    )
    builder = MagicMock()
    builder.build_context.return_value = {"has_data": False, "retrieved_text": ""}

    result = await RAGTool(search, builder).run(analyzed=MagicMock(), messages=[], current_query="q")

    assert result.success is False
    assert result.error_code == "vector_store_query"
    assert result.metadata["context"]["retrieval_error"] == "vector_store_query"


# ── 4-5. SQL validator ────────────────────────────────────────────────────────

@pytest.mark.parametrize("literal", ["'%Vitamin E'", "'Size E'", "'be'", "'E'"])
def test_literal_ending_in_e_is_not_mistaken_for_an_escape_string(literal):
    _validator().validate(
        f"SELECT product_name FROM sales_invoice_lines WHERE product_name ILIKE {literal} LIMIT 5"
    )


@pytest.mark.parametrize("sql", [
    "SELECT E'\\'' AS x FROM customers",
    "SELECT e 'x' AS x FROM customers",
    "SELECT name FROM customers WHERE name = E'a'",
])
def test_escape_strings_are_still_rejected(sql):
    with pytest.raises(SQLKeywordForbiddenError):
        _validator().validate(sql)


def test_bare_user_keyword_is_rejected():
    with pytest.raises(SQLKeywordForbiddenError):
        _validator().validate("SELECT user AS u FROM customers LIMIT 1")


# ── 6. No duplicate save when cancelled during the title update ──────────────

@pytest.mark.asyncio
async def test_cancel_during_title_update_does_not_save_the_exchange_twice():
    repo = AsyncMock()
    repo.update_conversation.side_effect = asyncio.CancelledError
    use_case = ChatUseCase(MagicMock(), repo, AsyncMock())
    conversation_id = uuid4()
    turn = _StreamTurn(
        conversation_id=conversation_id, user_message="hi", user_id="owner",
        loaded=True, is_first_message=True,
    )
    turn.chunks.append("answer")

    with pytest.raises(asyncio.CancelledError):
        await use_case._persist_exchange(
            conversation_id, "hi", "answer", {}, "owner", True, turn=turn
        )
    await use_case._persist_interrupted(turn)

    assert turn.persisted is True
    assert repo.add_messages.await_count == 1


# ── 7. Stream deadline counts provider time only ─────────────────────────────

class _LLM:
    def __init__(self, delay: float, count: int = 3):
        self.delay = delay
        self.count = count

    async def stream_response(self, _query, _context):
        for index in range(self.count):
            await asyncio.sleep(self.delay)
            yield f"t{index}"


def _agent_service(llm) -> agent_service_module.AgentService:
    service = agent_service_module.AgentService.__new__(agent_service_module.AgentService)
    service._llm_service = llm
    return service


@pytest.mark.asyncio
async def test_slow_consumer_does_not_consume_the_stream_deadline(monkeypatch):
    monkeypatch.setattr(agent_service_module, "STREAM_RESPONSE_TIMEOUT_SECONDS", 0.2)
    tokens = []
    async for token in _agent_service(_LLM(delay=0.01)).stream_response("q", {}):
        tokens.append(token)
        await asyncio.sleep(0.15)  # consumer is slower than the whole budget
    assert tokens == ["t0", "t1", "t2"]


@pytest.mark.asyncio
async def test_slow_provider_raises_agent_timeout(monkeypatch):
    monkeypatch.setattr(agent_service_module, "STREAM_RESPONSE_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(AgentOperationTimeout):
        async for _ in _agent_service(_LLM(delay=0.2)).stream_response("q", {}):
            pass


# ── 8. Lost connection is reported as such ───────────────────────────────────

@pytest.mark.asyncio
async def test_interface_error_maps_to_connection_lost():
    engine = MagicMock()

    def connect():
        raise InterfaceError("SELECT 1", {}, Exception("connection closed"))

    engine.connect = connect
    with pytest.raises(SQLDatabaseConnectionLostError):
        await PostgresSQLExecutor(engine).execute_sql("SELECT 1")


# ── 9. Average invoice value uses the same grain as revenue under line filters ─

async def _metric_sql(filters: DashboardFilters) -> str:
    captured = []

    class Session:
        async def execute(self, statement):
            captured.append(statement)
            row = SimpleNamespace(
                total_revenue=0, invoice_count=0, customer_count=0,
                average_invoice_value=0, net_debt_delta=0,
            )
            return SimpleNamespace(one=lambda: row)

    class Context:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *args):
            return False

    await DashboardAnalyticsRepository(lambda: Context()).get_metric_snapshot(filters)
    return str(captured[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_average_invoice_value_uses_matching_lines_when_filtering_by_product():
    sql = await _metric_sql(DashboardFilters(date(2025, 3, 1), date(2025, 4, 1), product_names=("Gạch",)))
    assert "avg(sales_invoices.invoice_total_amount)" not in sql
    assert "sum(sales_invoice_lines.line_amount)" in sql


@pytest.mark.asyncio
async def test_average_invoice_value_uses_invoice_totals_without_line_filters():
    sql = await _metric_sql(DashboardFilters(date(2025, 3, 1), date(2025, 4, 1)))
    assert "avg(sales_invoices.invoice_total_amount)" in sql


# ── 10. Single legacy write path is gone ──────────────────────────────────────

def test_conversation_repository_has_only_the_transactional_write_path():
    assert not hasattr(IConversationRepository, "add_message")
    assert hasattr(IConversationRepository, "add_messages")
