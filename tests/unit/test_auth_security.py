from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.modules.auth.domain.errors import AuthenticationError
from src.modules.auth.infrastructure.security import JWTTokenService


SECRET = "unit-test-secret-with-at-least-thirty-two-characters"


def claims():
    now = datetime.now(timezone.utc)
    return {
        "sub": "user-1", "iss": "issuer", "aud": "audience", "iat": now,
        "exp": now + timedelta(minutes=15), "type": "access",
    }


@pytest.mark.parametrize("change", [
    {"iss": "wrong"}, {"aud": "wrong"}, {"exp": 1},
    {"type": "refresh"}, {"sub": None},
])
def test_jwt_adapter_rejects_invalid_claims(change):
    token = jwt.encode({**claims(), **change}, SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        JWTTokenService(SECRET, "issuer", "audience").decode(token, "access")


@pytest.mark.parametrize("missing", ["sub", "iss", "aud", "iat", "exp", "type"])
def test_jwt_adapter_requires_authentication_claims(missing):
    payload = claims()
    del payload[missing]
    token = jwt.encode(payload, SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        JWTTokenService(SECRET, "issuer", "audience").decode(token, "access")


def test_refresh_token_requires_identifier():
    service = JWTTokenService(SECRET, "issuer", "audience")
    token = service.encode({**claims(), "type": "refresh"})
    with pytest.raises(AuthenticationError, match="identifier"):
        service.decode(token, "refresh")


def test_jwt_signature_and_algorithm_remain_restricted():
    service = JWTTokenService(SECRET, "issuer", "audience")
    for token in (
        jwt.encode(claims(), SECRET + "wrong", algorithm="HS256"),
        jwt.encode(claims(), SECRET, algorithm="HS384"),
    ):
        with pytest.raises(AuthenticationError):
            service.decode(token, "access")


def test_jwt_adapter_rejects_short_secret():
    with pytest.raises(ValueError, match="at least 32"):
        JWTTokenService("short", "issuer", "audience")
