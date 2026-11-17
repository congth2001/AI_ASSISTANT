"""HTTP regression checks for the separated chat and conversation routers."""
from contextlib import contextmanager

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from config.container import container
from main import create_app
from src.modules.auth.presentation.router import get_current_user


CONVERSATION_ID = "b347c518-3648-4bf4-8d3f-37e210576ab3"


class Conversations:
    async def get_conversation(self, conversation_id, user_id, turn_limit=None):
        if user_id in {None, "owner"}:
            return {"id": str(conversation_id), "user_id": "owner", "title": "Test", "messages": []}
        return None

    async def rename_conversation(self, *_args):
        return True

    async def delete_conversation(self, *_args):
        return True


class Chat:
    async def execute(self, **kwargs):
        return {
            "conversation_id": str(kwargs["conversation_id"]), "response": "OK",
            "intent": "conversation", "timestamp": "2026-10-16T12:00:00+07:00",
        }

    async def execute_stream(self, **_kwargs):
        yield 'data: {"type": "token", "content": "OK"}\n\n'
        yield 'data: {"type": "done"}\n\n'


@contextmanager
def client_for(role, user_id):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id, "role": role}
    with (
        container.use_case_conversation.override(providers.Object(Conversations())),
        container.chat_use_case.override(providers.Object(Chat())),
        TestClient(app) as client,
    ):
        yield client


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/chat", {"conversation_id": CONVERSATION_ID, "message": "hello"}),
    ("POST", "/chat/stream", {"conversation_id": CONVERSATION_ID, "message": "hello"}),
    ("PATCH", f"/conversations/{CONVERSATION_ID}", {"title": "New title"}),
    ("DELETE", f"/conversations/{CONVERSATION_ID}", None),
])
def test_admin_can_read_but_cannot_mutate_another_owners_conversation(method, path, body):
    with client_for("admin", "admin") as client:
        assert client.get(f"/api/v1/conversations/{CONVERSATION_ID}").status_code == 200
        assert client.request(method, "/api/v1" + path, json=body).status_code == 403


def test_owner_can_chat_stream_rename_and_delete_through_module_wiring():
    with client_for("staff", "owner") as client:
        payload = {"conversation_id": CONVERSATION_ID, "message": "hello"}
        assert client.post("/api/v1/chat", json=payload).json()["response"] == "OK"
        stream = client.post("/api/v1/chat/stream", json=payload)
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert 'data: {"type": "done"}\n\n' in stream.text
        assert client.patch(f"/api/v1/conversations/{CONVERSATION_ID}", json={"title": "New"}).status_code == 200
        assert client.delete(f"/api/v1/conversations/{CONVERSATION_ID}").json()["status"] == "deleted"


@pytest.mark.parametrize("role,user_id,status", [("staff", "someone-else", 404), ("guest", "guest", 403)])
def test_conversation_read_scope_is_preserved(role, user_id, status):
    with client_for(role, user_id) as client:
        assert client.get(f"/api/v1/conversations/{CONVERSATION_ID}").status_code == status
