from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

MAX_CHAT_MESSAGE_LENGTH = 4000


class ChatRequest(BaseModel):
    # Clients written against the older contract may still send ``user_id``;
    # identity always comes from the Bearer token, so unknown fields are ignored.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    conversation_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)
