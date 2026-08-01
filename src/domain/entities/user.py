from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    GUEST = "guest"
    STAFF = "staff"
    ADMIN = "admin"


@dataclass(frozen=True)
class User:
    id: str
    email: str | None
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
