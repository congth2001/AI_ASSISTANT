import asyncio
import hashlib
import json
import logging
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import UUID

from src.common.cache_keys import CHAT_RESPONSE_CACHE_PREFIX  # re-exported for ETL/CLI imports
from src.common.domain.time import now_vietnam
from src.modules.assistant.application.agent.agent_service import AgentService
from src.modules.assistant.domain.constants.search_config import SearchConfig
from src.modules.assistant.domain.errors import (
    GuestBusinessDataForbiddenError,
    StreamingResponseFailedError,
)
from src.modules.assistant.domain.ports.i_cache_service import ICacheService
from src.modules.conversations.domain.entities.conversation import Conversation
from src.modules.conversations.domain.entities.message import Message
from src.modules.conversations.domain.errors import ConversationNotFoundError
from src.modules.conversations.domain.repositories.i_conversation_repository import IConversationRepository

__all__ = ["ChatUseCase", "CHAT_RESPONSE_CACHE_PREFIX"]

_CACHE_TTL = 3600  # 1 hour
_FALLBACK_RESPONSE = "Xin lỗi, tôi không có đủ thông tin để trả lời câu hỏi này."
_CLARIFICATION_FALLBACK = "Bạn có thể nói rõ yêu cầu không?"
# Tools whose answers come from the sales tables. The ETL refreshes those tables
# and the cache key is scoped to one conversation plus its history, so a stored
# answer is almost never reused and could silently show stale numbers when it is.
_NON_CACHEABLE_TOOLS = frozenset({"text_to_sql", "hybrid"})
# Keys of the pre-cleanup agent state that API clients may still read from
# message metadata. The agent no longer produces them; they stay as constants.
_LEGACY_METADATA = {
    "plan": [],
    "iteration": 0,
    "awaiting_approval": False,
    "pending_action": None,
}
logger = logging.getLogger(__name__)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class _StreamTurn:
    """Mutable bookkeeping for one streamed exchange.

    Lets the cancellation handler persist whatever was already shown to the
    user (the user message plus the partial answer).
    """

    conversation_id: UUID
    user_message: str
    user_id: Optional[str]
    loaded: bool = False
    is_first_message: bool = False
    persisted: bool = False
    chunks: List[str] = field(default_factory=list)


class ChatUseCase:
    """
    Thin orchestrator for the chat pipeline:
        1. Load / create conversation
        2. Check response cache; skip agent on hit
        3. Delegate query analysis + tool execution + response to AgentService
        4. Persist messages
        5. Update conversation title on first exchange
    """

    def __init__(
        self,
        agent_service: AgentService,
        conversation_repo: IConversationRepository,
        cache_service: ICacheService
    ):
        self.agent_service = agent_service
        self.conversation_repo = conversation_repo
        self.cache_service = cache_service
        # Strong references so fire-and-forget persistence is not garbage collected.
        self._background_tasks: set[asyncio.Task] = set()

    # ─────────────────────────────────────────────────────────────────────
    # Guest (stateless)
    # ─────────────────────────────────────────────────────────────────────
    async def authorize_guest_query(self, user_message: str) -> None:
        route = await self.agent_service.classify_route(user_message)
        if route != "conversation":
            raise GuestBusinessDataForbiddenError()

    async def execute_guest(self, user_message: str) -> Dict[str, Any]:
        await self.authorize_guest_query(user_message)
        chunks = [token async for token in self.agent_service.stream_stateless_conversation(user_message)]
        return {
            "conversation_id": None,
            "response": "".join(chunks),
            "intent": "conversation",
            "timestamp": now_vietnam().isoformat(),
            "metadata": {"stateless": True, "data_access": False},
        }

    async def execute_guest_stream(self, user_message: str) -> AsyncGenerator[str, None]:
        """Stream a single guest answer without reading or writing conversation data.

        Always ends with ``done`` or ``error``. Nothing is persisted, so a client
        disconnect (``CancelledError``/``GeneratorExit``) simply propagates.
        """
        try:
            yield _sse({"type": "status", "step": "generating", "message": "Đang tạo câu trả lời..."})
            async for token in self.agent_service.stream_stateless_conversation(user_message):
                yield _sse({"type": "token", "content": token})
            yield _sse({
                "type": "done",
                "conversation_id": None,
                "intent": "conversation",
                "timestamp": now_vietnam().isoformat(),
                "metadata": {"stateless": True, "data_access": False},
            })
        except Exception:
            logger.exception("Guest streaming failed")
            yield _sse({"type": "error", "message": StreamingResponseFailedError().message})

    # ─────────────────────────────────────────────────────────────────────
    # Authenticated chat
    # ─────────────────────────────────────────────────────────────────────
    async def execute(
        self, conversation_id: UUID, user_message: str, user_id: Optional[str]
    ) -> Dict[str, Any]:
        conversation = await self._load_conversation(conversation_id, user_id)
        is_first_message = not conversation.messages

        cache_key = self._make_cache_key(user_message, conversation)
        cached_payload = await self._get_cached(cache_key)
        if cached_payload:
            return await self._respond_from_cache(
                cached_payload, conversation_id, user_message, is_first_message, user_id
            )

        final_state = await self.agent_service.invoke(
            user_message, conversation.messages, thread_id=str(conversation_id)
        )
        response_content = final_state.get("response") or _FALLBACK_RESPONSE
        context = final_state.get("context") or {}
        intent = self._resolve_intent(final_state, context)
        metadata = self._build_metadata(final_state, context)

        assistant_msg = await self._persist_exchange(
            conversation_id, user_message, response_content, metadata, user_id, is_first_message
        )
        await self._cache_response(cache_key, response_content, intent, metadata)

        return {
            "conversation_id": str(conversation_id),
            "response": response_content,
            "intent": intent,
            "timestamp": assistant_msg.timestamp.isoformat(),
            "metadata": metadata,
        }

    async def execute_stream(
        self, conversation_id: UUID, user_message: str, user_id: Optional[str]
    ) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted strings for the streaming chat endpoint.

        Event types emitted:
            {"type": "status",  "step": str, "message": str}   — pipeline progress
            {"type": "token",   "content": str}                  — LLM output token
            {"type": "done",    "conversation_id": str, "intent": str,
                                "timestamp": str, "metadata": dict}
            {"type": "error",   "message": str}

        The stream always ends with ``done`` or ``error`` unless the client goes
        away. On disconnect/stop (``CancelledError``/``GeneratorExit``) the user
        message and the partial answer are saved with ``{"interrupted": true}``
        before the cancellation is re-raised.
        """
        turn = _StreamTurn(conversation_id, user_message, user_id)
        try:
            conversation = await self._load_conversation(conversation_id, user_id)
            turn.loaded = True
            turn.is_first_message = not conversation.messages

            cache_key = self._make_cache_key(user_message, conversation)
            cached_payload = await self._get_cached(cache_key)
            events = (
                self._stream_cached(turn, cached_payload)
                if cached_payload
                else self._stream_fresh(turn, conversation, cache_key)
            )
            async with aclosing(events):
                async for event in events:
                    yield event
        except (asyncio.CancelledError, GeneratorExit):
            await self._persist_interrupted(turn)
            raise
        except Exception:
            # Covers failures after tokens were already streamed (e.g. persisting
            # the exchange): the client still gets a terminal `error` event.
            logger.exception("Streaming agent execution failed", extra={"conversation_id": str(conversation_id)})
            # Never expose database/provider/internal exception details to clients.
            yield _sse({"type": "error", "message": StreamingResponseFailedError().message})

    async def _stream_cached(self, turn: _StreamTurn, payload: Dict[str, Any]) -> AsyncGenerator[str, None]:
        yield _sse({"type": "status", "step": "cache", "message": "Tìm thấy câu trả lời trong cache..."})
        words = payload["response"].split(" ")  # simulate streaming word by word
        for index, word in enumerate(words):
            token = word + (" " if index < len(words) - 1 else "")
            turn.chunks.append(token)
            yield _sse({"type": "token", "content": token})
        assistant_msg = await self._persist_exchange(
            turn.conversation_id, turn.user_message, payload["response"],
            payload["metadata"], turn.user_id, turn.is_first_message, turn=turn,
        )
        yield _sse({
            "type": "done",
            "conversation_id": str(turn.conversation_id),
            "intent": payload["intent"],
            "timestamp": assistant_msg.timestamp.isoformat(),
            "metadata": {**payload["metadata"], "cache_hit": True},
        })

    async def _stream_fresh(
        self, turn: _StreamTurn, conversation: Conversation, cache_key: str
    ) -> AsyncGenerator[str, None]:
        yield _sse({"type": "status", "step": "routing", "message": "Đang phân tích câu hỏi..."})
        final_state = await self.agent_service.invoke_for_context(
            turn.user_message, conversation.messages, thread_id=str(turn.conversation_id)
        )
        context = final_state.get("context") or {}
        intent = self._resolve_intent(final_state, context)
        metadata = self._build_metadata(final_state, context)

        async for event in self._stream_answer(turn, final_state, context):
            yield event

        response_content = "".join(turn.chunks) or _FALLBACK_RESPONSE
        metadata["response_evaluation"] = {
            "citation_verified": self._citation_verified(metadata["citations"], response_content),
            "mode": "streaming_post_check",
        }
        assistant_msg = await self._persist_exchange(
            turn.conversation_id, turn.user_message, response_content,
            metadata, turn.user_id, turn.is_first_message, turn=turn,
        )
        await self._cache_response(cache_key, response_content, intent, metadata)
        yield _sse({
            "type": "done",
            "conversation_id": str(turn.conversation_id),
            "intent": intent,
            "timestamp": assistant_msg.timestamp.isoformat(),
            "metadata": metadata,
        })

    async def _stream_answer(
        self, turn: _StreamTurn, final_state: Dict[str, Any], context: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Emit the answer: a prepared message (tool error/clarification) or LLM tokens."""
        if context.get("response_mode") == "tool_error":
            message = final_state["response"]
            turn.chunks.append(message)
            yield _sse({"type": "token", "content": message})
        elif final_state.get("needs_clarification"):
            clarification = (
                final_state.get("response")
                or final_state.get("clarification_question")
                or _CLARIFICATION_FALLBACK
            )
            turn.chunks.append(clarification)
            yield _sse({"type": "status", "step": "clarification", "message": "Cần bổ sung thông tin..."})
            yield _sse({"type": "token", "content": clarification})
        else:
            yield _sse({"type": "status", "step": "generating", "message": "Đang tạo câu trả lời..."})
            async for token in self.agent_service.stream_response(turn.user_message, context):
                turn.chunks.append(token)
                yield _sse({"type": "token", "content": token})

    # ─────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────
    async def _load_conversation(self, conversation_id: UUID, user_id: Optional[str]) -> Conversation:
        data = await self.conversation_repo.get_conversation(
            conversation_id, SearchConfig.HISTORY_WINDOW, user_id
        )
        if not data:
            raise ConversationNotFoundError()
        return self._dict_to_conversation(data)

    async def _persist_exchange(
        self,
        conversation_id: UUID,
        user_message: str,
        response_content: str,
        assistant_metadata: Optional[Dict[str, Any]],
        user_id: Optional[str],
        is_first_message: bool,
        turn: Optional[_StreamTurn] = None,
    ) -> Message:
        """Save the user + assistant messages in one transaction, then set the title.

        Metadata describes the assistant answer only; the user message has none.
        ``turn`` is marked persisted right after the messages commit, before the
        title update, so a cancellation during the title update cannot make the
        interrupt handler save the same exchange a second time.
        """
        user_msg = Message(conversation_id=conversation_id, content=user_message, role="user")
        assistant_msg = Message(
            conversation_id=conversation_id,
            content=response_content,
            role="assistant",
            metadata=assistant_metadata,
        )
        await self.conversation_repo.add_messages(
            conversation_id, [self._message_to_dict(user_msg), self._message_to_dict(assistant_msg)]
        )
        if turn is not None:
            turn.persisted = True
        await self._set_title_if_first(conversation_id, user_message, user_id, is_first_message)
        return assistant_msg

    async def _set_title_if_first(
        self, conversation_id: UUID, user_message: str, user_id: Optional[str], is_first_message: bool
    ) -> None:
        if is_first_message:
            await self.conversation_repo.update_conversation(
                conversation_id, {"title": self._generate_title(user_message)}, user_id
            )

    async def _persist_interrupted(self, turn: _StreamTurn) -> None:
        """Save what the user already saw after a disconnect/stop.

        The caller is being cancelled, and with anyio a cancelled scope cancels
        every further ``await``. The write therefore runs as its own task
        behind ``shield`` so it can finish even if this coroutine is cancelled
        again; failures are logged by the task itself.
        """
        if not turn.loaded or turn.persisted:
            return
        turn.persisted = True
        partial = "".join(turn.chunks)
        task = asyncio.ensure_future(self._save_interrupted(turn, partial))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        try:
            await asyncio.shield(task)
        except BaseException:
            # Cancelled again while waiting; persistence continues in `task`.
            pass

    async def _save_interrupted(self, turn: _StreamTurn, partial: str) -> None:
        try:
            if partial:
                await self._persist_exchange(
                    turn.conversation_id, turn.user_message, partial,
                    {"interrupted": True}, turn.user_id, turn.is_first_message,
                )
            else:
                await self.conversation_repo.add_messages(
                    turn.conversation_id,
                    [self._message_to_dict(Message(
                        conversation_id=turn.conversation_id, content=turn.user_message,
                        role="user", metadata={"interrupted": True},
                    ))],
                )
                await self._set_title_if_first(
                    turn.conversation_id, turn.user_message, turn.user_id, turn.is_first_message
                )
        except Exception:
            logger.exception(
                "Could not persist interrupted chat exchange",
                extra={"conversation_id": str(turn.conversation_id)},
            )

    # ─────────────────────────────────────────────────────────────────────
    # Cache
    # ─────────────────────────────────────────────────────────────────────
    async def _respond_from_cache(
        self,
        payload: Dict[str, Any],
        conversation_id: UUID,
        user_message: str,
        is_first_message: bool,
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        assistant_msg = await self._persist_exchange(
            conversation_id, user_message, payload["response"],
            payload["metadata"], user_id, is_first_message,
        )
        return {
            "conversation_id": str(conversation_id),
            "response": payload["response"],
            "intent": payload["intent"],
            "timestamp": assistant_msg.timestamp.isoformat(),
            "metadata": {**payload["metadata"], "cache_hit": True},
        }

    @staticmethod
    def _is_cacheable(metadata: Dict[str, Any]) -> bool:
        """Cache only stable answers.

        Never cache clarification requests, failed tool runs (e.g. SQL errors) or
        answers built from the sales tables (`text_to_sql`, `hybrid`): their
        numbers change with every ETL run, and the key is tied to one
        conversation and its history, so those entries are rarely hit anyway.
        """
        return not (
            metadata.get("needs_clarification")
            or metadata.get("tool_success") is False
            or metadata.get("tool_error_code")
            or metadata.get("tool_used") in _NON_CACHEABLE_TOOLS
        )

    async def _cache_response(
        self, key: str, response: str, intent: str, metadata: Dict[str, Any]
    ) -> None:
        """Best-effort write: a cache outage must not fail an answer already given."""
        if not self._is_cacheable(metadata):
            return
        try:
            await self.cache_service.set(
                key,
                json.dumps({"response": response, "intent": intent, "metadata": metadata}),
                ttl=_CACHE_TTL,
            )
        except Exception:
            logger.warning("Could not store chat response in cache", exc_info=True)

    async def _get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            raw = await self.cache_service.get(key)
        except Exception:
            logger.warning("Could not read chat response cache", exc_info=True)
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _make_cache_key(user_message: str, conversation: Conversation) -> str:
        # Responses can depend on user scope and previous turns. Including both
        # prevents a cached answer from leaking into another conversation/user.
        history = [
            {"role": m.role, "content": m.content}
            for m in conversation.messages[:SearchConfig.HISTORY_WINDOW]
        ]
        payload = {
            "query": user_message.strip().lower(),
            "conversation_id": str(conversation.id),
            "user_id": conversation.user_id,
            "history": history,
            # Bump when routing/response semantics change so an old RAG fallback
            # for small talk is not served after deploying the conversation route.
            "version": 6,
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(serialized.encode()).hexdigest()[:32]
        return f"{CHAT_RESPONSE_CACHE_PREFIX}{digest}"

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────
    async def create_conversation(
        self,
        title: str,
        user_id: str = None,
        extra_metadata: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        return await self.conversation_repo.create_conversation({
            "title": title,
            "user_id": user_id,
            "metadata": extra_metadata,
        })

    @staticmethod
    def _resolve_intent(final_state: Dict[str, Any], context: Dict[str, Any]) -> str:
        analyzed = final_state.get("analyzed")
        return context.get("intent", analyzed.primary_intent.value if analyzed else "unknown")

    @staticmethod
    def _build_metadata(final_state: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Assistant-message metadata shared by the streaming and non-streaming paths."""
        return {
            "has_data": context.get("has_data", True),
            "used_fallback": context.get("used_fallback", False),
            "fallback_warning": context.get("fallback_warning"),
            "tool_used": final_state.get("tool_name"),
            "tool_success": final_state.get("tool_success"),
            "tool_error_code": final_state.get("tool_error_code"),
            "sql_query": final_state.get("sql_query"),
            "trace_id": final_state.get("trace_id"),
            "node_metrics": final_state.get("node_metrics", []),
            "tool_calls": final_state.get("tool_calls", []),
            "citations": final_state.get("citations", []),
            "evaluation": final_state.get("evaluation"),
            "needs_clarification": final_state.get("needs_clarification", False),
            **_LEGACY_METADATA,
        }

    @staticmethod
    def _citation_verified(citations: List[Dict[str, Any]], response: str) -> bool:
        source_ids = [source.get("id") for source in citations if source.get("id")]
        return not source_ids or any(f"[{source_id}]" in response for source_id in source_ids)

    def _dict_to_conversation(self, data: Dict[str, Any]) -> Conversation:
        messages = [
            Message(
                id=UUID(m["id"]) if m.get("id") else None,
                conversation_id=UUID(data["id"]),
                content=m.get("content") or "",
                role=m.get("role") or "user",
                timestamp=m.get("created_at"),
            )
            for m in data.get("messages", [])
            if (m.get("content") or "").strip()
        ]
        return Conversation(
            id=UUID(data["id"]),
            user_id=data.get("user_id"),
            title=data.get("title"),
            messages=messages,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            metadata=data.get("metadata"),
        )

    def _message_to_dict(self, message: Message) -> Dict[str, Any]:
        # No "timestamp": the repository assigns strictly increasing timestamps so
        # messages saved in one transaction keep their order.
        return {
            "id": str(message.id) if message.id else None,
            "conversation_id": str(message.conversation_id),
            "content": message.content,
            "role": message.role,
            "metadata": message.metadata,
        }

    @staticmethod
    def _generate_title(message: str) -> str:
        words = message.split()[:6]
        title = " ".join(words)
        return (title[:47] + "...") if len(title) > 50 else title or "New Conversation"
