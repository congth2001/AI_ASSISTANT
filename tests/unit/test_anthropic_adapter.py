from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.errors import ExternalServiceError
from src.modules.assistant.infrastructure.llm.anthropic_adapter import AnthropicAdapter
from src.modules.assistant.infrastructure.llm.llm_common import TRUNCATION_NOTICE


def response(text, stop_reason="end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason)


def make_adapter(result=None, error=None):
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=result, side_effect=error)
    return AnthropicAdapter(api_key="k", client=client), client


def test_defaults_use_async_client_and_current_model():
    adapter = AnthropicAdapter(api_key="k")
    assert adapter.model == "claude-sonnet-5-5"
    assert type(adapter._client).__name__ == "AsyncAnthropic"
    assert not hasattr(adapter, "client")


@pytest.mark.asyncio
async def test_generate_response_uses_retrieved_text_like_openai_adapter():
    adapter, client = make_adapter(response("  Xong [sql:1]  "))
    context = {
        "retrieved_text": "[sql:1] 10",
        "sources": [{"id": "sql:1"}],
        "conversation_history": [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
        ],
    }
    assert await adapter.generate_response("Doanh thu?", context) == "Xong [sql:1]"
    kwargs = client.messages.create.await_args.kwargs
    assert "[sql:1] 10" in kwargs["system"]
    # consecutive same-role turns are merged so roles strictly alternate
    assert [m["role"] for m in kwargs["messages"]] == ["user", "assistant", "user"]


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [response(""), response("cut", "max_tokens")])
async def test_generate_response_rejects_empty_or_truncated(result):
    adapter, _ = make_adapter(result)
    with pytest.raises(ExternalServiceError, match="Anthropic API error"):
        await adapter.generate_response("q")


@pytest.mark.asyncio
async def test_classify_route_parses_label_and_defaults_to_data_route():
    adapter, _ = make_adapter(response('{"route": "hybrid"}'))
    assert await adapter.classify_route("q") == "hybrid"
    adapter, _ = make_adapter(response('{"route": "weird"}'))
    assert await adapter.classify_route("q") == "rag"


@pytest.mark.asyncio
async def test_classify_route_raises_external_error_on_provider_failure():
    adapter, _ = make_adapter(error=RuntimeError("down"))
    with pytest.raises(ExternalServiceError):
        await adapter.classify_route("q")


class FakeStream:
    def __init__(self, texts, stop_reason):
        self.texts, self.stop_reason = texts, stop_reason

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def gen():
            for text in self.texts:
                yield text
        return gen()

    async def get_final_message(self):
        return SimpleNamespace(stop_reason=self.stop_reason)


@pytest.mark.asyncio
async def test_stream_appends_notice_when_truncated():
    adapter, client = make_adapter()
    client.messages.stream = MagicMock(return_value=FakeStream(["a", "b"], "max_tokens"))
    assert [t async for t in adapter.stream_response("q")] == ["a", "b", TRUNCATION_NOTICE]


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_to_original_on_failure():
    adapter, _ = make_adapter(error=RuntimeError("down"))
    assert await adapter.rewrite_query("câu gốc") == "câu gốc"
