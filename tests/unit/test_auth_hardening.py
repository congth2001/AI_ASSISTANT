"""Password hashing, login timing equalisation, refresh-token reuse detection and purge."""
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.common.errors import PermissionDeniedError
from src.modules.auth.application.use_cases.auth_use_case import AuthUseCase
from src.modules.auth.domain.errors import (
    AuthenticationError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    PasswordTooLongError,
    StaffCreationForbiddenError,
)
from src.modules.auth.domain.ports.i_password_hasher import IPasswordHasher
from src.modules.auth.domain.repositories.i_auth_repository import RefreshRotation
from src.modules.auth.infrastructure.models import RefreshTokenModel, UserModel
from src.modules.auth.infrastructure.repositories.auth_repository import AuthRepository
from src.modules.auth.infrastructure.security import BcryptPasswordHasher, JWTTokenService
from src.common.infrastructure.database.base import Base
from src.modules.conversations.infrastructure.models import ConversationModel, MessageModel


# ── password hasher ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hash_and_verify_roundtrip_run_off_the_event_loop():
    hasher = BcryptPasswordHasher(rounds=4)
    loop_thread = threading.get_ident()
    seen = []
    original = hasher._hash
    hasher._hash = lambda password: (seen.append(threading.get_ident()), original(password))[1]

    hashed = await hasher.hash("correct horse")
    assert await hasher.verify("correct horse", hashed) is True
    assert await hasher.verify("wrong", hashed) is False
    assert seen and seen[0] != loop_thread


@pytest.mark.asyncio
async def test_event_loop_stays_responsive_while_hashing():
    hasher = BcryptPasswordHasher(rounds=12)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    await hasher.hash("password-123")
    task.cancel()
    assert ticks >= 3  # a blocking hash (~200 ms at cost 12) would leave ticks at 0


@pytest.mark.asyncio
async def test_verify_returns_false_for_malformed_hash():
    hasher = BcryptPasswordHasher(rounds=4)
    for bad_hash in ("", "not-a-bcrypt-hash", "$2b$12$short"):
        assert await hasher.verify("whatever", bad_hash) is False


@pytest.mark.asyncio
async def test_password_limit_is_measured_in_bytes():
    hasher = BcryptPasswordHasher(rounds=4)
    ok = "a" * 72
    too_long_in_bytes = "é" * 40  # 40 characters but 80 bytes
    assert len(too_long_in_bytes) < 72 < len(too_long_in_bytes.encode())

    hashed = await hasher.hash(ok)
    assert await hasher.verify(ok, hashed) is True
    with pytest.raises(PasswordTooLongError):
        await hasher.hash(too_long_in_bytes)
    # A longer password can never match a hash made from its 72-byte prefix.
    assert await hasher.verify(ok + "extra", hashed) is False
    assert await hasher.verify(too_long_in_bytes, hashed) is False


def test_dummy_hash_is_fixed_and_valid():
    hasher = BcryptPasswordHasher(rounds=4)
    assert hasher.dummy_hash == hasher.dummy_hash
    assert hasher.dummy_hash.startswith("$2")
    assert BcryptPasswordHasher(rounds=4).dummy_hash != hasher.dummy_hash


def test_create_staff_dto_validates_password_bytes():
    from pydantic import ValidationError as PydanticValidationError
    from src.modules.auth.presentation.dto.auth import CreateStaffRequest

    ok = CreateStaffRequest(email="a@b.co", password="a" * 72, display_name="Staff")
    assert ok.password == "a" * 72
    with pytest.raises(PydanticValidationError):
        CreateStaffRequest(email="a@b.co", password="é" * 40, display_name="Staff")
    with pytest.raises(PydanticValidationError):
        CreateStaffRequest(email="a@b.co", password="short", display_name="Staff")


def test_create_admin_validates_encoded_length():
    from src.modules.auth.domain.ports.i_password_hasher import MAX_PASSWORD_BYTES, password_byte_length

    assert MAX_PASSWORD_BYTES == 72
    assert password_byte_length("é" * 40) == 80


def test_staff_creation_forbidden_is_a_permission_error_not_authentication():
    error = StaffCreationForbiddenError()
    assert isinstance(error, PermissionDeniedError)
    assert not isinstance(error, AuthenticationError)


# ── login: no user enumeration through timing ───────────────────────────────

class SpyHasher(IPasswordHasher):
    def __init__(self):
        self.verified = []

    @property
    def dummy_hash(self):
        return "dummy-hash"

    async def hash(self, password):
        return "hash:" + password

    async def verify(self, password, password_hash):
        self.verified.append(password_hash)
        return password_hash == "hash:" + password


class UsersRepo:
    def __init__(self, users):
        self.users = users

    async def get_user_by_email(self, email):
        return self.users.get(email)


def login_use_case(users):
    hasher = SpyHasher()
    use_case = AuthUseCase(
        auth_repository=UsersRepo(users), password_hasher=hasher, token_service=None,
        access_token_minutes=15, refresh_token_days=30,
    )
    return use_case, hasher


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [
    None,
    {"role": "staff", "password_hash": None, "is_active": True},
    {"role": "guest", "password_hash": "hash:pw", "is_active": True},
])
async def test_login_verifies_against_dummy_hash_when_no_usable_account(user):
    use_case, hasher = login_use_case({"a@b.co": user} if user else {})
    with pytest.raises(InvalidCredentialsError):
        await use_case.login("a@b.co", "pw")
    assert hasher.verified == ["dummy-hash"]  # exactly one verification, always


@pytest.mark.asyncio
async def test_login_with_real_account_verifies_once_against_its_hash():
    user = {"role": "staff", "password_hash": "hash:pw", "is_active": True, "id": "u"}
    use_case, hasher = login_use_case({"a@b.co": user})
    use_case._issue_token_pair = lambda u: asyncio.sleep(0, result={"ok": True})
    assert await use_case.login("a@b.co", "pw") == {"ok": True}
    assert hasher.verified == ["hash:pw"]
    with pytest.raises(InvalidCredentialsError):
        await use_case.login("a@b.co", "wrong")
    assert hasher.verified == ["hash:pw", "hash:pw"]


# ── repository against a real (SQLite) database ─────────────────────────────

SECRET = "unit-test-secret-that-is-at-least-32-characters-long"


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    pytest.importorskip("aiosqlite")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = [model.__table__ for model in (UserModel, RefreshTokenModel, ConversationModel, MessageModel)]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def build_use_case(session_factory, grace=0):
    return AuthUseCase(
        auth_repository=AuthRepository(session_factory),
        password_hasher=BcryptPasswordHasher(rounds=4),
        token_service=JWTTokenService(SECRET, "issuer", "audience"),
        access_token_minutes=15,
        refresh_token_days=30,
        refresh_reuse_grace_seconds=grace,
    )


async def active_tokens(session_factory, user_id):
    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(RefreshTokenModel).where(
                RefreshTokenModel.user_id == user_id, RefreshTokenModel.revoked_at.is_(None)
            )
        )
        return result.scalar_one()


@pytest.mark.asyncio
async def test_refresh_rotation_replaces_token_and_replay_revokes_every_session(session_factory):
    use_case = build_use_case(session_factory)
    await use_case.bootstrap_admin("a@b.co", "Admin", "password123")
    first = await use_case.login("a@b.co", "password123")
    second_device = await use_case.login("a@b.co", "password123")
    user_id = first["user"]["id"]
    assert await active_tokens(session_factory, user_id) == 2

    rotated = await use_case.refresh(first["refresh_token"])
    assert rotated["refresh_token"] != first["refresh_token"]
    assert await active_tokens(session_factory, user_id) == 2  # consumed one, stored one

    # Replaying the consumed token is treated as theft: 401 and every active token is revoked.
    with pytest.raises(InvalidRefreshTokenError):
        await use_case.refresh(first["refresh_token"])
    assert await active_tokens(session_factory, user_id) == 0
    with pytest.raises(InvalidRefreshTokenError):
        await use_case.refresh(rotated["refresh_token"])
    with pytest.raises(InvalidRefreshTokenError):
        await use_case.refresh(second_device["refresh_token"])


@pytest.mark.asyncio
async def test_replay_of_logged_out_token_revokes_all_sessions(session_factory):
    use_case = build_use_case(session_factory)
    await use_case.bootstrap_admin("a@b.co", "Admin", "password123")
    laptop = await use_case.login("a@b.co", "password123")
    phone = await use_case.login("a@b.co", "password123")
    await use_case.logout(laptop["refresh_token"])
    with pytest.raises(InvalidRefreshTokenError):
        await use_case.refresh(laptop["refresh_token"])
    with pytest.raises(InvalidRefreshTokenError):
        await use_case.refresh(phone["refresh_token"])


@pytest.mark.asyncio
async def test_other_users_tokens_are_never_revoked_by_a_replay(session_factory):
    use_case = build_use_case(session_factory)
    await use_case.bootstrap_admin("a@b.co", "Admin", "password123")
    admin = await use_case.login("a@b.co", "password123")
    guest = await use_case.create_guest_session()
    await use_case.refresh(admin["refresh_token"])
    with pytest.raises(InvalidRefreshTokenError):
        await use_case.refresh(admin["refresh_token"])
    assert await active_tokens(session_factory, guest["user"]["id"]) == 1
    assert (await use_case.refresh(guest["refresh_token"]))["user"]["id"] == guest["user"]["id"]


@pytest.mark.asyncio
async def test_grace_window_makes_concurrent_refresh_a_plain_401(session_factory):
    use_case = build_use_case(session_factory, grace=30)
    await use_case.bootstrap_admin("a@b.co", "Admin", "password123")
    session = await use_case.login("a@b.co", "password123")
    rotated = await use_case.refresh(session["refresh_token"])
    with pytest.raises(InvalidRefreshTokenError):
        await use_case.refresh(session["refresh_token"])
    # The freshly rotated token survives because the replay fell inside the grace window.
    assert (await use_case.refresh(rotated["refresh_token"]))["access_token"]


@pytest.mark.asyncio
async def test_rotation_is_atomic_when_storing_the_new_token_fails(session_factory):
    repository = AuthRepository(session_factory)
    user = await repository.create_user("a@b.co", "A", "x", "staff")
    expiry = datetime.now(timezone.utc) + timedelta(days=1)
    await repository.store_refresh_token("old-jti", user["id"], expiry)
    await repository.store_refresh_token("dup-jti", user["id"], expiry)

    # new_jti collides with an existing primary key -> the insert fails -> consume must roll back.
    with pytest.raises(Exception):
        await repository.rotate_refresh_token("old-jti", user["id"], "dup-jti", expiry)
    assert await active_tokens(session_factory, user["id"]) == 2
    assert await repository.rotate_refresh_token("old-jti", user["id"], "new-jti", expiry) is RefreshRotation.ROTATED


@pytest.mark.asyncio
async def test_expired_or_unknown_token_is_invalid_without_revoking_anything(session_factory):
    repository = AuthRepository(session_factory)
    user = await repository.create_user("a@b.co", "A", "x", "staff")
    future = datetime.now(timezone.utc) + timedelta(days=1)
    await repository.store_refresh_token("live", user["id"], future)
    await repository.store_refresh_token("expired", user["id"], datetime.now(timezone.utc) - timedelta(seconds=1))

    assert await repository.rotate_refresh_token("expired", user["id"], "n1", future) is RefreshRotation.INVALID
    assert await repository.rotate_refresh_token("missing", user["id"], "n2", future) is RefreshRotation.INVALID
    assert await repository.rotate_refresh_token("live", "someone-else", "n3", future) is RefreshRotation.INVALID
    assert await active_tokens(session_factory, user["id"]) == 2


@pytest.mark.asyncio
async def test_purge_removes_only_stale_guests_without_conversations_and_old_tokens(session_factory):
    repository = AuthRepository(session_factory)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)

    async def add_user(role, created_at, email=None):
        user = await repository.create_user(email, role, None, role)
        async with session_factory() as session:
            model = await session.get(UserModel, user["id"])
            model.created_at = created_at
            await session.commit()
        return user["id"]

    stale_guest = await add_user("guest", old)
    guest_with_conversation = await add_user("guest", old)
    recent_guest = await add_user("guest", now - timedelta(days=1))
    old_staff = await add_user("staff", old, "s@b.co")
    async with session_factory() as session:
        session.add(ConversationModel(id=str(uuid4()), user_id=guest_with_conversation, title="t"))
        await session.commit()

    await repository.store_refresh_token("stale-guest-live", stale_guest, now + timedelta(days=5))
    await repository.store_refresh_token("expired", old_staff, now - timedelta(days=1))
    await repository.store_refresh_token("revoked-long-ago", old_staff, now + timedelta(days=5))
    await repository.store_refresh_token("revoked-recently", old_staff, now + timedelta(days=5))
    await repository.store_refresh_token("valid", old_staff, now + timedelta(days=5))
    async with session_factory() as session:
        (await session.get(RefreshTokenModel, "revoked-long-ago")).revoked_at = now - timedelta(days=30)
        (await session.get(RefreshTokenModel, "revoked-recently")).revoked_at = now - timedelta(hours=1)
        await session.commit()

    use_case = build_use_case(session_factory)
    dry = await use_case.purge_expired_auth_data(30, revoked_older_than_days=7)  # dry_run default
    assert dry == {"guest_users": 1, "refresh_tokens": 2}
    async with session_factory() as session:
        assert (await session.scalar(select(func.count()).select_from(UserModel))) == 4  # nothing deleted

    applied = await use_case.purge_expired_auth_data(30, revoked_older_than_days=7, dry_run=False)
    assert applied == {"guest_users": 1, "refresh_tokens": 2}
    async with session_factory() as session:
        remaining_users = set((await session.scalars(select(UserModel.id))).all())
        remaining_tokens = set((await session.scalars(select(RefreshTokenModel.jti))).all())
    assert remaining_users == {guest_with_conversation, recent_guest, old_staff}
    # The stale guest's token disappeared with the guest (ON DELETE CASCADE).
    assert remaining_tokens == {"revoked-recently", "valid"}
