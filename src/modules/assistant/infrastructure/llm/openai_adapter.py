import hashlib
import logging
from openai import AsyncOpenAI
from typing import AsyncGenerator, Optional, Dict, Any
from src.modules.assistant.domain.ports.i_llm_service import ILLMService
from src.modules.assistant.domain.errors import (
    OpenAIRequestError,
)
from src.modules.assistant.infrastructure.llm.llm_common import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    TRUNCATION_NOTICE,
    build_system_prompt,
    parse_route,
)

logger = logging.getLogger(__name__)

# Characters of a request hashed into its prompt_cache_key. Well inside the static
# part of the SQL prompts (GENERATION_RULES alone is ~19k characters).
_CACHE_KEY_PREFIX_CHARS = 4000


class OpenAIAdapter(ILLMService):
    """OpenAI implementation of LLM service"""

    # SQL plans can contain several CTEs/queries. Reasoning and visible output
    # share the completion budget, so 1,000 tokens can produce incomplete plans.
    INTERNAL_COMPLETION_TOKENS = 8192
    RESPONSE_COMPLETION_TOKENS = 4096

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        client: AsyncOpenAI | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.api_key = api_key
        self.model = model
        # The SDK default timeout is 10 minutes, far above the graph's own budgets.
        self._client = client or AsyncOpenAI(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )

    def _response_token_budget(self, context: Optional[Dict[str, Any]]) -> int:
        if context is None:
            return self.INTERNAL_COMPLETION_TOKENS
        requested = context.get("max_completion_tokens") or self.RESPONSE_COMPLETION_TOKENS
        return min(int(requested), self.RESPONSE_COMPLETION_TOKENS)

    def _log_usage(self, call: str, usage: Any) -> None:
        """Log token usage, including the prompt-cache hit OpenAI applies automatically.

        Cached tokens are still counted as input in OpenAI's usage charts but are
        billed at the cached-input rate. The numbers are in the message itself (not
        only in ``extra``) so a plain-text formatter shows them.
        """
        if not usage:
            return

        def count(source: Any, name: str) -> int:
            value = getattr(source, name, None)
            return value if isinstance(value, int) else 0

        prompt = count(usage, "prompt_tokens")
        completion = count(usage, "completion_tokens")
        cached = count(getattr(usage, "prompt_tokens_details", None), "cached_tokens")
        reasoning = count(getattr(usage, "completion_tokens_details", None), "reasoning_tokens")
        logger.info(
            "LLM usage [%s] model=%s prompt=%d cached=%d (%.0f%%) completion=%d reasoning=%d",
            call,
            self.model,
            prompt,
            cached,
            cached * 100 / prompt if prompt else 0,
            completion,
            reasoning,
            extra={
                "llm_call": call,
                "model": self.model,
                "prompt_tokens": prompt,
                "cached_tokens": cached,
                "completion_tokens": completion,
                "reasoning_tokens": reasoning,
                "total_tokens": count(usage, "total_tokens") or prompt + completion,
            },
        )

    @staticmethod
    def _prompt_cache_key(messages: list) -> str:
        """Stable routing key shared by requests that start with the same static text.

        OpenAI caches prompt prefixes automatically; on models before GPT-5.6 a
        ``prompt_cache_key`` also routes requests with the same prefix to the same
        cache. Hashing the first characters of the request (system message plus the
        start of the first user message) groups e.g. every SQL generation call, which
        all begin with SQLPrompt.GENERATION_RULES, without naming call sites. Only a
        digest is sent, never prompt text.
        """
        head = "\x1f".join(str(message.get("content", "")) for message in messages[:2])
        digest = hashlib.sha256(head[:_CACHE_KEY_PREFIX_CHARS].encode("utf-8")).hexdigest()
        return f"ai-assistant-{digest[:16]}"

    def _build_messages(self, prompt: str, context: Optional[Dict[str, Any]]) -> list:
        messages = []
        if context and 'conversation_history' in context:
            for msg in context['conversation_history']:
                messages.append({"role": msg['role'], "content": msg['content']})
        messages.append({"role": "user", "content": prompt})
        system_message = build_system_prompt(context)
        messages.insert(0, {"role": "system", "content": system_message})
        return messages

    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate response using OpenAI"""
        try:
            messages = self._build_messages(prompt, context)
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=self._response_token_budget(context),
                prompt_cache_key=self._prompt_cache_key(messages),
            )
            self._log_usage("generate", getattr(response, "usage", None))
            choice = response.choices[0]
            if getattr(choice, "finish_reason", None) == "length" or not choice.message.content:
                logger.warning("LLM returned incomplete or empty output", extra={"model": self.model})
                raise OpenAIRequestError()
            return choice.message.content.strip()
        except OpenAIRequestError:
            raise
        except Exception as exc:
            logger.exception("OpenAI generate_response failed", extra={"model": self.model})
            raise OpenAIRequestError() from exc

    async def stream_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> AsyncGenerator[str, None]:
        """Stream response tokens using OpenAI.

        When the provider stops with ``finish_reason == "length"`` after output
        was already sent, raising would discard an otherwise usable answer, so a
        truncation notice is appended instead. Truncation with no output at all
        (reasoning consumed the whole budget) is still an error.
        """
        emitted = False
        try:
            messages = self._build_messages(prompt, context)
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=self._response_token_budget(context),
                prompt_cache_key=self._prompt_cache_key(messages),
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                self._log_usage("stream", getattr(chunk, "usage", None))
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta.content:
                    emitted = True
                    yield delta.content
                if getattr(choice, "finish_reason", None) == "length":
                    logger.warning("LLM stream truncated by token limit", extra={"model": self.model})
                    if not emitted:
                        raise OpenAIRequestError()
                    yield TRUNCATION_NOTICE
        except OpenAIRequestError:
            raise
        except Exception as exc:
            logger.exception("OpenAI stream_response failed", extra={"model": self.model})
            raise OpenAIRequestError() from exc

    async def analyze_intent(self, message: str) -> str:
        """Analyze intent of user message"""
        try:
            prompt = f"""
            Phân tích ý định của tin nhắn người dùng này và phân loại nó vào một trong những danh mục sau:
            - revenue: câu hỏi về doanh thu, bán hàng, lợi nhuận
            - profit: câu hỏi về lợi nhuận, lỗ, biên lợi nhuận
            - customer: câu hỏi về khách hàng, đối tác, người dùng
            - inventory: câu hỏi về kho hàng, sản phẩm, tồn kho
            - sales: câu hỏi về giao dịch bán hàng, đơn đặt hàng
            - trend: câu hỏi về các thay đổi, xu hướng, tăng trưởng
            - comparison: câu hỏi so sánh các thứ khác nhau
            - report: yêu cầu báo cáo, tóm tắt, phân tích
            - general: cuộc trò chuyện tổng quát hoặc các chủ đề khác

            Message: "{message}"

            Return only the category name, nothing else.
            """

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=50,
            )
            self._log_usage("analyze_intent", getattr(response, "usage", None))

            intent = response.choices[0].message.content.strip().lower()
            return intent

        except Exception:
            logger.warning("OpenAI analyze_intent failed; using 'general'", exc_info=True)
            return "general"  # fallback

    async def classify_route(self, query: str) -> str:
        """Classify query into routing label using structured JSON output."""
        system_prompt = (
            "Bạn là bộ phân loại định tuyến cho chatbot phân tích kinh doanh của một cửa hàng.\n"
            "Phân loại câu hỏi của người dùng vào đúng một nhãn định tuyến sau:\n"
            '- "text_to_sql": câu hỏi liên quan đến số liệu bán hàng của cửa hàng, '
            "bao gồm doanh thu, đơn hàng, sản phẩm, công nợ, và thông tin khách hàng\n"
            '- "rag": câu hỏi bên lề, liên quan đến các luật hoặc chính sách kinh doanh tại Việt Nam '
            "(ví dụ: quy định thuế, luật thương mại, chính sách hoàn trả hàng hóa)\n"
            '- "hybrid": câu hỏi liên quan đến cả số liệu bán hàng lẫn luật/chính sách kinh doanh\n\n'
            '- "conversation": chào hỏi, cảm ơn, xác nhận, tạm biệt hoặc trò chuyện thông thường '
            "không cần tra cứu dữ liệu\n\n"
            "Ví dụ:\n"
            '- "Doanh thu tháng 3/2025 là bao nhiêu?" → {"route": "text_to_sql"}\n'
            '- "Top 5 khách hàng mua nhiều nhất năm nay?" → {"route": "text_to_sql"}\n'
            '- "Anh Minh còn nợ bao nhiêu tiền?" → {"route": "text_to_sql"}\n'
            '- "Thuế VAT đối với hàng hóa xuất khẩu là bao nhiêu?" → {"route": "rag"}\n'
            '- "Chính sách đổi trả hàng theo quy định pháp luật như thế nào?" → {"route": "rag"}\n'
            '- "Doanh thu của anh Minh có vượt ngưỡng phải nộp thuế không?" → {"route": "hybrid"}\n\n'
            '- "Cảm ơn bạn" → {"route": "conversation"}\n'
            '- "Xin chào" → {"route": "conversation"}\n\n'
            'Chỉ trả về JSON hợp lệ: {"route": "<nhãn>"}'
        )
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=512,
            )
        except Exception as exc:
            logger.exception("OpenAI classify_route failed", extra={"model": self.model})
            raise OpenAIRequestError() from exc
        self._log_usage("classify_route", getattr(response, "usage", None))
        return parse_route(response.choices[0].message.content)

    async def rewrite_query(self, prompt: str) -> str:
        """Rewrite an ambiguous query into a fully explicit one."""
        system_prompt = (
            "Bạn là chuyên gia cần làm rõ câu hỏi cho chatbot phân tích kinh doanh.\n\n"
            "Nhiệm vụ: Dựa vào lịch sử hội thoại bên dưới, viết lại câu hỏi cuối "
            "thành một câu hoàn chỉnh và tường minh — thay thế tất cả đại từ, tham chiếu "
            "mơ hồ ('anh ấy', 'loại đó', 'tháng đó', 'cái này', ...) bằng thực thể cụ thể "
            "trích từ lịch sử.\n\n"
            "Quy tắc:\n"
            "- Chỉ viết lại câu hỏi, không trả lời\n"
            "- Giữ nguyên tiếng Việt\n"
            "- Nếu câu hỏi đã rõ ràng và không có tham chiếu mơ hồ, trả về nguyên văn\n"
            "- Không thêm thông tin không có trong lịch sử\n"
            "- Chỉ trả về đúng một câu, không giải thích"
        )
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=2048,
        )
        self._log_usage("rewrite_query", getattr(response, "usage", None))
        return response.choices[0].message.content.strip()
