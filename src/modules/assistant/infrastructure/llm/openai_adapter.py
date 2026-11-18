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
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=self._build_messages(prompt, context),
                max_completion_tokens=self._response_token_budget(context),
            )
            usage = response.usage
            if usage:
                logger.info(
                    "LLM usage",
                    extra={
                        "model": self.model,
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                    },
                )
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
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=self._build_messages(prompt, context),
                max_completion_tokens=self._response_token_budget(context),
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if chunk.usage:
                    logger.info(
                        "LLM streaming usage",
                        extra={
                            "model": self.model,
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                            "total_tokens": chunk.usage.total_tokens,
                        },
                    )
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
        return response.choices[0].message.content.strip()
