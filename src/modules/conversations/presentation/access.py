"""Conversation visibility and mutation authorization shared by HTTP adapters."""
from uuid import UUID
from src.modules.conversations.application.use_cases.conversation_use_case import ConversationUseCase
from src.modules.conversations.domain.errors import (
    ConversationNotFoundError,
    ConversationReadOnlyError,
)


def is_admin(current_user: dict) -> bool:
    return current_user["role"] == "admin"


def conversation_read_scope(current_user: dict) -> str | None:
    """Deprecated: ``None`` ("everything") must not be passed to the use case any more.

    Kept only for import compatibility; routers use ``is_admin`` / ``read_conversation``.
    """
    return None if is_admin(current_user) else current_user["id"]


async def read_conversation(
    conversation_id: UUID,
    current_user: dict,
    conversation_use_case: ConversationUseCase,
    turn_limit: int = 50,
) -> dict | None:
    """Admins can read every conversation; everyone else only their own."""
    if is_admin(current_user):
        return await conversation_use_case.get_conversation_as_admin(conversation_id, turn_limit)
    # Owner scoped read: the second argument is the owner id and is never None here.
    return await conversation_use_case.get_conversation(
        conversation_id, current_user["id"], turn_limit
    )


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

    if is_admin(current_user):
        visible = await conversation_use_case.get_conversation_as_admin(
            conversation_id, turn_limit=1
        )
        if visible:
            raise ConversationReadOnlyError()
    raise ConversationNotFoundError()
