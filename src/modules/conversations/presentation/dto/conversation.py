import json
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any, Dict, List, Optional
from datetime import datetime

from src.modules.conversations.domain.errors import (
    ConversationMetadataInvalidError,
    ConversationMetadataTooLargeError,
)

MAX_TITLE_LENGTH = 200
MAX_METADATA_BYTES = 8 * 1024


class CreateConversationRequest(BaseModel):
    # Unknown fields (e.g. a client-sent user_id) are ignored: the owner is always the caller.
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = Field(default="New Conversation", max_length=MAX_TITLE_LENGTH)
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("metadata")
    @classmethod
    def limit_metadata_size(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is not None:
            try:
                size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
            except (TypeError, ValueError):
                raise ConversationMetadataInvalidError() from None
            if size > MAX_METADATA_BYTES:
                raise ConversationMetadataTooLargeError(max_bytes=MAX_METADATA_BYTES)
        return value


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)


class MessageResponse(BaseModel):
    role: str
    content: str
    timestamp: Optional[datetime] = None


class ConversationOwnerResponse(BaseModel):
    id: str
    display_name: str
    email: Optional[str] = None
    role: str


class ConversationResponse(BaseModel):
    id: str
    title: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    messages: Optional[List[MessageResponse]] = None
    metadata: Optional[Dict[str, Any]] = None
    owner: Optional[ConversationOwnerResponse] = None


class CreateConversationResponse(BaseModel):
    id: str
    title: str
    user_id: Optional[str] = None
    created_at: Optional[datetime] = None
    owner: Optional[ConversationOwnerResponse] = None


class DeleteConversationResponse(BaseModel):
    conversation_id: str
    status: str
