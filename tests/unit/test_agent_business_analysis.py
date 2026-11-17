"""Regressions for overview analysis: dashboard scope, tool failures, and dates."""
from datetime import date, datetime
from decimal import Decimal
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.common.domain.time import VIETNAM_TIMEZONE
from src.modules.assistant.application.agent.agent_service import AgentService
from src.modules.assistant.application.agent.tools.text_to_sql_tool import TextToSQLTool
from src.modules.assistant.application.services.intent_classifier import IntentClassifier
from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.application.services.query_contextualizer import QueryContextualizer
from src.modules.assistant.application.services.schema_linker import SchemaLinker
from src.modules.assistant.application.services.sql_service import SQLService, SQLQueryPlan
from src.modules.assistant.application.use_cases.chat_use_case import ChatUseCase
from src.modules.assistant.application.use_cases.text_to_sql_use_case import TextToSQLUseCase
from src.modules.assistant.domain.errors import SQLExecutionFailedError
from src.modules.conversations.domain.entities.message import Message


REPORT_QUERY = """Phân tích kết quả kinh doanh và các biến động đáng chú ý trong kỳ đang chọn.
Ngữ cảnh báo cáo đang xem:
Kỳ hiện tại: từ 2026-01-01 đến hết 2026-10-18, múi giờ Asia/Ho_Chi_Minh.
Bộ lọc: khách hàng tất cả; phường/xã tất cả; thôn/xóm tất cả.
Kỳ trước cùng số ngày: 2025-03-16 đến hết 2025-12-31.
Khách giảm mạnh nhất: Anh Minh (customer_id=11111111-1111-1111-1111-111111111111), kỳ trước 100, kỳ này 50 VND.
"""


def test_dashboard_reference_customer_does_not_narrow_report():
    analyzed = QueryAnalyzer(customer_names=["Anh Minh"]).analyze(REPORT_QUERY)
    assert analyzed.customer_name is None
    assert analyzed.customer_id is None
    assert analyzed.time_filter.date_from == date(2026, 1, 1)
    assert analyzed.time_filter.date_to == date(2026, 10, 19)
    hints = SchemaLinker().link(analyzed).filter_hints
    assert hints == {
        "sales_invoices.issued_at.gte": "2026-01-01",
        "sales_invoices.issued_at.lt": "2026-10-19",
    }


def test_dashboard_explicit_customer_and_geography_survive_schema_linking():
    selected_id = str(uuid4())
    query = REPORT_QUERY.replace(
        "khách hàng tất cả; phường/xã tất cả; thôn/xóm tất cả",
        f"khách hàng Anh Minh (customer_id={selected_id}); phường/xã Xã A; thôn/xóm Thôn B",
    )
    hints = SchemaLinker().link(QueryAnalyzer().analyze(query)).filter_hints
    assert hints["customers.customer_id"] == selected_id
    assert hints["customers.ward_name"] == "Xã A"
    assert hints["customers.village_name"] == "Thôn B"


@pytest.mark.asyncio
async def test_followup_rewrite_preserves_current_dashboard_context():
    llm = AsyncMock()
    llm.rewrite_query.return_value = "So sánh doanh thu với kỳ trước"
    history = [Message(role="assistant", content="Kết quả cũ"), Message(role="user", content="Doanh thu?")]
    resolved = await QueryContextualizer(llm).resolve(REPORT_QUERY, history)
    assert resolved.startswith("So sánh doanh thu với kỳ trước\nNgữ cảnh")
    assert resolved.partition("\nNgữ cảnh báo cáo đang xem:")[2] == REPORT_QUERY.partition("\nNgữ cảnh báo cáo đang xem:")[2]


@pytest.mark.parametrize("phrase, month, quarter", [
    ("tháng 10/2026", 10, None), ("tháng 11/2026", 11, None),
    ("tháng 12/2026", 12, None), ("tháng mười hai năm 2026", 12, None),
    ("quý IV năm 2026", None, 4), ("quý 3 năm 2026", None, 3),
])
def test_time_extraction_keeps_full_month_and_quarter(phrase, month, quarter):
    tf = QueryAnalyzer().analyze("Doanh thu " + phrase).time_filter
    assert (tf.year, tf.month, tf.quarter) == (2026, month, quarter)


def test_relative_time_changes_without_process_restart(monkeypatch):
    import src.modules.assistant.application.services.query_analyzer as module
    analyzer = QueryAnalyzer()
    for current in (datetime(2026, 12, 31, tzinfo=VIETNAM_TIMEZONE), datetime(2027, 1, 1, tzinfo=VIETNAM_TIMEZONE)):
        monkeypatch.setattr(module, "now_vietnam", lambda: current)
        tf = analyzer.analyze("Doanh thu hôm nay").time_filter
        assert (tf.year, tf.month, tf.day) == (current.year, current.month, current.day)
    tf = analyzer.analyze("Doanh thu quý trước").time_filter
    assert (tf.year, tf.quarter) == (2026, 4)


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [REPORT_QUERY.splitlines()[0], "Đánh giá tình hình kinh doanh gần đây"])
async def test_business_analysis_routes_to_sql_even_when_llm_misclassifies(question):
    llm = AsyncMock()
    llm.classify_route.return_value = "conversation"
    assert await IntentClassifier(llm).classify(question) == "text_to_sql"
    llm.classify_route.assert_not_called()


def test_incomplete_json_is_not_treated_as_raw_sql():
    assert SQLService._parse('[{"intent":"kpi","sql":"SELECT 1') == []


@pytest.mark.asyncio
async def test_repaired_sql_is_reported_as_executed_source():
    executor = AsyncMock()
    executor.execute_sql.side_effect = [RuntimeError("bad column"), ([(Decimal("12.34"),)], ["doanh_thu"])]
    service = AsyncMock()
    service.generate.return_value = [SQLQueryPlan("kpi", "SELECT bad_column")]
    service.validate_all = SQLService(None).validate_all
    service.repair.return_value = SQLQueryPlan("kpi", "SELECT 12.34 AS doanh_thu")
    use_case = TextToSQLUseCase(executor, SchemaLinker(), service)
    queries, content, success, has_data, error = await use_case.execute(QueryAnalyzer().analyze(REPORT_QUERY))
    assert queries == ["SELECT 12.34 AS doanh_thu"]
    assert "12.34" in content
    assert success and has_data and error is None


@pytest.mark.asyncio
async def test_failed_sql_is_not_reported_as_no_data_or_internal_exception():
    executor = AsyncMock()
    executor.execute_sql.side_effect = RuntimeError("private database details")
    service = SQLService(AsyncMock())
    service.llm_service.generate_response.return_value = '[{"intent":"kpi","sql":"SELECT 1 AS n"}]'
    result = await TextToSQLUseCase(executor, SchemaLinker(), service).execute(QueryAnalyzer().analyze(REPORT_QUERY))
    assert result[2:5] == (False, False, SQLExecutionFailedError.code)
    assert "Không thể thực hiện truy vấn dữ liệu" in result[1]
    assert "Không có dữ liệu" not in result[1]
    assert "private database details" not in result[1]


@pytest.mark.asyncio
async def test_overview_question_executes_multiple_plans_and_retains_report_scope():
    llm, executor, rag = AsyncMock(), AsyncMock(), AsyncMock()
    llm.generate_response.return_value = json.dumps([
        {"intent": intent, "sql": f"SELECT {index} AS chi_so"}
        for index, intent in enumerate(("kpi", "xu_huong", "khach_hang", "dia_ban", "cong_no"))
    ])
    executor.execute_sql.return_value = ([(Decimal("12.34"),)], ["chi_so"])
    service = SQLService(llm)
    sql_tool = TextToSQLTool(TextToSQLUseCase(executor, SchemaLinker(), service))
    agent = AgentService(IntentClassifier(llm), QueryAnalyzer(customer_names=["Anh Minh"]), QueryContextualizer(llm), sql_tool, rag, llm)
    state = await agent.invoke_for_context(REPORT_QUERY, [])
    assert state["route"] == "text_to_sql"
    assert executor.execute_sql.await_count == 5
    assert len(state["citations"]) == 5
    assert state["context"]["has_data"] is True
    prompt = llm.generate_response.await_args.args[0]
    assert '"sales_invoices.issued_at.lt": "2026-10-19"' in prompt
    assert '"customers.customer_name"' not in prompt
    assert "2025-03-16 đến hết 2025-12-31" in prompt
    assert "12.34" in state["context"]["retrieved_text"]
    assert "[sql:5] [cong_no]" in state["context"]["retrieved_text"]
    assert "Khách giảm mạnh nhất" not in state["context"]["retrieved_text"]
    rag.run.assert_not_called()


@pytest.mark.asyncio
async def test_sql_failure_returns_actionable_error_in_both_graphs_and_sse():
    llm = AsyncMock()
    rag = AsyncMock()
    failed_use_case = AsyncMock()
    failed_use_case.execute.return_value = ([], "failure", False, False, SQLExecutionFailedError.code)
    agent = AgentService(IntentClassifier(llm), QueryAnalyzer(), QueryContextualizer(llm), TextToSQLTool(failed_use_case), rag, llm)
    for invoke in (agent.invoke, agent.invoke_for_context):
        state = await invoke(REPORT_QUERY, [])
        assert state["evaluation"]["decision"] != "clarify"
        assert state["needs_clarification"] is False
        assert "Không thể thực hiện truy vấn dữ liệu" in state["response"]
    repo, cache = AsyncMock(), AsyncMock()
    conversation_id = uuid4()
    repo.get_conversation.return_value = {"id": str(conversation_id), "messages": [], "user_id": "owner"}
    cache.get.return_value = None
    events = [event async for event in ChatUseCase(agent, repo, cache).execute_stream(conversation_id, REPORT_QUERY, "owner")]
    assert any('"type": "token"' in event and "Không thể thực hiện truy vấn dữ liệu" in event for event in events)
    assert any('"type": "done"' in event for event in events)
    rag.run.assert_not_called()
    llm.generate_response.assert_not_called()
    llm.stream_response.assert_not_called()


def test_agent_dependency_construction_does_not_connect_to_milvus():
    from config.container import Container
    from config.settings import Settings, LLMSettings, AuthSettings
    settings = Settings.model_construct(llm=LLMSettings(openai_api_key="synthetic"), auth=AuthSettings(jwt_secret="synthetic-secret-with-at-least-thirty-two-characters"))
    container = Container()
    container.config.from_dict(settings.to_container_config())
    with patch("src.modules.assistant.infrastructure.database.milvus_client.PyMilvusClient", side_effect=RuntimeError("Milvus unavailable")) as connect:
        assert container.agent_service() is not None
        connect.assert_not_called()


def test_milvus_connects_only_on_first_vector_operation_and_reuses_connection():
    from src.modules.assistant.infrastructure.database.milvus_client import MilvusClient
    with patch("src.modules.assistant.infrastructure.database.milvus_client.PyMilvusClient") as connect:
        connect.return_value.query.return_value = [{"doc_id": "fixture"}]
        vector_db = MilvusClient()
        connect.assert_not_called()
        assert vector_db.query("doc_id != ''") == [{"doc_id": "fixture"}]
        vector_db.query("doc_id != ''")
        connect.assert_called_once()
