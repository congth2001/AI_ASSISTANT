import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CreateStaffRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(min_length=2, max_length=100)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("Invalid email address")
        return normalized


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str | None
    display_name: str
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user: UserResponse
