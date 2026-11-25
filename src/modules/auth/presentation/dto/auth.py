import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from src.modules.auth.domain.errors import (
    InvalidEmailError,
    PasswordTooLongError,
)
from src.modules.auth.domain.ports.i_password_hasher import MAX_PASSWORD_BYTES, password_byte_length


class CreateStaffRequest(BaseModel):
    email: str = Field(max_length=320)
    # bcrypt reads at most 72 BYTES: validate the UTF-8 length, not the character count.
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_BYTES)
    display_name: str = Field(min_length=2, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if password_byte_length(value) > MAX_PASSWORD_BYTES:
            raise PasswordTooLongError(max_bytes=MAX_PASSWORD_BYTES)
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise InvalidEmailError()
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    # Longer-than-72-byte passwords can never match; the hasher rejects them without raising.
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_BYTES)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class UserResponse(BaseModel):
    id: str
    email: str | None
    display_name: str
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    # None for guest sessions: they are stateless and renewed via POST /auth/guest.
    refresh_token: str | None = None
    token_type: str
    expires_in: int
    user: UserResponse
