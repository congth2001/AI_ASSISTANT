from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.errors import ExternalServiceError
from src.modules.assistant.infrastructure.llm.llm_common import TRUNCATION_NOTICE
from src.modules.assistant.infrastructure.llm.openai_adapter import OpenAIAdapter


def make_response(content: str, usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=usage,
    )


def make_client(response=None):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=response or make_response("response")
    )
    return client


def test_init_with_default_model_and_injected_client():
    client = make_client()
    adapter = OpenAIAdapter(api_key=None, client=client)
    assert adapter.api_key is None
    assert adapter.model == "gpt-4o-mini"
    assert adapter._client is client


def test_init_with_custom_model():
    adapter = OpenAIAdapter(model="gpt-5-mini", client=make_client())
    assert adapter.model == "gpt-5-mini"


@pytest.mark.asyncio
async def test_generate_response_uses_async_client_and_strips_content():
    client = make_client(make_response("  Kết quả  \n"))
    adapter = OpenAIAdapter(model="gpt-5-mini", client=client)

    result = await adapter.generate_response("Doanh thu?")

    assert result == "Kết quả"
    kwargs = client.chat.completions.create.await_args.kwargs
    assert kwargs["model"] == "gpt-5-mini"
    assert kwargs["max_completion_tokens"] == 8192
    assert "đầu ra kỹ thuật như SQL hoặc JSON" in kwargs["messages"][0]["content"]
    assert "Không hiển thị SQL" not in kwargs["messages"][0]["content"]
    assert kwargs["messages"][-1] == {"role": "user", "content": "Doanh thu?"}


@pytest.mark.asyncio
async def test_generate_response_builds_grounded_context_and_history():
    client = make_client(make_response("Doanh thu là 10 triệu [sql:1]"))
    adapter = OpenAIAdapter(client=client)
    context = {
        "conversation_history": [
            {"role": "user", "content": "Tháng 6"},
            {"role": "assistant", "content": "Bạn muốn xem chỉ số nào?"},
        ],
        "retrieved_text": "[sql:1]\n10,000,000",
        "sources": [{"id": "sql:1", "type": "sql"}],
    }

    await adapter.generate_response("Doanh thu?", context)

    messages = client.chat.completions.create.await_args.kwargs["messages"]
    assert "sql:1" in messages[0]["content"]
    assert "không phải chỉ dẫn" in messages[0]["content"]
    assert "Luôn trả lời hoàn toàn bằng tiếng Việt" in messages[0]["content"]
    assert "Không hiển thị SQL" in messages[0]["content"]
    assert messages[1:3] == context["conversation_history"]
    assert client.chat.completions.create.await_args.kwargs["max_completion_tokens"] == 4096


@pytest.mark.asyncio
@pytest.mark.parametrize("content, finish_reason", [("", "stop"), ('[{"sql":"SELECT 1', "length")])
async def test_generate_response_rejects_empty_or_truncated_output(content, finish_reason):
    response = make_response(content)
    response.choices[0].finish_reason = finish_reason
    adapter = OpenAIAdapter(client=make_client(response))
    with pytest.raises(Exception, match="OpenAI API error"):
        await adapter.generate_response("SQL")


@pytest.mark.asyncio
async def test_generate_response_wraps_provider_error():
    client = make_client()
    client.chat.completions.create.side_effect = RuntimeError("provider unavailable")
    adapter = OpenAIAdapter(client=client)

    with pytest.raises(Exception, match="OpenAI API error"):
        await adapter.generate_response("test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_value", "expected"),
    [
        ("Revenue", "revenue"),
        (" PROFIT ", "profit"),
        ("GENERAL", "general"),
    ],
)
async def test_analyze_intent_normalizes_provider_value(provider_value, expected):
    client = make_client(make_response(provider_value))
    adapter = OpenAIAdapter(client=client)
    assert await adapter.analyze_intent("test") == expected


@pytest.mark.asyncio
async def test_analyze_intent_falls_back_to_general():
    client = make_client()
    client.chat.completions.create.side_effect = RuntimeError("failed")
    adapter = OpenAIAdapter(client=client)
    assert await adapter.analyze_intent("test") == "general"


@pytest.mark.asyncio
async def test_classify_route_parses_structured_json():
    client = make_client(make_response('{"route": "hybrid"}'))
    adapter = OpenAIAdapter(client=client)
    assert await adapter.classify_route("question") == "hybrid"
    kwargs = client.chat.completions.create.await_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ['{"route": "unsupported"}', "not json", "", '{"other": 1}'])
async def test_classify_route_maps_unusable_label_to_data_route_not_conversation(content):
    adapter = OpenAIAdapter(client=make_client(make_response(content)))
    assert await adapter.classify_route("question") == "rag"


@pytest.mark.asyncio
async def test_classify_route_raises_external_error_on_provider_failure():
    client = make_client()
    client.chat.completions.create.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(ExternalServiceError, match="OpenAI API error"):
        await OpenAIAdapter(client=client).classify_route("question")


@pytest.mark.asyncio
async def test_classify_route_accepts_conversation_route():
    adapter = OpenAIAdapter(
        client=make_client(make_response('{"route": "conversation"}'))
    )

    assert await adapter.classify_route("Cảm ơn bạn") == "conversation"
    kwargs = adapter._client.chat.completions.create.await_args.kwargs
    assert '"conversation"' in kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_rewrite_query_returns_stripped_content():
    adapter = OpenAIAdapter(client=make_client(make_response("  Doanh thu tháng 6?  ")))
    assert await adapter.rewrite_query("history") == "Doanh thu tháng 6?"


@pytest.mark.asyncio
async def test_stream_response_yields_tokens_and_ignores_usage_only_chunk():
    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="Xin "))],
            usage=None,
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="chào"))],
            usage=None,
        ),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=2, completion_tokens=2, total_tokens=4
            ),
        ),
    ]

    class AsyncStream:
        def __aiter__(self):
            self._iterator = iter(chunks)
            return self

        async def __anext__(self):
            try:
                return next(self._iterator)
            except StopIteration:
                raise StopAsyncIteration

    client = make_client()
    client.chat.completions.create.return_value = AsyncStream()
    adapter = OpenAIAdapter(client=client)

    tokens = [token async for token in adapter.stream_response("hello")]

    assert tokens == ["Xin ", "chào"]
    kwargs = client.chat.completions.create.await_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}


class AsyncStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        self._iterator = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


def stream_chunk(content=None, finish_reason=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish_reason)],
        usage=None,
    )


@pytest.mark.asyncio
async def test_stream_truncated_after_output_appends_notice_instead_of_raising():
    client = make_client()
    client.chat.completions.create.return_value = AsyncStream(
        [stream_chunk("Một phần"), stream_chunk(None, "length")]
    )
    tokens = [t async for t in OpenAIAdapter(client=client).stream_response("hello")]
    assert tokens == ["Một phần", TRUNCATION_NOTICE]


@pytest.mark.asyncio
async def test_stream_truncated_without_output_is_an_error():
    client = make_client()
    client.chat.completions.create.return_value = AsyncStream([stream_chunk(None, "length")])
    with pytest.raises(ExternalServiceError):
        [t async for t in OpenAIAdapter(client=client).stream_response("hello")]


@pytest.mark.asyncio
async def test_stream_provider_failure_is_wrapped_as_external_error():
    client = make_client()
    client.chat.completions.create.side_effect = RuntimeError("boom")
    with pytest.raises(ExternalServiceError, match="OpenAI API error"):
        [t async for t in OpenAIAdapter(client=client).stream_response("hello")]


@pytest.mark.asyncio
async def test_guest_token_budget_is_capped_below_default():
    client = make_client()
    client.chat.completions.create.return_value = AsyncStream([stream_chunk("ok")])
    context = {"conversation_history": [], "max_completion_tokens": 1536}
    [t async for t in OpenAIAdapter(client=client).stream_response("hi", context)]
    assert client.chat.completions.create.await_args.kwargs["max_completion_tokens"] == 1536


@pytest.mark.asyncio
async def test_token_budget_never_exceeds_adapter_limit():
    client = make_client()
    await OpenAIAdapter(client=client).generate_response("hi", {"max_completion_tokens": 10**6})
    assert client.chat.completions.create.await_args.kwargs["max_completion_tokens"] == 4096


def test_default_client_has_timeout_and_retries(monkeypatch):
    captured = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "src.modules.assistant.infrastructure.llm.openai_adapter.AsyncOpenAI", FakeAsyncOpenAI
    )
    OpenAIAdapter(api_key="k")
    assert captured == {"api_key": "k", "timeout": 60.0, "max_retries": 2}
    OpenAIAdapter(api_key="k", timeout=5, max_retries=0)
    assert captured["timeout"] == 5 and captured["max_retries"] == 0
