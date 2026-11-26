import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

import anthropic

from src.modules.assistant.domain.errors import AnthropicRequestError
from src.modules.assistant.domain.ports.i_llm_service import ILLMService
from src.modules.assistant.infrastructure.llm.llm_common import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    TRUNCATION_NOTICE,
    build_system_prompt,
    parse_route,
)

logger = logging.getLogger(__name__)


class AnthropicAdapter(ILLMService):
    """Anthropic Claude implementation of LLM service.

    Uses ``AsyncAnthropic`` throughout so calls never block the event loop.
    Not wired into the container by default; keep behaviour aligned with
    ``OpenAIAdapter`` (same prompts, error contract and route labels).
    """

    RESPONSE_MAX_TOKENS = 4096
    ROUTE_MAX_TOKENS = 64

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-5-5",
        client: anthropic.AsyncAnthropic | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.api_key = api_key
        self.model = model
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )

    @staticmethod
    def _build_messages(prompt: str, context: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Conversation turns in the strictly alternating user/assistant form the API requires."""
        turns = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in (context or {}).get("conversation_history", [])
            if msg.get("role") in ("user", "assistant") and msg.get("content")
        ]
        turns.append({"role": "user", "content": prompt})
        merged: List[Dict[str, str]] = []
        for turn in turns:
            if merged and merged[-1]["role"] == turn["role"]:
                merged[-1]["content"] += "\n\n" + turn["content"]
            else:
                merged.append(dict(turn))
        if merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": "(tiếp tục cuộc trò chuyện)"})
        return merged

    @staticmethod
    def _text(response: Any) -> str:
        return "".join(block.text for block in response.content if block.type == "text").strip()

    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate response using Anthropic Claude"""
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=self.RESPONSE_MAX_TOKENS,
                temperature=0.7,
                system=build_system_prompt(context),
                messages=self._build_messages(prompt, context),
            )
            text = self._text(response)
            if response.stop_reason == "max_tokens" or not text:
                logger.warning("LLM returned incomplete or empty output", extra={"model": self.model})
                raise AnthropicRequestError()
            return text
        except AnthropicRequestError:
            raise
        except Exception as exc:
            logger.exception("Anthropic generate_response failed", extra={"model": self.model})
            raise AnthropicRequestError() from exc

    async def analyze_intent(self, message: str) -> str:
        """Analyze intent of user message"""
        try:
            prompt = f"""
            Analyze the intent of this user message and classify it into one of these categories:
            - revenue: questions about income, sales, earnings
            - profit: questions about profit, loss, margins
            - customer: questions about customers, clients, users
            - inventory: questions about stock, products, inventory
            - sales: questions about sales transactions, orders
            - trend: questions about changes, trends, growth
            - comparison: questions comparing different things
            - report: requests for reports, summaries, analysis
            - general: general conversation or other topics

            Message: "{message}"

            Return only the category name, nothing else.
            """
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=50,
                temperature=0.1,
                system="You are an intent classification assistant. Return only the category name.",
                messages=[{"role": "user", "content": prompt}],
            )
            return self._text(response).lower()
        except Exception:
            logger.warning("Anthropic analyze_intent failed; using 'general'", exc_info=True)
            return "general"  # fallback

    async def stream_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> AsyncGenerator[str, None]:
        """Stream response tokens; append a notice if the output hit the token limit."""
        emitted = False
        try:
            async with self._client.messages.stream(
                model=self.model,
                max_tokens=self.RESPONSE_MAX_TOKENS,
                system=build_system_prompt(context),
                messages=self._build_messages(prompt, context),
            ) as stream:
                async for text in stream.text_stream:
                    emitted = True
                    yield text
                final = await stream.get_final_message()
            if final.stop_reason == "max_tokens":
                logger.warning("LLM stream truncated by token limit", extra={"model": self.model})
                if not emitted:
                    raise AnthropicRequestError()
                yield TRUNCATION_NOTICE
        except AnthropicRequestError:
            raise
        except Exception as exc:
            logger.exception("Anthropic stream_response failed", extra={"model": self.model})
            raise AnthropicRequestError() from exc

    async def classify_route(self, query: str) -> str:
        """Classify query into a routing label.

        Provider/infrastructure failures raise ``AnthropicRequestError`` (same
        contract as ``OpenAIAdapter``); unusable labels map to a data route.
        """
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=self.ROUTE_MAX_TOKENS,
                system='Classify into one of: "text_to_sql", "rag", "hybrid", "conversation". Return only valid JSON: {"route": "<label>"}',
                messages=[{"role": "user", "content": query}],
            )
        except Exception as exc:
            logger.exception("Anthropic classify_route failed", extra={"model": self.model})
            raise AnthropicRequestError() from exc
        return parse_route(self._text(response))

    async def rewrite_query(self, prompt: str) -> str:
        """Rewrite an ambiguous query into a fully explicit one."""
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=200,
                system="Viết lại câu hỏi thành câu hoàn chỉnh, tường minh dựa trên lịch sử hội thoại. Chỉ trả về đúng một câu.",
                messages=[{"role": "user", "content": prompt}],
            )
            return self._text(response) or prompt
        except Exception:
            logger.warning("Anthropic rewrite_query failed; using the original query", exc_info=True)
            return prompt
