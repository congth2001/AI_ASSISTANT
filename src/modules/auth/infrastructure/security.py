"""Cryptographic adapters; authentication policy stays in the use case.

Dependency note: ``requirements.txt`` should pin ``bcrypt`` (>=4.1,<6). bcrypt 5.x raises
``ValueError`` for passwords longer than 72 bytes while 4.x silently truncates them; this
adapter rejects/handles both uniformly (see ``MAX_PASSWORD_BYTES``).
"""
import asyncio
import logging
import secrets
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError as JWTInvalidTokenError

from src.modules.auth.domain.ports.i_password_hasher import (
    MAX_PASSWORD_BYTES,
    IPasswordHasher,
    password_byte_length,
)
from src.modules.auth.domain.ports.i_token_service import ITokenService
from src.modules.auth.domain.errors import (
    InvalidJWTSecretError,
    InvalidTokenError,
    MissingRefreshTokenIdentifierError,
    PasswordTooLongError,
    UnexpectedTokenTypeError,
)

logger = logging.getLogger(__name__)


class BcryptPasswordHasher(IPasswordHasher):
    """bcrypt adapter; hashing runs in a worker thread so the event loop stays responsive."""

    def __init__(self, rounds: int = 12):
        self._rounds = rounds
        # Computed once: login for unknown accounts verifies against it (constant-cost path).
        self._dummy_hash = bcrypt.hashpw(
            secrets.token_urlsafe(16).encode(), bcrypt.gensalt(rounds)
        ).decode()

    @property
    def dummy_hash(self) -> str:
        return self._dummy_hash

    async def hash(self, password: str) -> str:
        if password_byte_length(password) > MAX_PASSWORD_BYTES:
            raise PasswordTooLongError(max_bytes=MAX_PASSWORD_BYTES)
        return await asyncio.to_thread(self._hash, password)

    async def verify(self, password: str, password_hash: str) -> bool:
        return await asyncio.to_thread(self._verify, password, password_hash)

    def _hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(self._rounds)).decode()

    @staticmethod
    def _verify(password: str, password_hash: str) -> bool:
        encoded = password.encode()
        if len(encoded) > MAX_PASSWORD_BYTES:
            # bcrypt 4.x would silently truncate; 5.x raises. Never accept a truncated match.
            return False
        try:
            return bcrypt.checkpw(encoded, password_hash.encode())
        except ValueError:
            # Corrupt/unsupported stored hash: treat as a failed login, never as a 500.
            logger.warning("Stored password hash is malformed or unsupported")
            return False


class JWTTokenService(ITokenService):
    def __init__(self, secret: str, issuer: str, audience: str):
        if len(secret) < 32:
            raise InvalidJWTSecretError()
        self.secret = secret
        self.issuer = issuer
        self.audience = audience

    def encode(self, claims: dict[str, Any]) -> str:
        return jwt.encode(
            {**claims, "iss": self.issuer, "aud": self.audience},
            self.secret, algorithm="HS256",
        )

    def decode(self, token: str, expected_type: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["sub", "iss", "aud", "iat", "exp", "type"]},
            )
        except JWTInvalidTokenError as exc:
            raise InvalidTokenError() from exc
        if payload.get("type") != expected_type:
            raise UnexpectedTokenTypeError()
        if expected_type == "refresh" and not payload.get("jti"):
            raise MissingRefreshTokenIdentifierError()
        return payload
