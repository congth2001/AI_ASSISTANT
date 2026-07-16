import os
import sys
from uuid import uuid4

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT_DIR)

from src.application.agent.graph.edges import (
    route_after_text_to_sql,
    route_after_request_assessment,
    route_after_context_evaluation,
    route_after_response_evaluation,
)
from src.application.services.intent_classifier import IntentClassifier
from src.application.services.sql_service import SQLService, SQLValidationError
from src.application.use_cases.chat_use_case import ChatUseCase
from src.domain.entities.conversation import Conversation
from src.domain.entities.message import Message
from src.application.agent.runtime import AgentOperationTimeout, run_with_policy


class _LLM:
    def __init__(self, route):
        self.route = route

    async def classify_route(self, _query):
        return self.route


def test_sql_no_data_routes_to_rag():
    assert route_after_text_to_sql({"context": {"has_data": False}}) == "rag"


def test_sql_data_routes_to_response():
    assert route_after_text_to_sql({"context": {"has_data": True}}) == "generate_response"


@pytest.mark.asyncio
async def test_invalid_llm_route_uses_rule_based_fallback():
    classifier = IntentClassifier(_LLM("not-a-route"))
    assert await classifier.classify("Tổng doanh thu tháng này") == "text_to_sql"


def test_sql_validator_accepts_cte_and_adds_limit():
    service = SQLService(llm_service=None)
    sql = service.validate("WITH totals AS (SELECT 1 AS n) SELECT n FROM totals")
    assert sql.endswith("LIMIT 1000")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT * FROM invoices FOR UPDATE",
        "SELECT 1 -- hide another statement",
        "DELETE FROM invoices",
    ],
)
def test_sql_validator_rejects_unsafe_queries(sql):
    with pytest.raises(SQLValidationError):
        SQLService(llm_service=None).validate(sql)


def test_sql_validator_caps_large_limit():
    sql = SQLService(llm_service=None).validate("SELECT * FROM invoices LIMIT 999999")
    assert "LIMIT 1000" in sql


def test_cache_key_isolated_by_conversation_and_history():
    conversation_a = Conversation(id=uuid4(), user_id="user-1", messages=[])
    conversation_b = Conversation(id=uuid4(), user_id="user-1", messages=[])

    key_a = ChatUseCase._make_cache_key("Doanh thu tháng này?", conversation_a)
    key_b = ChatUseCase._make_cache_key("Doanh thu tháng này?", conversation_b)
    assert key_a != key_b

    conversation_a.messages.append(Message(role="user", content="Tháng 6"))
    key_with_history = ChatUseCase._make_cache_key("Doanh thu tháng này?", conversation_a)
    assert key_with_history != key_a


@pytest.mark.asyncio
async def test_runtime_policy_retries_transient_failure():
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary")
        return "ok"

    assert await run_with_policy(
        operation, name="test", timeout_seconds=1, retries=1
    ) == "ok"
    assert attempts == 2


@pytest.mark.asyncio
async def test_runtime_policy_enforces_timeout():
    import asyncio

    async def slow_operation():
        await asyncio.sleep(0.1)

    with pytest.raises(AgentOperationTimeout):
        await run_with_policy(
            slow_operation, name="slow", timeout_seconds=0.001
        )


def test_phase3_decision_edges():
    assert route_after_request_assessment({"needs_clarification": True}) == "clarify"
    assert route_after_request_assessment({"needs_clarification": False}) == "continue"
    assert route_after_context_evaluation({"evaluation": {"decision": "respond"}}) == "respond"
    assert route_after_context_evaluation({"evaluation": {"decision": "replan"}}) == "replan"
    assert route_after_response_evaluation({"evaluation": {"decision": "retry_response"}}) == "retry"
    assert route_after_response_evaluation({"evaluation": {"decision": "done"}}) == "done"
