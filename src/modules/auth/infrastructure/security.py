"""Cryptographic adapters; authentication policy stays in the use case."""
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError as JWTInvalidTokenError

from src.modules.auth.domain.ports.i_password_hasher import IPasswordHasher
from src.modules.auth.domain.ports.i_token_service import ITokenService
from src.modules.auth.domain.errors import (
    InvalidJWTSecretError,
    InvalidTokenError,
    MissingRefreshTokenIdentifierError,
    UnexpectedTokenTypeError,
)


class BcryptPasswordHasher(IPasswordHasher):
    def hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def verify(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode(), password_hash.encode())


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
