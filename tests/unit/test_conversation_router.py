"""Conversation HTTP behaviour: explicit scopes, 404 mapping, DTO limits, error logging."""
import logging
from contextlib import contextmanager

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from config.container import container
from main import create_app
from src.modules.auth.presentation.router import get_current_user
from src.modules.conversations.presentation.dto.conversation import (
    MAX_METADATA_BYTES,
    CreateConversationRequest,
    RenameConversationRequest,
)

CONVERSATION_ID = "b347c518-3648-4bf4-8d3f-37e210576ab3"


class FakeConversations:
    def __init__(self, *, owned=True, deleted=True, renamed=True, fail=False):
        self.calls = []
        self.owned, self.deleted, self.renamed, self.fail = owned, deleted, renamed, fail

    def _row(self, owner="owner"):
        return {"id": CONVERSATION_ID, "user_id": owner, "title": "T", "messages": []}

    async def get_conversation(self, conversation_id, user_id, turn_limit=50):
        self.calls.append(("owner", user_id))
        if self.fail:
            raise RuntimeError("private db details")
        return self._row(user_id) if self.owned or user_id == "owner" else None

    async def get_conversation_as_admin(self, conversation_id, turn_limit=50):
        self.calls.append(("admin", None))
        return self._row("owner")

    async def get_conversations_for_owner(self, owner_id, limit, offset):
        self.calls.append(("list_owner", owner_id, limit, offset))
        return [self._row(owner_id)]

    async def get_all_conversations_as_admin(self, limit, offset):
        self.calls.append(("list_admin", limit, offset))
        return [self._row("owner"), self._row("other")]

    async def create_conversation(self, title=None, user_id=None, metadata=None):
        self.calls.append(("create", user_id, title, metadata))
        return {"id": CONVERSATION_ID, "title": title, "user_id": user_id}

    async def rename_conversation(self, conversation_id, title, user_id):
        return self.renamed

    async def delete_conversation(self, conversation_id, user_id):
        return self.deleted


@contextmanager
def client_for(role, user_id, fake):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id, "role": role}
    with container.conversation_use_case.override(providers.Object(fake)), TestClient(app) as client:
        yield client


def test_admin_reads_through_explicit_admin_scope_and_staff_through_owner_scope():
    fake = FakeConversations()
    with client_for("admin", "admin-1", fake) as client:
        assert client.get(f"/api/v1/conversations/{CONVERSATION_ID}").status_code == 200
        assert len(client.get("/api/v1/conversations").json()) == 2
    assert fake.calls == [("admin", None), ("list_admin", 200, 0)]

    fake = FakeConversations()
    with client_for("staff", "owner", fake) as client:
        assert client.get(f"/api/v1/conversations/{CONVERSATION_ID}").status_code == 200
        assert len(client.get("/api/v1/conversations").json()) == 1
    assert fake.calls == [("owner", "owner"), ("list_owner", "owner", 200, 0)]


def test_list_pagination_parameters_are_validated_and_forwarded():
    fake = FakeConversations()
    with client_for("staff", "owner", fake) as client:
        assert client.get("/api/v1/conversations?limit=20&offset=40").status_code == 200
        assert client.get("/api/v1/conversations?limit=201").status_code == 422
        assert client.get("/api/v1/conversations?limit=0").status_code == 422
        assert client.get("/api/v1/conversations?offset=-1").status_code == 422
    assert fake.calls == [("list_owner", "owner", 20, 40)]


def test_admin_cannot_mutate_another_owners_conversation():
    fake = FakeConversations(owned=False)
    with client_for("admin", "admin-1", fake) as client:
        assert client.patch(f"/api/v1/conversations/{CONVERSATION_ID}", json={"title": "x"}).status_code == 403
        assert client.delete(f"/api/v1/conversations/{CONVERSATION_ID}").status_code == 403


def test_rename_and_delete_of_missing_conversation_are_404_not_500_or_200():
    fake = FakeConversations(owned=False)
    with client_for("staff", "stranger", fake) as client:
        assert client.get(f"/api/v1/conversations/{CONVERSATION_ID}").status_code == 404
        assert client.patch(f"/api/v1/conversations/{CONVERSATION_ID}", json={"title": "x"}).status_code == 404
        assert client.delete(f"/api/v1/conversations/{CONVERSATION_ID}").status_code == 404


def test_rename_deleted_concurrently_and_delete_race_return_404():
    with client_for("staff", "owner", FakeConversations(renamed=False)) as client:
        assert client.patch(f"/api/v1/conversations/{CONVERSATION_ID}", json={"title": "x"}).status_code == 404
    with client_for("staff", "owner", FakeConversations(deleted=False)) as client:
        assert client.delete(f"/api/v1/conversations/{CONVERSATION_ID}").status_code == 404
    with client_for("staff", "owner", FakeConversations()) as client:
        response = client.delete(f"/api/v1/conversations/{CONVERSATION_ID}")
    assert response.json() == {"conversation_id": CONVERSATION_ID, "status": "deleted"}


def test_unexpected_failure_is_logged_with_traceback_and_hidden_from_client(caplog):
    with caplog.at_level(logging.ERROR):
        with client_for("staff", "owner", FakeConversations(fail=True)) as client:
            response = client.get(f"/api/v1/conversations/{CONVERSATION_ID}")
    assert response.status_code == 500
    assert response.json() == {"detail": "Error retrieving conversation"}
    assert "private db details" not in response.text
    assert any(
        record.exc_info and "private db details" in str(record.exc_info[1])
        for record in caplog.records
    )


def test_create_ignores_client_supplied_user_id():
    fake = FakeConversations()
    with client_for("staff", "owner", fake) as client:
        response = client.post("/api/v1/conversations", json={"title": "T", "user_id": "someone-else"})
    assert response.status_code == 201
    assert fake.calls == [("create", "owner", "T", None)]
    assert "user_id" not in CreateConversationRequest.model_fields


def test_create_and_rename_limits():
    CreateConversationRequest(title="x" * 200)
    with pytest.raises(PydanticValidationError):
        CreateConversationRequest(title="x" * 201)
    with pytest.raises(PydanticValidationError):
        RenameConversationRequest(title="x" * 201)
    with pytest.raises(PydanticValidationError):
        RenameConversationRequest(title="")

    CreateConversationRequest(metadata={"k": "v" * 1000})
    with pytest.raises(PydanticValidationError, match="must not exceed"):
        CreateConversationRequest(metadata={"k": "v" * MAX_METADATA_BYTES})
    # Multi-byte text is measured in bytes, not characters.
    with pytest.raises(PydanticValidationError):
        CreateConversationRequest(metadata={"k": "é" * (MAX_METADATA_BYTES // 2)})


def test_oversized_metadata_is_rejected_over_http():
    fake = FakeConversations()
    with client_for("staff", "owner", fake) as client:
        response = client.post(
            "/api/v1/conversations", json={"title": "T", "metadata": {"k": "v" * MAX_METADATA_BYTES}}
        )
    assert response.status_code == 422
    assert fake.calls == []
