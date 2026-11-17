"""Conversation visibility and mutation authorization shared by HTTP adapters."""
from uuid import UUID
from src.modules.conversations.application.use_cases.conversation_use_case import ConversationUseCase
from src.modules.conversations.domain.errors import (
    ConversationNotFoundError,
    ConversationReadOnlyError,
)


def conversation_read_scope(current_user: dict) -> str | None:
    """Admins can read every conversation; staff can read only their own."""
    return None if current_user["role"] == "admin" else current_user["id"]


async def ensure_conversation_write_access(
    conversation_id: UUID,
    current_user: dict,
    conversation_use_case: ConversationUseCase,
) -> None:
    """Only the owner can chat in, rename, or delete a conversation."""
    owned = await conversation_use_case.get_conversation(
        conversation_id, current_user["id"], turn_limit=1
    )
    if owned:
        return

    if current_user["role"] == "admin":
        visible = await conversation_use_case.get_conversation(
            conversation_id, None, turn_limit=1
        )
        if visible:
            raise ConversationReadOnlyError()
    raise ConversationNotFoundError()


