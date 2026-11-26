import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4

from src.modules.auth.domain.ports.i_password_hasher import IPasswordHasher
from src.modules.auth.domain.ports.i_token_service import ITokenService

from src.modules.auth.domain.repositories.i_auth_repository import IAuthRepository, RefreshRotation
from src.modules.auth.domain.entities.user import UserRole
from src.modules.auth.domain.errors import (
    AccountDisabledError,
    AccountUnavailableError,
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    StaffCreationForbiddenError,
)

logger = logging.getLogger(__name__)


class AuthUseCase:
    def __init__(
        self,
        auth_repository: IAuthRepository,
        password_hasher: IPasswordHasher,
        token_service: ITokenService,
        access_token_minutes: int,
        refresh_token_days: int,
        refresh_reuse_grace_seconds: int = 30,
        guest_token_minutes: int = 60,
    ):
        self.repository = auth_repository
        self.password_hasher = password_hasher
        self.token_service = token_service
        self.access_token_minutes = access_token_minutes
        self.refresh_token_days = refresh_token_days
        self.refresh_reuse_grace_seconds = 30 if refresh_reuse_grace_seconds is None else int(refresh_reuse_grace_seconds)
        self.guest_token_minutes = 60 if guest_token_minutes is None else int(guest_token_minutes)

    async def create_staff(
        self, email: str, display_name: str, password: str, actor: Dict[str, Any]
    ) -> Dict[str, Any]:
        if actor.get("role") != UserRole.ADMIN.value:
            raise StaffCreationForbiddenError()
        normalized_email = email.strip().lower()
        password_hash = await self.password_hasher.hash(password)
        return await self.repository.create_user(
            normalized_email, display_name.strip(), password_hash, UserRole.STAFF.value
        )

    async def create_guest_session(self) -> Dict[str, Any]:
        """Stateless guest session: a self-contained access token, no users row, no refresh token.

        Guests may only chat one stateless question at a time, so nothing has to be looked up or
        revoked server-side. When the token expires the client simply asks for a new session.
        """
        now = datetime.now(timezone.utc)
        guest = self._guest_user(str(uuid4()), now)
        access_token = self.token_service.encode({
            "sub": guest["id"],
            "role": UserRole.GUEST.value,
            "iat": now,
            "type": "access",
            "exp": now + timedelta(minutes=self.guest_token_minutes),
        })
        return {
            "access_token": access_token,
            "refresh_token": None,
            "token_type": "bearer",
            "expires_in": self.guest_token_minutes * 60,
            "user": guest,
        }

    @staticmethod
    def _guest_user(guest_id: str, created_at: datetime) -> Dict[str, Any]:
        return {
            "id": guest_id,
            "email": None,
            "display_name": "Khách",
            "role": UserRole.GUEST.value,
            "is_active": True,
            "created_at": created_at,
        }

    async def bootstrap_admin(self, email: str, display_name: str, password: str) -> Dict[str, Any]:
        """Create an initial admin. This method is intended for the local CLI only."""
        normalized_email = email.strip().lower()
        existing = await self.repository.get_user_by_email(normalized_email)
        if existing:
            raise DuplicateEmailError()
        password_hash = await self.password_hasher.hash(password)
        return await self.repository.create_user(
            normalized_email, display_name.strip(), password_hash, UserRole.ADMIN.value
        )

    async def login(self, email: str, password: str) -> Dict[str, Any]:
        user = await self.repository.get_user_by_email(email.strip().lower())
        eligible = bool(
            user
            and user.get("role") in {UserRole.STAFF.value, UserRole.ADMIN.value}
            and user.get("password_hash")
        )
        # Always run exactly one bcrypt verification (against a fixed dummy hash when there is
        # no usable account) so response time does not reveal whether the e-mail exists.
        stored_hash = user["password_hash"] if eligible else self.password_hasher.dummy_hash
        password_ok = await self.password_hasher.verify(password, stored_hash)
        if not eligible or not password_ok:
            raise InvalidCredentialsError()
        if not user["is_active"]:
            raise AccountDisabledError()
        return await self._issue_token_pair(user)

    async def refresh(self, refresh_token: str) -> Dict[str, Any]:
        payload = self._decode(refresh_token, expected_type="refresh")
        if payload.get("role") == UserRole.GUEST.value:
            # Guest sessions are stateless now; tokens issued before still fail cleanly.
            raise InvalidRefreshTokenError()
        user_id = payload["sub"]
        user = await self.repository.get_user_by_id(user_id)
        if not user or not user["is_active"]:
            raise AccountUnavailableError()
        pair, new_jti, new_expiry = self._build_token_pair(user)
        outcome = await self.repository.rotate_refresh_token(
            payload["jti"], user_id, new_jti, new_expiry, self.refresh_reuse_grace_seconds
        )
        if outcome is RefreshRotation.REUSED:
            # A consumed token was replayed: assume theft, all sessions of this user were revoked.
            logger.warning("Refresh token reuse detected; revoked all sessions of user %s", user_id)
        if outcome is not RefreshRotation.ROTATED:
            raise InvalidRefreshTokenError()
        return pair

    async def logout(self, refresh_token: str) -> None:
        payload = self._decode(refresh_token, expected_type="refresh")
        await self.repository.revoke_refresh_token(payload["jti"], payload["sub"])

    async def authenticate_access_token(self, access_token: str) -> Dict[str, Any]:
        payload = self._decode(access_token, expected_type="access")
        if payload.get("role") == UserRole.GUEST.value:
            issued_at = datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc)
            return self._guest_user(str(payload["sub"]), issued_at)
        user = await self.repository.get_user_by_id(payload["sub"])
        if not user or not user["is_active"]:
            raise AccountUnavailableError()
        return user

    async def purge_expired_auth_data(
        self,
        guest_older_than_days: int,
        *,
        revoked_older_than_days: int = 7,
        dry_run: bool = True,
    ) -> Dict[str, int]:
        """Remove stale guests (no conversations) and expired/old-revoked refresh tokens.

        Revoked tokens are kept for ``revoked_older_than_days`` so that replaying a recently
        rotated token is still detected as reuse. ``dry_run`` only reports the counts.
        """
        now = datetime.now(timezone.utc)
        return await self.repository.purge_expired_auth_data(
            guest_created_before=now - timedelta(days=guest_older_than_days),
            refresh_expired_before=now,
            revoked_before=now - timedelta(days=revoked_older_than_days),
            dry_run=dry_run,
        )

    async def _issue_token_pair(self, user: Dict[str, Any]) -> Dict[str, Any]:
        pair, refresh_jti, refresh_expiry = self._build_token_pair(user)
        await self.repository.store_refresh_token(refresh_jti, user["id"], refresh_expiry)
        return pair

    def _build_token_pair(self, user: Dict[str, Any]) -> tuple[Dict[str, Any], str, datetime]:
        now = datetime.now(timezone.utc)
        refresh_jti = str(uuid4())
        access_expiry = now + timedelta(minutes=self.access_token_minutes)
        refresh_expiry = now + timedelta(days=self.refresh_token_days)
        common = {
            "sub": user["id"],
            "role": user["role"],
            "iat": now,
        }
        access_token = self.token_service.encode(
            {**common, "type": "access", "exp": access_expiry}
        )
        refresh_token = self.token_service.encode(
            {**common, "type": "refresh", "jti": refresh_jti, "exp": refresh_expiry}
        )
        pair = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.access_token_minutes * 60,
            "user": user,
        }
        return pair, refresh_jti, refresh_expiry

    def _decode(self, token: str, expected_type: str) -> Dict[str, Any]:
        return self.token_service.decode(token, expected_type)
