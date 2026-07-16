import hashlib
import json
import logging
from typing import Any, AsyncGenerator, Dict, Optional
from uuid import UUID

from src.application.agent.agent_service import AgentService
from src.domain.constants.search_config import SearchConfig
from src.domain.entities.message import Message
from src.domain.entities.conversation import Conversation
from src.domain.interfaces.i_cache_service import ICacheService
from src.domain.repositories.i_conversation_repository import IConversationRepository

_CACHE_TTL = 3600  # 1 hour
logger = logging.getLogger(__name__)


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

    async def execute(self, conversation_id: UUID, user_message: str) -> Dict[str, Any]:
        # ── 1. Load or create conversation ───────────────────────────────
        conversation_data = await self.conversation_repo.get_conversation(conversation_id, SearchConfig.HISTORY_WINDOW)
        if not conversation_data:
            conversation_data = await self.create_conversation(
                title=self._generate_title(user_message)
            )

        conversation = self._dict_to_conversation(conversation_data)
        is_first_message = len(conversation.messages) == 0

        # ── 2. Cache lookup ───────────────────────────────────────────────
        cache_key = self._make_cache_key(user_message, conversation)
        cached_payload = await self._get_cached(cache_key)
        if cached_payload:
            return await self._respond_from_cache(
                cached_payload, conversation_id, user_message, is_first_message
            )

        # ── 3. Run agent graph ────────────────────────────────────────────
        final_state = await self.agent_service.invoke(
            user_message, conversation.messages, thread_id=str(conversation_id)
        )

        response_content = final_state.get("response") or "Xin lỗi, tôi không có đủ thông tin để trả lời câu hỏi này."
        context = final_state.get("context") or {}
        analyzed = final_state.get("analyzed")
        sql_query = final_state.get("sql_query", None)
        intent = context.get("intent", analyzed.primary_intent.value if analyzed else "unknown")
        metadata = {
            "has_data": context.get("has_data", True),
            "used_fallback": context.get("used_fallback", False),
            "fallback_warning": context.get("fallback_warning"),
            "tool_used": final_state.get("tool_name"),
            "tool_success": final_state.get("tool_success"),
            "tool_error_code": final_state.get("tool_error_code"),
            "sql_query": sql_query,
            "trace_id": final_state.get("trace_id"),
            "node_metrics": final_state.get("node_metrics", []),
            "tool_calls": final_state.get("tool_calls", []),
            "citations": final_state.get("citations", []),
            "plan": final_state.get("plan", []),
            "evaluation": final_state.get("evaluation"),
            "iteration": final_state.get("iteration", 0),
            "needs_clarification": final_state.get("needs_clarification", False),
            "awaiting_approval": final_state.get("awaiting_approval", False),
            "pending_action": final_state.get("pending_action"),
        }

        # ── 4. Persist messages ───────────────────────────────────────────
        _, assistant_msg = await self._persist_messages(
            conversation_id, user_message, response_content, metadata=metadata
        )

        # ── 5. Update title on first exchange ────────────────────────────
        if is_first_message:
            await self.conversation_repo.update_conversation(
                conversation_id, {"title": self._generate_title(user_message)}
            )

        # ── 6. Store in cache for future identical queries ────────────────
        await self.cache_service.set(
            cache_key,
            json.dumps({"response": response_content, "intent": intent, "metadata": metadata}),
            ttl=_CACHE_TTL,
        )

        return {
            "conversation_id": str(conversation_id),
            "response": response_content,
            "intent": intent,
            "timestamp": assistant_msg.timestamp.isoformat(),
            "metadata": metadata,
        }

    async def execute_stream(self, conversation_id: UUID, user_message: str) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted strings for the streaming chat endpoint.

        Event types emitted:
            {"type": "status",  "step": str, "message": str}   — pipeline progress
            {"type": "token",   "content": str}                  — LLM output token
            {"type": "done",    "conversation_id": str, "intent": str,
                                "timestamp": str, "metadata": dict}
            {"type": "error",   "message": str}
        """
        def sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            # ── 1. Load or create conversation ───────────────────────────
            conversation_data = await self.conversation_repo.get_conversation(
                conversation_id, SearchConfig.HISTORY_WINDOW
            )
            if not conversation_data:
                conversation_data = await self.create_conversation(
                    title=self._generate_title(user_message)
                )
            conversation = self._dict_to_conversation(conversation_data)
            is_first_message = len(conversation.messages) == 0

            # ── 2. Cache lookup ──────────────────────────────────────────
            cache_key = self._make_cache_key(user_message, conversation)
            cached_payload = await self._get_cached(cache_key)

            if cached_payload:
                yield sse({"type": "status", "step": "cache", "message": "Tìm thấy câu trả lời trong cache..."})
                # Simulate streaming by yielding word-by-word
                words = cached_payload["response"].split(" ")
                for i, word in enumerate(words):
                    suffix = " " if i < len(words) - 1 else ""
                    yield sse({"type": "token", "content": word + suffix})
                _, assistant_msg = await self._persist_messages(
                    conversation_id, user_message, cached_payload["response"], metadata=cached_payload["metadata"]
                )
                if is_first_message:
                    await self.conversation_repo.update_conversation(
                        conversation_id, {"title": self._generate_title(user_message)}
                    )
                yield sse({
                    "type": "done",
                    "conversation_id": str(conversation_id),
                    "intent": cached_payload["intent"],
                    "timestamp": assistant_msg.timestamp.isoformat(),
                    "metadata": {**cached_payload["metadata"], "cache_hit": True},
                })
                return

            # ── 3. Run context-only agent graph ──────────────────────────
            yield sse({"type": "status", "step": "routing", "message": "Đang phân tích câu hỏi..."})
            final_state = await self.agent_service.invoke_for_context(
                user_message, conversation.messages, thread_id=str(conversation_id)
            )

            context = final_state.get("context") or {}
            analyzed = final_state.get("analyzed")
            sql_query = final_state.get("sql_query", None)
            intent = context.get("intent", analyzed.primary_intent.value if analyzed else "unknown")
            metadata = {
                "has_data": context.get("has_data", True),
                "used_fallback": context.get("used_fallback", False),
                "fallback_warning": context.get("fallback_warning"),
                "tool_used": final_state.get("tool_name"),
                "tool_success": final_state.get("tool_success"),
                "tool_error_code": final_state.get("tool_error_code"),
                "sql_query": sql_query,
                "trace_id": final_state.get("trace_id"),
                "node_metrics": final_state.get("node_metrics", []),
                "tool_calls": final_state.get("tool_calls", []),
                "citations": final_state.get("citations", []),
                "plan": final_state.get("plan", []),
                "evaluation": final_state.get("evaluation"),
                "iteration": final_state.get("iteration", 0),
                "needs_clarification": final_state.get("needs_clarification", False),
                "awaiting_approval": final_state.get("awaiting_approval", False),
                "pending_action": final_state.get("pending_action"),
            }

            # ── 4. Stream LLM response tokens ────────────────────────────
            response_chunks: list[str] = []
            if final_state.get("needs_clarification"):
                clarification = final_state.get("response") or final_state.get("clarification_question") or "Bạn có thể nói rõ yêu cầu không?"
                response_chunks.append(clarification)
                yield sse({"type": "status", "step": "clarification", "message": "Cần bổ sung thông tin..."})
                yield sse({"type": "token", "content": clarification})
            else:
                yield sse({"type": "status", "step": "generating", "message": "Đang tạo câu trả lời..."})
                async for token in self.agent_service.stream_response(user_message, context):
                    response_chunks.append(token)
                    yield sse({"type": "token", "content": token})

            response_content = "".join(response_chunks) or "Xin lỗi, tôi không có đủ thông tin để trả lời câu hỏi này."
            source_ids = [source.get("id") for source in metadata["citations"] if source.get("id")]
            metadata["response_evaluation"] = {
                "citation_verified": (
                    not source_ids
                    or any(f"[{source_id}]" in response_content for source_id in source_ids)
                ),
                "mode": "streaming_post_check",
            }

            # ── 5. Persist messages ──────────────────────────────────────
            _, assistant_msg = await self._persist_messages(
                conversation_id, user_message, response_content, metadata=metadata
            )
            if is_first_message:
                await self.conversation_repo.update_conversation(
                    conversation_id, {"title": self._generate_title(user_message)}
                )

            # ── 6. Cache for future identical queries ────────────────────
            await self.cache_service.set(
                cache_key,
                json.dumps({"response": response_content, "intent": intent, "metadata": metadata}),
                ttl=_CACHE_TTL,
            )

            yield sse({
                "type": "done",
                "conversation_id": str(conversation_id),
                "intent": intent,
                "timestamp": assistant_msg.timestamp.isoformat(),
                "metadata": metadata,
            })

        except Exception:
            logger.exception("Streaming agent execution failed", extra={"conversation_id": str(conversation_id)})
            # Never expose database/provider/internal exception details to clients.
            yield sse({
                "type": "error",
                "message": "Không thể xử lý yêu cầu lúc này. Vui lòng thử lại sau.",
            })

    async def _respond_from_cache(
        self,
        payload: Dict[str, Any],
        conversation_id: UUID,
        user_message: str,
        is_first_message: bool,
    ) -> Dict[str, Any]:
        _, assistant_msg = await self._persist_messages(
            conversation_id, user_message, payload["response"], metadata=payload["metadata"]
        )
        if is_first_message:
            await self.conversation_repo.update_conversation(
                conversation_id, {"title": self._generate_title(user_message)}
            )
        return {
            "conversation_id": str(conversation_id),
            "response": payload["response"],
            "intent": payload["intent"],
            "timestamp": assistant_msg.timestamp.isoformat(),
            "metadata": {**payload["metadata"], "cache_hit": True},
        }

    async def _persist_messages(
        self, conversation_id: UUID, user_message: str, response_content: str, metadata: Optional[Dict[str, Any]] = None
    ):
        user_msg = Message(conversation_id=conversation_id, content=user_message, role="user", metadata=metadata or {})
        assistant_msg = Message(conversation_id=conversation_id, content=response_content, role="assistant", metadata=metadata or {})
        await self.conversation_repo.add_message(conversation_id, self._message_to_dict(user_msg))
        await self.conversation_repo.add_message(conversation_id, self._message_to_dict(assistant_msg))
        return user_msg, assistant_msg

    async def _get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        raw = await self.cache_service.get(key)
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
            "version": 2,
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(serialized.encode()).hexdigest()[:32]
        return f"chat:response:{digest}"

    # ─────────────────────────────────────────────────────────────────────
    # Private helpers
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
        return {
            "id": str(message.id) if message.id else None,
            "conversation_id": str(message.conversation_id),
            "content": message.content,
            "role": message.role,
            "timestamp": message.timestamp,
            "metadata": message.metadata,
        }

    @staticmethod
    def _generate_title(message: str) -> str:
        words = message.split()[:6]
        title = " ".join(words)
        return (title[:47] + "...") if len(title) > 50 else title or "New Conversation"
