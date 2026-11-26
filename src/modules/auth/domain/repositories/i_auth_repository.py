from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class RefreshRotation(str, Enum):
    """Outcome of an atomic refresh-token rotation."""

    ROTATED = "rotated"  # old token consumed and the new one stored
    INVALID = "invalid"  # unknown, expired, or (within the grace window) just rotated
    REUSED = "reused"    # an already revoked/consumed token was presented again


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
    async def rotate_refresh_token(
        self,
        jti: str,
        user_id: str,
        new_jti: str,
        new_expires_at: datetime,
        reuse_grace_seconds: int = 0,
    ) -> RefreshRotation:
        """Consume ``jti`` and store ``new_jti`` in ONE transaction.

        When ``jti`` was already revoked (replay), every still-valid refresh token of the user
        is revoked in the same transaction and ``REUSED`` is returned, unless the token was
        revoked less than ``reuse_grace_seconds`` ago (then ``INVALID`` without side effects).
        """
        pass

    @abstractmethod
    async def revoke_refresh_token(self, jti: str, user_id: str) -> None:
        pass

    @abstractmethod
    async def revoke_all_refresh_tokens(self, user_id: str) -> int:
        """Revoke every active refresh token of the user; returns how many were revoked."""
        pass

    @abstractmethod
    async def purge_expired_auth_data(
        self,
        guest_created_before: datetime,
        refresh_expired_before: datetime,
        revoked_before: datetime,
        dry_run: bool = True,
    ) -> Dict[str, int]:
        """Delete (or only count when ``dry_run``) stale auth rows.

        * guest users created before ``guest_created_before`` that own no conversation
          (their refresh tokens cascade);
        * refresh tokens expired before ``refresh_expired_before`` or revoked before
          ``revoked_before``.
        Returns ``{"guest_users": n, "refresh_tokens": n}``.
        """
        pass
