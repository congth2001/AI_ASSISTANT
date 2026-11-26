"""Conversation repository scoping, pagination and atomic multi-message writes (SQLite)."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.common.infrastructure.database.base import Base
from src.modules.auth.infrastructure.models import RefreshTokenModel, UserModel
from src.modules.conversations.application.use_cases.conversation_use_case import ConversationUseCase
from src.modules.conversations.domain.entities.message import Message
from src.modules.conversations.domain.errors import (
    ConversationNotFoundError,
    ConversationScopeRequiredError,
)
from src.modules.conversations.domain.repositories.i_conversation_repository import MAX_CONVERSATION_PAGE_SIZE
from src.modules.conversations.infrastructure.models import ConversationModel, MessageModel
from src.modules.conversations.infrastructure.repositories.conversation_repository import ConversationRepository


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    pytest.importorskip("aiosqlite")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'conversations.db'}")
    tables = [model.__table__ for model in (UserModel, RefreshTokenModel, ConversationModel, MessageModel)]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all([
            UserModel(id="owner", email="o@x.co", display_name="Owner", role="staff"),
            UserModel(id="other", email="t@x.co", display_name="Other", role="staff"),
            UserModel(id="admin", email="a@x.co", display_name="Admin", role="admin"),
        ])
        await session.commit()
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def repo(session_factory):
    return ConversationRepository(session_factory)


async def new_conversation(repo, owner="owner", title="t"):
    return await repo.create_conversation({"user_id": owner, "title": title})


async def count_messages(session_factory):
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(MessageModel))


# ── add_messages ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_messages_writes_all_in_order_and_bumps_updated_at(repo, session_factory):
    conversation = await new_conversation(repo)
    before = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with session_factory() as session:
        (await session.get(ConversationModel, conversation["id"])).updated_at = before
        await session.commit()

    saved = await repo.add_messages(UUID(conversation["id"]), [
        {"role": "user", "content": "Doanh thu?", "metadata": None},
        {"role": "assistant", "content": "100", "metadata": {"intent": "text_to_sql"}},
    ])

    assert [m.role for m in saved] == ["user", "assistant"]
    assert all(isinstance(m, Message) and isinstance(m.id, UUID) for m in saved)
    assert saved[0].timestamp < saved[1].timestamp
    assert saved[1].metadata == {"intent": "text_to_sql"}

    loaded = await repo.get_conversation(UUID(conversation["id"]), 10, "owner")
    assert [m["content"] for m in loaded["messages"]] == ["100", "Doanh thu?"]  # newest first
    assert loaded["updated_at"] > before


@pytest.mark.asyncio
async def test_add_messages_accepts_chat_use_case_dicts_with_ids_and_timestamps(repo):
    conversation = await new_conversation(repo)
    message_id = str(uuid4())
    stamp = datetime.now(timezone.utc)
    saved = await repo.add_messages(UUID(conversation["id"]), [{
        "id": message_id, "conversation_id": conversation["id"], "role": "user",
        "content": "hi", "timestamp": stamp, "metadata": None,
    }])
    assert str(saved[0].id) == message_id


@pytest.mark.asyncio
async def test_add_messages_is_all_or_nothing(repo, session_factory):
    conversation = await new_conversation(repo)
    duplicate = str(uuid4())
    with pytest.raises(Exception):
        await repo.add_messages(UUID(conversation["id"]), [
            {"id": duplicate, "role": "user", "content": "first"},
            {"id": duplicate, "role": "assistant", "content": "same primary key"},
        ])
    assert await count_messages(session_factory) == 0


@pytest.mark.asyncio
async def test_add_messages_rejects_missing_or_deleted_conversation_without_writing(repo, session_factory):
    with pytest.raises(ConversationNotFoundError):
        await repo.add_messages(uuid4(), [{"role": "user", "content": "x"}])
    conversation = await new_conversation(repo)
    assert await repo.update_conversation(
        UUID(conversation["id"]), {"deleted_at": datetime.now(timezone.utc)}, "owner"
    )
    with pytest.raises(ConversationNotFoundError):
        await repo.add_messages(UUID(conversation["id"]), [{"role": "user", "content": "x"}])
    assert await count_messages(session_factory) == 0
    assert await repo.add_messages(uuid4(), []) == []


# ── explicit scopes ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_reads_are_scoped_and_none_never_means_everything(repo):
    conversation = await new_conversation(repo)
    conversation_id = UUID(conversation["id"])

    assert (await repo.get_conversation(conversation_id, 5, "owner"))["id"] == conversation["id"]
    assert await repo.get_conversation(conversation_id, 5, "other") is None
    with pytest.raises(ConversationScopeRequiredError):
        await repo.get_conversation(conversation_id, 5, None)
    with pytest.raises(ConversationScopeRequiredError):
        await repo.update_conversation(conversation_id, {"title": "x"}, None)
    with pytest.raises(ConversationScopeRequiredError):
        await repo.list_conversations_for_owner(None)


@pytest.mark.asyncio
async def test_admin_read_sees_any_conversation_but_not_deleted_ones(repo):
    conversation = await new_conversation(repo, owner="other")
    conversation_id = UUID(conversation["id"])
    found = await repo.get_conversation_as_admin(conversation_id, 5)
    assert found["owner"]["id"] == "other"
    await repo.update_conversation(conversation_id, {"deleted_at": datetime.now(timezone.utc)}, "other")
    assert await repo.get_conversation_as_admin(conversation_id, 5) is None


@pytest.mark.asyncio
async def test_update_only_affects_owned_conversation(repo):
    conversation = await new_conversation(repo)
    conversation_id = UUID(conversation["id"])
    assert await repo.update_conversation(conversation_id, {"title": "hijack"}, "other") is False
    assert await repo.update_conversation(conversation_id, {"title": "mine"}, "owner") is True
    assert (await repo.get_conversation(conversation_id, 5, "owner"))["title"] == "mine"


@pytest.mark.asyncio
async def test_use_case_refuses_unscoped_get_conversation(repo):
    use_case = ConversationUseCase(repo)
    conversation = await new_conversation(repo)
    with pytest.raises(ConversationScopeRequiredError):
        await use_case.get_conversation(UUID(conversation["id"]), None)
    assert await use_case.get_conversation(UUID(conversation["id"]), "owner")
    assert await use_case.get_conversation_for_owner(UUID(conversation["id"]), "other") is None
    assert await use_case.get_conversation_as_admin(UUID(conversation["id"]))


# ── listing ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_is_ordered_by_updated_at_desc_and_paginated(repo, session_factory):
    base = datetime.now(timezone.utc)
    ids = []
    for index in range(5):
        conversation = await new_conversation(repo, title=f"c{index}")
        ids.append(conversation["id"])
        async with session_factory() as session:
            (await session.get(ConversationModel, conversation["id"])).updated_at = base + timedelta(minutes=index)
            await session.commit()
    await new_conversation(repo, owner="other", title="not mine")

    everything = await repo.list_conversations_for_owner("owner")
    assert [c["title"] for c in everything] == ["c4", "c3", "c2", "c1", "c0"]
    assert all(c["owner"]["id"] == "owner" for c in everything)
    page = await repo.list_conversations_for_owner("owner", limit=2, offset=2)
    assert [c["title"] for c in page] == ["c2", "c1"]
    assert len(await repo.list_conversations_as_admin()) == 6


@pytest.mark.asyncio
async def test_list_excludes_deleted_and_caps_page_size(repo, session_factory):
    gone = await new_conversation(repo, title="gone")
    await new_conversation(repo, title="kept")
    await repo.update_conversation(UUID(gone["id"]), {"deleted_at": datetime.now(timezone.utc)}, "owner")
    assert [c["title"] for c in await repo.list_conversations_for_owner("owner")] == ["kept"]

    async with session_factory() as session:
        session.add_all(
            ConversationModel(id=str(uuid4()), user_id="owner", title=f"bulk{i}")
            for i in range(MAX_CONVERSATION_PAGE_SIZE + 20)
        )
        await session.commit()
    assert len(await repo.list_conversations_for_owner("owner", limit=10_000)) == MAX_CONVERSATION_PAGE_SIZE
    assert len(await repo.list_conversations_for_owner("owner", limit=0)) == 1  # clamped to >= 1


def test_message_table_has_conversation_index():
    index_names = {index.name for index in MessageModel.__table__.indexes}
    assert "ix_messages_conversation_id_created_at" in index_names


def test_removed_dead_code_stays_removed():
    assert not hasattr(ConversationRepository, "get_conversation_messages")
    assert not hasattr(ConversationUseCase, "get_messages")
