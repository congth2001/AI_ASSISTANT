from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.application.use_cases.conversation_use_case import ConversationUseCase
from src.domain.entities.conversation import Conversation
from src.domain.entities.message import Message
from src.domain.time import as_vietnam_time, now_vietnam
from src.infrastructure.repositories.conversation_repository import ConversationRepository


def test_vietnam_clock_is_timezone_aware():
    assert now_vietnam().utcoffset() == timedelta(hours=7)
    assert Conversation().created_at.utcoffset() == timedelta(hours=7)
    assert Message().timestamp.utcoffset() == timedelta(hours=7)


def test_legacy_naive_utc_timestamp_is_converted_to_vietnam_time():
    legacy_utc = datetime(2026, 7, 23, 3, 30)

    converted = as_vietnam_time(legacy_utc)

    assert converted.isoformat() == "2026-07-23T10:30:00+07:00"


def test_repository_serializes_chat_timestamps_with_vietnam_offset():
    row = SimpleNamespace(
        created_at=datetime(2026, 7, 23, 3, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc),
        deleted_at=None,
    )

    serialized = ConversationRepository._to_dict(row)

    assert serialized["created_at"].isoformat() == "2026-07-23T10:30:00+07:00"
    assert serialized["updated_at"].isoformat() == "2026-07-23T11:00:00+07:00"


def test_repository_serializes_conversation_owner_summary():
    owner = SimpleNamespace(
        id="staff-1",
        display_name="Nguyễn Văn A",
        email="staff@example.com",
        role="staff",
    )

    assert ConversationRepository._owner_to_dict(owner) == {
        "id": "staff-1",
        "display_name": "Nguyễn Văn A",
        "email": "staff@example.com",
        "role": "staff",
    }


class RecordingConversationRepository:
    def __init__(self):
        self.updates = None

    async def update_conversation(self, conversation_id, updates, user_id):
        self.updates = (conversation_id, updates, user_id)
        return True


@pytest.mark.asyncio
async def test_conversation_updates_use_vietnam_time():
    repository = RecordingConversationRepository()
    use_case = ConversationUseCase(repository)

    await use_case.rename_conversation(uuid4(), "Tên mới", "staff-1")

    assert repository.updates[1]["updated_at"].utcoffset() == timedelta(hours=7)
