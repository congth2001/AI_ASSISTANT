import logging

from src.modules.conversations.domain.entities.message import Message
from src.modules.assistant.domain.ports.i_llm_service import ILLMService

logger = logging.getLogger(__name__)

# Minimum turns needed before contextualization is worth an LLM call
_MIN_HISTORY_MESSAGES = 2


class QueryContextualizer:
    """
    Rewrites an ambiguous user query into a fully explicit one using
    conversation history.

    LLM is invoked only when history is non-trivial; otherwise the
    original query is returned unchanged to avoid unnecessary latency.
    """

    def __init__(self, llm_service: ILLMService, max_history_messages: int = 6):
        self._llm = llm_service
        self._max_history = max_history_messages

    async def resolve(self, query: str, messages: list[Message]) -> str:
        """
        Return a fully explicit rewrite of `query`, or the original query
        when history is too short to be useful or the LLM call fails.
        """
        if len(messages) < _MIN_HISTORY_MESSAGES:
            return query

        question, marker, report_context = query.partition("\nNgữ cảnh báo cáo đang xem:")
        history_text = self._format_history(messages)
        prompt = (
            f"Lịch sử hội thoại:\n{history_text}\n\n"
            f"Câu hỏi cần làm rõ: {question}"
        )

        try:
            resolved = await self._llm.rewrite_query(prompt)
            return (resolved + marker + report_context) if resolved else query
        except Exception:
            logger.warning(
                "Query contextualization failed; using the original query", exc_info=True
            )
            return query

    def _format_history(self, messages: list[Message]) -> str:
        # messages is DESC (newest first); take first N then reverse for chronological output
        recent = list(reversed(messages[:self._max_history]))
        lines = []
        for m in recent:
            role = "Người dùng" if m.role == "user" else "Trợ lý"
            lines.append(f"{role}: {m.content}")
        return "\n".join(lines)
