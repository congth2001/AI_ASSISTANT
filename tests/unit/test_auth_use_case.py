from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.application.use_cases.auth_use_case import AuthenticationError, AuthUseCase


class FakeAuthRepository:
    def __init__(self):
        self.users = {}
        self.refresh_tokens = {}

    async def create_user(self, email, display_name, password_hash, role):
        user = {
            "id": str(uuid4()),
            "email": email,
            "display_name": display_name,
            "password_hash": password_hash,
            "role": role,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
        }
        self.users[user["id"]] = user
        return user

    async def get_user_by_email(self, email):
        return next((user for user in self.users.values() if user["email"] == email), None)

    async def get_user_by_id(self, user_id):
        return self.users.get(user_id)

    async def store_refresh_token(self, jti, user_id, expires_at):
        self.refresh_tokens[jti] = {"user_id": user_id, "expires_at": expires_at, "revoked": False}

    async def consume_refresh_token(self, jti, user_id):
        token = self.refresh_tokens.get(jti)
        if not token or token["user_id"] != user_id or token["revoked"]:
            return False
        token["revoked"] = True
        return True

    async def revoke_refresh_token(self, jti, user_id):
        token = self.refresh_tokens.get(jti)
        if token and token["user_id"] == user_id:
            token["revoked"] = True


def build_use_case():
    return AuthUseCase(
        auth_repository=FakeAuthRepository(),
        jwt_secret="unit-test-secret-that-is-at-least-32-characters-long",
        jwt_issuer="test-issuer",
        jwt_audience="test-audience",
        access_token_minutes=15,
        refresh_token_days=30,
    )


@pytest.mark.asyncio
async def test_register_login_and_authenticate_access_token():
    use_case = build_use_case()
    admin = await use_case.bootstrap_admin(" Test@Example.com ", "Test User", "password123")
    registered = await use_case.login("test@example.com", "password123")

    assert registered["user"]["email"] == "test@example.com"
    assert admin["role"] == "admin"
    current_user = await use_case.authenticate_access_token(registered["access_token"])
    assert current_user["id"] == registered["user"]["id"]

    logged_in = await use_case.login("test@example.com", "password123")
    assert logged_in["user"]["id"] == current_user["id"]


@pytest.mark.asyncio
async def test_refresh_token_is_rotated_and_cannot_be_reused():
    use_case = build_use_case()
    session = await use_case.create_guest_session()

    refreshed = await use_case.refresh(session["refresh_token"])
    assert refreshed["refresh_token"] != session["refresh_token"]

    with pytest.raises(AuthenticationError):
        await use_case.refresh(session["refresh_token"])


@pytest.mark.asyncio
async def test_login_rejects_wrong_password():
    use_case = build_use_case()
    await use_case.bootstrap_admin("test@example.com", "Test User", "password123")

    with pytest.raises(AuthenticationError):
        await use_case.login("test@example.com", "wrong-password")


@pytest.mark.asyncio
async def test_only_admin_can_create_staff():
    use_case = build_use_case()
    guest_session = await use_case.create_guest_session()

    with pytest.raises(AuthenticationError):
        await use_case.create_staff(
            "staff@example.com", "Staff User", "password123", guest_session["user"]
        )

    admin = await use_case.bootstrap_admin("admin@example.com", "Admin", "password123")
    staff = await use_case.create_staff(
        "staff@example.com", "Staff User", "password123", admin
    )
    assert staff["role"] == "staff"


@pytest.mark.asyncio
async def test_guest_account_cannot_login():
    use_case = build_use_case()
    guest_session = await use_case.create_guest_session()
    assert guest_session["user"]["role"] == "guest"
    assert guest_session["user"]["email"] is None
