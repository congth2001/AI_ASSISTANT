import logging
from typing import List
from uuid import UUID
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from config.container import Container
from src.modules.conversations.application.use_cases.conversation_use_case import ConversationUseCase
from src.modules.conversations.domain.repositories.i_conversation_repository import (
    MAX_CONVERSATION_PAGE_SIZE,
)
from src.modules.conversations.presentation.access import (
    ensure_conversation_write_access, is_admin, read_conversation,
)
from src.modules.conversations.presentation.dto.conversation import (
    CreateConversationRequest, CreateConversationResponse, ConversationResponse,
    DeleteConversationResponse, RenameConversationRequest,
)
from src.modules.auth.presentation.router import require_role
from src.modules.conversations.domain.errors import (
    ConversationCreateFailedError,
    ConversationDeleteFailedError,
    ConversationListFailedError,
    ConversationNotFoundError,
    ConversationReadFailedError,
    ConversationRenameFailedError,
)
from src.common.errors import ApplicationError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
@inject
async def get_conversation(
    conversation_id: UUID,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.conversation_use_case]),
) -> ConversationResponse:
    """Get conversation details including message history."""
    try:
        data = await read_conversation(conversation_id, current_user, conversation_use_case)
        if not data:
            raise ConversationNotFoundError()
        if data.get("messages"):
            data["messages"] = list(reversed(data["messages"]))
        return ConversationResponse(**data)
    except ApplicationError:
        raise
    except Exception as exc:
        logger.exception("Failed to read conversation %s", conversation_id)
        raise ConversationReadFailedError() from exc


@router.get("/conversations", response_model=List[ConversationResponse])
@inject
async def get_all_conversations(
    limit: int = Query(MAX_CONVERSATION_PAGE_SIZE, ge=1, le=MAX_CONVERSATION_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.conversation_use_case]),
) -> List[ConversationResponse]:
    """List conversations, most recently updated first (staff: own; admin: everyone's)."""
    try:
        if is_admin(current_user):
            data_list = await conversation_use_case.get_all_conversations_as_admin(limit, offset)
        else:
            data_list = await conversation_use_case.get_conversations_for_owner(
                current_user["id"], limit, offset
            )
        return [ConversationResponse(**data) for data in data_list]
    except ApplicationError:
        raise
    except Exception as exc:
        logger.exception("Failed to list conversations for user %s", current_user["id"])
        raise ConversationListFailedError() from exc


@router.post("/conversations", response_model=CreateConversationResponse, status_code=201)
@inject
async def create_conversation(
    request: CreateConversationRequest,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.conversation_use_case]),
) -> CreateConversationResponse:
    """Create a new conversation."""
    try:
        data = await conversation_use_case.create_conversation(
            title=request.title,
            user_id=current_user["id"],
            metadata=request.metadata,
        )
        return CreateConversationResponse(**data)
    except ApplicationError:
        raise
    except Exception as exc:
        logger.exception("Failed to create conversation for user %s", current_user["id"])
        raise ConversationCreateFailedError() from exc


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
@inject
async def rename_conversation(
    conversation_id: UUID,
    request: RenameConversationRequest,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.conversation_use_case]),
) -> ConversationResponse:
    """Rename a conversation."""
    try:
        await ensure_conversation_write_access(
            conversation_id, current_user, conversation_use_case
        )
        success = await conversation_use_case.rename_conversation(
            conversation_id, request.title, current_user["id"]
        )
        if not success:
            raise ConversationNotFoundError()
        data = await conversation_use_case.get_conversation(
            conversation_id, current_user["id"]
        )
        if not data:
            # Deleted concurrently between the update and the read.
            raise ConversationNotFoundError()
        return ConversationResponse(**data)
    except ApplicationError:
        raise
    except Exception as exc:
        logger.exception("Failed to rename conversation %s", conversation_id)
        raise ConversationRenameFailedError() from exc


@router.delete("/conversations/{conversation_id}", response_model=DeleteConversationResponse)
@inject
async def delete_conversation(
    conversation_id: UUID,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.conversation_use_case]),
) -> DeleteConversationResponse:
    """Soft-delete a conversation."""
    try:
        await ensure_conversation_write_access(
            conversation_id, current_user, conversation_use_case
        )
        deleted = await conversation_use_case.delete_conversation(
            conversation_id, current_user["id"]
        )
        if not deleted:
            raise ConversationNotFoundError()
        return DeleteConversationResponse(
            conversation_id=str(conversation_id), status="deleted"
        )
    except ApplicationError:
        raise
    except Exception as exc:
        logger.exception("Failed to delete conversation %s", conversation_id)
        raise ConversationDeleteFailedError() from exc
