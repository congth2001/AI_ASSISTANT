"""Streaming/persistence behaviour of ChatUseCase and the chat router."""
import asyncio
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from config.container import container
from main import create_app
from src.common.errors import ExternalServiceError
from src.modules.assistant.application.agent.agent_service import AgentService
from src.modules.assistant.application.agent.tools.text_to_sql_tool import TextToSQLTool
from src.modules.assistant.application.services.intent_classifier import IntentClassifier
from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.application.services.query_contextualizer import QueryContextualizer
from src.modules.assistant.application.use_cases.chat_use_case import (
    CHAT_RESPONSE_CACHE_PREFIX,
    ChatUseCase,
)
from src.modules.assistant.domain.errors import AgentOperationTimeout, GuestBusinessDataForbiddenError
from src.modules.auth.presentation.router import get_current_user


def events_of(raw_events):
    return [json.loads(e.removeprefix("data: ").strip()) for e in raw_events]


def conversation_state(**overrides):
    state = {
        "context": {"response_mode": "conversation", "intent": "conversation", "has_data": True},
        "response": None,
        "citations": [],
        "tool_name": None,
        "tool_success": True,
        "needs_clarification": False,
        "evaluation": {"decision": "respond"},
    }
    state.update(overrides)
    return state


class FakeAgent:
    def __init__(self, tokens=("Xin ", "chào"), state=None, fail_after=None, hang=False):
        self.tokens = tokens
        self.state = state or conversation_state()
        self.fail_after = fail_after
        self.hang = hang
        self.invocations = 0

    async def invoke(self, *_a, **_k):
        self.invocations += 1
        return {**self.state, "response": "Xin chào"}

    async def invoke_for_context(self, *_a, **_k):
        self.invocations += 1
        return self.state

    async def stream_response(self, _query, _context):
        for index, token in enumerate(self.tokens):
            if self.fail_after is not None and index == self.fail_after:
                raise ExternalServiceError()
            yield token
        if self.hang:
            await asyncio.Event().wait()

    async def stream_stateless_conversation(self, _query):
        for token in self.tokens:
            if self.fail_after is not None:
                raise ExternalServiceError()
            yield token

    async def classify_route(self, _query):
        return "conversation"


def build(agent=None, cached=None):
    conversation_id = uuid4()
    repo = AsyncMock()
    repo.get_conversation.return_value = {
        "id": str(conversation_id), "user_id": "owner", "messages": [],
    }
    cache = AsyncMock()
    cache.get.return_value = cached
    use_case = ChatUseCase(agent or FakeAgent(), repo, cache)
    return use_case, repo, cache, conversation_id


async def collect(generator):
    return [event async for event in generator]


@pytest.mark.asyncio
async def test_stream_persists_both_messages_in_one_call_and_user_metadata_is_empty():
    use_case, repo, _cache, cid = build()

    events = events_of(await collect(use_case.execute_stream(cid, "Xin chào", "owner")))

    assert events[-1]["type"] == "done"
    repo.add_messages.assert_awaited_once()
    saved = repo.add_messages.await_args.args[1]
    assert [m["role"] for m in saved] == ["user", "assistant"]
    assert saved[0]["metadata"] is None
    assert saved[1]["content"] == "Xin chào"
    assert "tool_used" in saved[1]["metadata"]
    repo.add_message.assert_not_called()
    repo.update_conversation.assert_awaited_once()  # first message sets the title


@pytest.mark.asyncio
async def test_cache_hit_does_not_copy_assistant_metadata_to_user_message():
    payload = {"response": "đã lưu", "intent": "conversation", "metadata": {"tool_used": None}}
    use_case, repo, _cache, cid = build(cached=json.dumps(payload))

    events = events_of(await collect(use_case.execute_stream(cid, "Xin chào", "owner")))

    assert events[-1]["metadata"]["cache_hit"] is True
    saved = repo.add_messages.await_args.args[1]
    assert saved[0]["metadata"] is None
    assert saved[1]["metadata"] == {"tool_used": None}

    result = await use_case.execute(cid, "Xin chào", "owner")
    assert result["metadata"]["cache_hit"] is True
    assert repo.add_messages.await_args.args[1][0]["metadata"] is None


@pytest.mark.asyncio
async def test_cancel_mid_stream_saves_user_message_and_partial_answer_then_reraises():
    use_case, repo, _cache, cid = build(FakeAgent(hang=True))
    seen = []

    async def consume():
        async for event in use_case.execute_stream(cid, "Xin chào", "owner"):
            seen.append(event)

    task = asyncio.create_task(consume())
    for _ in range(200):
        await asyncio.sleep(0)
        if sum('"type": "token"' in e for e in seen) == 2:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.gather(*use_case._background_tasks)

    saved = repo.add_messages.await_args.args[1]
    assert [m["role"] for m in saved] == ["user", "assistant"]
    assert saved[1]["content"] == "Xin chào"
    assert saved[1]["metadata"] == {"interrupted": True}
    repo.update_conversation.assert_awaited_once()


@pytest.mark.asyncio
async def test_generator_close_before_any_token_saves_only_the_user_message():
    use_case, repo, _cache, cid = build(FakeAgent(tokens=()))
    stream = use_case.execute_stream(cid, "Câu hỏi", "owner")
    assert '"routing"' in await stream.__anext__()
    await stream.aclose()
    await asyncio.gather(*use_case._background_tasks)

    saved = repo.add_messages.await_args.args[1]
    assert [m["role"] for m in saved] == ["user"]
    assert saved[0]["metadata"] == {"interrupted": True}


@pytest.mark.asyncio
async def test_completed_stream_is_not_saved_again_on_close():
    use_case, repo, _cache, cid = build()
    stream = use_case.execute_stream(cid, "Xin chào", "owner")
    async for _ in stream:
        pass
    await stream.aclose()
    repo.add_messages.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_failure_after_streaming_emits_error_instead_of_done():
    use_case, repo, _cache, cid = build()
    repo.add_messages.side_effect = RuntimeError("db down")

    events = events_of(await collect(use_case.execute_stream(cid, "Xin chào", "owner")))

    types = [e["type"] for e in events]
    assert types[-1] == "error" and "done" not in types
    assert "token" in types
    assert "db down" not in json.dumps(events)


@pytest.mark.asyncio
async def test_llm_failure_mid_stream_emits_error():
    use_case, _repo, _cache, cid = build(FakeAgent(fail_after=1))
    events = events_of(await collect(use_case.execute_stream(cid, "Xin chào", "owner")))
    assert events[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_cache_backend_failure_does_not_break_answer():
    use_case, _repo, cache, cid = build()
    cache.get.side_effect = RuntimeError("redis down")
    cache.set.side_effect = RuntimeError("redis down")
    events = events_of(await collect(use_case.execute_stream(cid, "Xin chào", "owner")))
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_sql_answers_are_not_cached_but_conversation_answers_are():
    sql_state = conversation_state(tool_name="text_to_sql", tool_success=True)
    use_case, _repo, cache, cid = build(FakeAgent(state=sql_state))
    await collect(use_case.execute_stream(cid, "Doanh thu?", "owner"))
    cache.set.assert_not_awaited()

    use_case, _repo, cache, cid = build()
    await collect(use_case.execute_stream(cid, "Xin chào", "owner"))
    cache.set.assert_awaited_once()
    assert cache.set.await_args.args[0].startswith(CHAT_RESPONSE_CACHE_PREFIX)


@pytest.mark.parametrize("tool", ["text_to_sql", "hybrid"])
def test_sales_table_tools_are_not_cacheable(tool):
    assert ChatUseCase._is_cacheable({"tool_used": tool, "tool_success": True}) is False
    assert ChatUseCase._is_cacheable({"tool_used": "rag", "tool_success": True}) is True


def test_metadata_keeps_legacy_keys_with_fixed_values():
    metadata = ChatUseCase._build_metadata(conversation_state(), {"has_data": True})
    assert metadata["plan"] == [] and metadata["iteration"] == 0
    assert metadata["awaiting_approval"] is False and metadata["pending_action"] is None
    assert metadata["tool_calls"] == [] and metadata["citations"] == []


@pytest.mark.asyncio
async def test_non_stream_execute_uses_single_transaction_helper():
    use_case, repo, cache, cid = build()
    result = await use_case.execute(cid, "Xin chào", "owner")
    assert result["response"] == "Xin chào"
    saved = repo.add_messages.await_args.args[1]
    assert saved[0]["metadata"] is None and saved[1]["metadata"]["tool_used"] is None
    cache.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_guest_stream_ends_with_done():
    use_case, repo, _cache, _cid = build()
    events = events_of(await collect(use_case.execute_guest_stream("Xin chào")))
    assert [e["type"] for e in events] == ["status", "token", "token", "done"]
    assert events[-1]["metadata"] == {"stateless": True, "data_access": False}
    assert not repo.mock_calls


@pytest.mark.asyncio
async def test_guest_stream_failure_emits_error_event():
    use_case, _repo, _cache, _cid = build(FakeAgent(fail_after=0))
    events = events_of(await collect(use_case.execute_guest_stream("Xin chào")))
    assert events[-1]["type"] == "error"
    assert "done" not in [e["type"] for e in events]


# ── AgentService: unique thread per turn, checkpoint cleanup, overall timeout ──

def make_agent_service():
    llm = AsyncMock()
    return AgentService(
        IntentClassifier(llm), QueryAnalyzer(), QueryContextualizer(llm),
        TextToSQLTool(AsyncMock()), AsyncMock(), llm,
    )


@pytest.mark.asyncio
async def test_each_turn_uses_a_unique_thread_and_checkpoints_are_deleted():
    agent = make_agent_service()
    checkpointer = agent._context_graph.checkpointer
    seen = []
    original = checkpointer.adelete_thread

    async def spy(thread_id):
        seen.append(thread_id)
        await original(thread_id)

    checkpointer.adelete_thread = spy
    for _ in range(2):
        state = await agent.invoke_for_context("Xin chào", [], thread_id="conv-1")
        assert state["context"]["response_mode"] == "conversation"

    assert len(seen) == 2 and len(set(seen)) == 2
    assert all(t.startswith("context:conv-1:") for t in seen)
    assert checkpointer.storage == {}
    assert not checkpointer.writes


@pytest.mark.asyncio
async def test_full_graph_thread_is_also_cleaned_up():
    agent = make_agent_service()
    agent._llm_service.generate_response.return_value = "Chào bạn"
    await agent.invoke("Xin chào", [], thread_id="conv-2")
    assert agent._graph.checkpointer.storage == {}


@pytest.mark.asyncio
async def test_graph_run_is_bounded_by_overall_timeout(monkeypatch):
    from src.modules.assistant.application.agent import agent_service as module

    class SlowGraph:
        checkpointer = None

        async def ainvoke(self, *_a, **_k):
            await asyncio.sleep(5)

    agent = make_agent_service()
    agent._context_graph = SlowGraph()
    monkeypatch.setattr(module, "CONTEXT_GRAPH_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(AgentOperationTimeout):
        await agent.invoke_for_context("Xin chào", [])


@pytest.mark.asyncio
async def test_guest_context_caps_completion_tokens():
    agent = make_agent_service()
    captured = {}

    async def fake_stream(_query, context):
        captured.update(context)
        yield "ok"

    agent._llm_service.stream_response = fake_stream
    assert [t async for t in agent.stream_stateless_conversation("Xin chào")] == ["ok"]
    assert captured["max_completion_tokens"] <= 2048
    assert captured["has_data"] is False


# ── HTTP layer ────────────────────────────────────────────────────────────────

class RouterChat:
    def __init__(self, authorize_error=None, stream_error=False):
        self.authorize_error = authorize_error
        self.stream_error = stream_error

    async def authorize_guest_query(self, _message):
        if self.authorize_error:
            raise self.authorize_error

    async def execute_guest_stream(self, message):
        yield 'data: {"type": "token", "content": "hi"}\n\n'
        if self.stream_error:
            raise RuntimeError("secret internals")
        yield 'data: {"type": "done"}\n\n'

    async def execute_guest(self, message):
        return {
            "conversation_id": None, "response": "hi", "intent": "conversation",
            "timestamp": "2026-10-16T12:00:00+07:00", "metadata": {},
        }


class SearchUseCase:
    def __init__(self):
        self.called_with = None

    def execute(self, **_kwargs):  # pragma: no cover - must not be used from async code
        raise AssertionError("blocking execute() must not be called in the event loop")

    async def execute_async(self, query):
        self.called_with = query
        return type("R", (), {"results": [], "used_fallback": False})()


@contextmanager
def client_for(role, chat=None, search=None):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": role}
    with (
        container.chat_use_case.override(providers.Object(chat or RouterChat())),
        container.search_documents_use_case.override(providers.Object(search or SearchUseCase())),
        TestClient(app) as client,
    ):
        yield client


@pytest.mark.parametrize("body", [{"message": ""}, {"message": "   "}, {"message": "x" * 4001}, {}])
def test_chat_request_rejects_empty_or_oversized_message(body):
    with client_for("guest") as client:
        assert client.post("/api/v1/chat", json=body).status_code == 422
        assert client.post("/api/v1/chat/stream", json=body).status_code == 422


def test_chat_request_ignores_legacy_user_id_field():
    with client_for("guest") as client:
        response = client.post("/api/v1/chat", json={"message": "hi", "user_id": "spoofed"})
    assert response.status_code == 200


def test_guest_refusal_is_http_403_before_any_stream_opens():
    chat = RouterChat(authorize_error=GuestBusinessDataForbiddenError())
    with client_for("guest", chat) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "doanh thu"})
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/json")


def test_guest_authorization_infrastructure_error_maps_to_domain_status():
    chat = RouterChat(authorize_error=ExternalServiceError())
    with client_for("guest", chat) as client:
        assert client.post("/api/v1/chat/stream", json={"message": "hi"}).status_code == 502


def test_guest_authorization_unexpected_error_is_a_clean_500():
    chat = RouterChat(authorize_error=RuntimeError("boom"))
    with TestClientWithoutRaise(chat) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "hi"})
    assert response.status_code == 500
    assert "boom" not in response.text


class TestClientWithoutRaise:
    __test__ = False

    def __init__(self, chat):
        self._cm = client_for("guest", chat)

    def __enter__(self):
        client = self._cm.__enter__()
        client.raise_server_exceptions = False
        return client

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)


def test_stream_router_adds_terminal_error_event_for_unexpected_failure():
    chat = RouterChat(stream_error=True)
    with client_for("guest", chat) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "hi"})
    assert response.status_code == 200
    events = events_of([e + "\n\n" for e in response.text.split("\n\n") if e])
    assert [e["type"] for e in events] == ["token", "error"]
    assert "secret internals" not in response.text


def test_search_documents_uses_non_blocking_async_entry_point():
    search = SearchUseCase()
    with client_for("staff", search=search) as client:
        response = client.post("/api/v1/search-documents", json={"query": "thuế VAT"})
    assert response.status_code == 200
    assert search.called_with == "thuế VAT"
