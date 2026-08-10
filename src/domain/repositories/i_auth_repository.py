from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional


class IAuthRepository(ABC):
    @abstractmethod
    async def create_user(
        self, email: Optional[str], display_name: str, password_hash: Optional[str], role: str
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def store_refresh_token(self, jti: str, user_id: str, expires_at: datetime) -> None:
        pass

    @abstractmethod
    async def consume_refresh_token(self, jti: str, user_id: str) -> bool:
        """Atomically revoke a refresh token. Returns False when it is invalid/used."""
        pass

    @abstractmethod
    async def revoke_refresh_token(self, jti: str, user_id: str) -> None:
        pass
