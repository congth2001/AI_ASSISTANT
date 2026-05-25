from typing import Any, Dict, List
from uuid import UUID

from src.application.services.context_builder import ContextBuilder
from src.application.use_cases.search_document_use_case import SearchDocumentsUseCase
from src.application.use_cases.analytics_use_case import AnalyticsUseCase
from src.domain.entities.message import Message, Conversation
from src.domain.interfaces.i_conversation_repository import IConversationRepository
from src.domain.interfaces.i_llm_service import ILLMService


class ChatUseCase:
    """
    Orchestrate the full chat pipeline:
        1. Load / create conversation
        2. Search relevant business documents  (SearchDocumentsUseCase)
        3. Build LLM context                   (ContextBuilder)
        4. Generate response                   (ILLMService)
        5. Persist messages
    """

    def __init__(
        self,
        llm_service      : ILLMService,
        conversation_repo: IConversationRepository,
        search_use_case  : SearchDocumentsUseCase,
        context_builder  : ContextBuilder,
        analytics_use_case: AnalyticsUseCase,
    ):
        self.llm_service        = llm_service
        self.conversation_repo  = conversation_repo
        self.search_use_case    = search_use_case
        self.context_builder    = context_builder
        self.analytics_use_case = analytics_use_case

    async def execute(self, conversation_id: UUID, user_message: str) -> Dict[str, Any]:
        # ── 1. Load or create conversation ───────────────────────────────
        conversation_data = await self.conversation_repo.get_conversation(conversation_id)
        if not conversation_data:
            conversation_data = await self.create_conversation(title=self._generate_title(user_message))

        conversation     = self._dict_to_conversation(conversation_data)
        is_first_message = len(conversation.messages) == 0

        # ── 2. Analyze query once, route to analytics or RAG ─────────────
        # analyzed = self.search_use_case.query_analyzer.analyze(user_message)
        analyzed = await self.search_use_case.query_analyzer.analyze_with_llm(user_message)

        if analyzed.needs_analytics:
            analytics_text = self.analytics_use_case.execute(analyzed)
            context = self._build_analytics_context(
                analytics_text, conversation.messages, user_message, analyzed
            )
        else:
            search_result = self.search_use_case.execute_analyzed(analyzed)
            context = self.context_builder.build_context(
                search_result=search_result,
                messages     =conversation.messages,
                current_query=user_message,
            )

        # ── 4. Generate LLM response ──────────────────────────────────────
        response_content = await self.llm_service.generate_response(user_message, context)
        print(f"LLM Response: {response_content}")

        # ── 5. Persist messages ───────────────────────────────────────────
        user_msg = Message(
            conversation_id=conversation_id,
            content        =user_message,
            role           ="user",
        )
        assistant_msg = Message(
            conversation_id=conversation_id,
            content        =response_content,
            role           ="assistant",
        )

        await self.conversation_repo.add_message(
            conversation_id, self._message_to_dict(user_msg)
        )
        await self.conversation_repo.add_message(
            conversation_id, self._message_to_dict(assistant_msg)
        )

        # Update title after first real exchange
        if is_first_message:
            await self.conversation_repo.update_conversation(
                conversation_id, {"title": self._generate_title(user_message)}
            )

        return {
            "conversation_id": str(conversation_id),
            "response"       : response_content,
            "intent"         : context.get("intent", analyzed.primary_intent.value),
            "timestamp"      : assistant_msg.timestamp.isoformat(),
            "metadata"       : {
                "has_data"        : context.get("has_data", True),
                "used_fallback"   : context.get("used_fallback", False),
                "fallback_warning": context.get("fallback_warning"),
            },
        }

    async def create_conversation(self, title: str, user_id: str = None, extra_metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        conversation_data = await self.conversation_repo.create_conversation({
            "title"  : title,
            "user_id": user_id,
            "metadata": extra_metadata,
        })
        return conversation_data
    # ─────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────

    def _dict_to_conversation(self, data: Dict[str, Any]) -> Conversation:
        messages = [
            Message(
                id             =UUID(m["id"]) if m.get("id") else None,
                conversation_id=UUID(data["id"]),
                content        =m["content"],
                role           =m["role"],
                timestamp      =m.get("timestamp"),
            )
            for m in data.get("messages", [])
        ]
        return Conversation(
            id        =UUID(data["id"]),
            user_id   =data.get("user_id"),
            title     =data.get("title"),
            messages  =messages,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            metadata  =data.get("metadata"),
        )

    def _message_to_dict(self, message: Message) -> Dict[str, Any]:
        return {
            "id"             : str(message.id) if message.id else None,
            "conversation_id": str(message.conversation_id),
            "content"        : message.content,
            "role"           : message.role,
            "timestamp"      : message.timestamp,
            "metadata"       : message.metadata,
        }

    def _build_analytics_context(
        self,
        analytics_text: str,
        messages      : list,
        current_query : str,
        analyzed      ,
    ) -> Dict[str, Any]:
        history = [
            {"role": m.role, "content": m.content}
            for m in messages[-10:]
        ]
        return {
            "retrieved_text"     : analytics_text,
            "conversation_history": history,
            "current_query"      : current_query,
            "intent"             : analyzed.primary_intent.value,
            "has_data"           : bool(analytics_text),
            "used_fallback"      : False,
            "fallback_warning"   : None,
        }

    @staticmethod
    def _generate_title(message: str) -> str:
        words = message.split()[:6]
        title = " ".join(words)
        return (title[:47] + "...") if len(title) > 50 else title or "New Conversation"
