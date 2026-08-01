from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import uuid4

import bcrypt
import jwt
from jwt import InvalidTokenError

from src.domain.repositories.i_auth_repository import IAuthRepository
from src.domain.entities.user import UserRole


class AuthenticationError(ValueError):
    pass


class AuthUseCase:
    def __init__(
        self,
        auth_repository: IAuthRepository,
        jwt_secret: str,
        jwt_issuer: str,
        jwt_audience: str,
        access_token_minutes: int,
        refresh_token_days: int,
    ):
        if len(jwt_secret) < 32:
            raise ValueError("auth.jwt_secret must contain at least 32 characters")
        self.repository = auth_repository
        self.jwt_secret = jwt_secret
        self.jwt_issuer = jwt_issuer
        self.jwt_audience = jwt_audience
        self.access_token_minutes = access_token_minutes
        self.refresh_token_days = refresh_token_days

    async def create_staff(
        self, email: str, display_name: str, password: str, actor: Dict[str, Any]
    ) -> Dict[str, Any]:
        if actor.get("role") != UserRole.ADMIN.value:
            raise AuthenticationError("Only administrators can create staff accounts")
        normalized_email = email.strip().lower()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
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
            raise ValueError("Email is already registered")
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        return await self.repository.create_user(
            normalized_email, display_name.strip(), password_hash, UserRole.ADMIN.value
        )

    async def login(self, email: str, password: str) -> Dict[str, Any]:
        user = await self.repository.get_user_by_email(email.strip().lower())
        if (
            not user
            or user.get("role") not in {UserRole.STAFF.value, UserRole.ADMIN.value}
            or not user.get("password_hash")
            or not bcrypt.checkpw(password.encode(), user["password_hash"].encode())
        ):
            raise AuthenticationError("Email or password is incorrect")
        if not user["is_active"]:
            raise AuthenticationError("Account is disabled")
        return await self._issue_token_pair(user)

    async def refresh(self, refresh_token: str) -> Dict[str, Any]:
        payload = self._decode(refresh_token, expected_type="refresh")
        user_id = payload["sub"]
        if not await self.repository.consume_refresh_token(payload["jti"], user_id):
            raise AuthenticationError("Refresh token is invalid or has already been used")
        user = await self.repository.get_user_by_id(user_id)
        if not user or not user["is_active"]:
            raise AuthenticationError("Account is unavailable")
        return await self._issue_token_pair(user)

    async def logout(self, refresh_token: str) -> None:
        payload = self._decode(refresh_token, expected_type="refresh")
        await self.repository.revoke_refresh_token(payload["jti"], payload["sub"])

    async def authenticate_access_token(self, access_token: str) -> Dict[str, Any]:
        payload = self._decode(access_token, expected_type="access")
        user = await self.repository.get_user_by_id(payload["sub"])
        if not user or not user["is_active"]:
            raise AuthenticationError("Account is unavailable")
        return user

    async def _issue_token_pair(self, user: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        refresh_jti = str(uuid4())
        access_expiry = now + timedelta(minutes=self.access_token_minutes)
        refresh_expiry = now + timedelta(days=self.refresh_token_days)
        common = {
            "sub": user["id"],
            "role": user["role"],
            "iss": self.jwt_issuer,
            "aud": self.jwt_audience,
            "iat": now,
        }
        access_token = jwt.encode(
            {**common, "type": "access", "exp": access_expiry}, self.jwt_secret, algorithm="HS256"
        )
        refresh_token = jwt.encode(
            {**common, "type": "refresh", "jti": refresh_jti, "exp": refresh_expiry},
            self.jwt_secret,
            algorithm="HS256",
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
        try:
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256"],
                issuer=self.jwt_issuer,
                audience=self.jwt_audience,
                options={"require": ["sub", "iss", "aud", "iat", "exp", "type"]},
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("Token is invalid or expired") from exc
        if payload.get("type") != expected_type:
            raise AuthenticationError("Unexpected token type")
        if expected_type == "refresh" and not payload.get("jti"):
            raise AuthenticationError("Refresh token is missing an identifier")
        return payload
