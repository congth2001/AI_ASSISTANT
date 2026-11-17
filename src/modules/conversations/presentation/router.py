from typing import List
from uuid import UUID
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends

from config.container import Container
from src.modules.conversations.application.use_cases.conversation_use_case import ConversationUseCase
from src.modules.conversations.presentation.access import (
    conversation_read_scope, ensure_conversation_write_access,
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
from src.common.errors import (
    ApplicationError,
    ErrorType,
)

router = APIRouter()


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
@inject
async def get_conversation(
    conversation_id: UUID,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> ConversationResponse:
    """Get conversation details including message history."""
    try:
        data = await conversation_use_case.get_conversation(
            conversation_id, conversation_read_scope(current_user)
        )
        if not data:
            raise ConversationNotFoundError()
        if data.get("messages"):
            data["messages"] = list(reversed(data["messages"]))
        return ConversationResponse(**data)
    except ApplicationError:
        raise
    except Exception as e:
        raise ConversationReadFailedError()

@router.get("/conversations", response_model=List[ConversationResponse])
@inject
async def get_all_conversations(
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> List[ConversationResponse]:
    """Get all conversations."""
    try:
        data_list = await conversation_use_case.get_all_conversations(
            conversation_read_scope(current_user)
        )
        return [ConversationResponse(**data) for data in data_list]
    except ApplicationError:
        raise
    except Exception as e:
        raise ConversationListFailedError()


@router.post("/conversations", response_model=CreateConversationResponse, status_code=201)
@inject
async def create_conversation(
    request: CreateConversationRequest,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
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
    except Exception as e:
        raise ConversationCreateFailedError()


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
@inject
async def rename_conversation(
    conversation_id: UUID,
    request: RenameConversationRequest,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
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
        return ConversationResponse(**data)
    except ApplicationError:
        raise
    except Exception as e:
        raise ConversationRenameFailedError()


@router.delete("/conversations/{conversation_id}", response_model=DeleteConversationResponse)
@inject
async def delete_conversation(
    conversation_id: UUID,
    current_user: dict = Depends(require_role("staff", "admin")),
    conversation_use_case: ConversationUseCase = Depends(Provide[Container.use_case_conversation]),
) -> DeleteConversationResponse:
    """Soft-delete a conversation."""
    try:
        await ensure_conversation_write_access(
            conversation_id, current_user, conversation_use_case
        )
        result = await conversation_use_case.delete_conversation(
            conversation_id, current_user["id"]
        )
        return DeleteConversationResponse(
            conversation_id=str(conversation_id),
            status="deleted" if result else ErrorType.NOT_FOUND.value,
        )
    except ApplicationError:
        raise
    except Exception as e:
        raise ConversationDeleteFailedError()


