from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4

from src.modules.auth.domain.errors import AuthenticationError
from src.modules.auth.domain.ports.i_password_hasher import IPasswordHasher
from src.modules.auth.domain.ports.i_token_service import ITokenService

from src.modules.auth.domain.repositories.i_auth_repository import IAuthRepository
from src.modules.auth.domain.entities.user import UserRole
from src.modules.auth.domain.errors import (
    AccountDisabledError,
    AccountUnavailableError,
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    StaffCreationForbiddenError,
)


class AuthUseCase:
    def __init__(
        self,
        auth_repository: IAuthRepository,
        password_hasher: IPasswordHasher,
        token_service: ITokenService,
        access_token_minutes: int,
        refresh_token_days: int,
    ):
        self.repository = auth_repository
        self.password_hasher = password_hasher
        self.token_service = token_service
        self.access_token_minutes = access_token_minutes
        self.refresh_token_days = refresh_token_days

    async def create_staff(
        self, email: str, display_name: str, password: str, actor: Dict[str, Any]
    ) -> Dict[str, Any]:
        if actor.get("role") != UserRole.ADMIN.value:
            raise StaffCreationForbiddenError()
        normalized_email = email.strip().lower()
        password_hash = self.password_hasher.hash(password)
        return await self.repository.create_user(
            normalized_email, display_name.strip(), password_hash, UserRole.STAFF.value
        )

    async def create_guest_session(self) -> Dict[str, Any]:
        guest = await self.repository.create_user(
            None, "Khách", None, UserRole.GUEST.value
        )
        return await self._issue_token_pair(guest)

    async def bootstrap_admin(self, email: str, display_name: str, password: str) -> Dict[str, Any]:
        """Create an initial admin. This method is intended for the local CLI only."""
        normalized_email = email.strip().lower()
        existing = await self.repository.get_user_by_email(normalized_email)
        if existing:
            raise DuplicateEmailError()
        password_hash = self.password_hasher.hash(password)
        return await self.repository.create_user(
            normalized_email, display_name.strip(), password_hash, UserRole.ADMIN.value
        )

    async def login(self, email: str, password: str) -> Dict[str, Any]:
        user = await self.repository.get_user_by_email(email.strip().lower())
        if (
            not user
            or user.get("role") not in {UserRole.STAFF.value, UserRole.ADMIN.value}
            or not user.get("password_hash")
            or not self.password_hasher.verify(password, user["password_hash"])
        ):
            raise InvalidCredentialsError()
        if not user["is_active"]:
            raise AccountDisabledError()
        return await self._issue_token_pair(user)

    async def refresh(self, refresh_token: str) -> Dict[str, Any]:
        payload = self._decode(refresh_token, expected_type="refresh")
        user_id = payload["sub"]
        if not await self.repository.consume_refresh_token(payload["jti"], user_id):
            raise InvalidRefreshTokenError()
        user = await self.repository.get_user_by_id(user_id)
        if not user or not user["is_active"]:
            raise AccountUnavailableError()
        return await self._issue_token_pair(user)

    async def logout(self, refresh_token: str) -> None:
        payload = self._decode(refresh_token, expected_type="refresh")
        await self.repository.revoke_refresh_token(payload["jti"], payload["sub"])

    async def authenticate_access_token(self, access_token: str) -> Dict[str, Any]:
        payload = self._decode(access_token, expected_type="access")
        user = await self.repository.get_user_by_id(payload["sub"])
        if not user or not user["is_active"]:
            raise AccountUnavailableError()
        return user

    async def _issue_token_pair(self, user: Dict[str, Any]) -> Dict[str, Any]:
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
        await self.repository.store_refresh_token(refresh_jti, user["id"], refresh_expiry)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.access_token_minutes * 60,
            "user": user,
        }

    def _decode(self, token: str, expected_type: str) -> Dict[str, Any]:
        return self.token_service.decode(token, expected_type)
