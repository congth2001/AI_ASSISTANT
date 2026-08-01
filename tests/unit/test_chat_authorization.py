import pytest
from fastapi import HTTPException

from src.application.use_cases.chat_use_case import ChatUseCase
from src.presentation.api.v1.auth import require_role
from src.presentation.api.v1.chat import (
    conversation_read_scope,
    ensure_conversation_write_access,
)


class GuardedRepository:
    def __getattr__(self, name):
        async def forbidden(*_args, **_kwargs):
            raise AssertionError(f"Guest chat must not access repository method {name}")
        return forbidden


class GuardedCache(GuardedRepository):
    pass


class GuestAgent:
    def __init__(self, route):
        self.route = route
        self.stream_called = False

    async def classify_route(self, _query):
        return self.route

    async def stream_stateless_conversation(self, _query):
        self.stream_called = True
        yield "Xin "
        yield "chào"


def build_guest_chat(route):
    agent = GuestAgent(route)
    return ChatUseCase(agent, GuardedRepository(), GuardedCache()), agent


@pytest.mark.asyncio
async def test_guest_chat_is_stateless_and_never_accesses_repository():
    use_case, agent = build_guest_chat("conversation")

    result = await use_case.execute_guest("Xin chào")

    assert result["response"] == "Xin chào"
    assert result["conversation_id"] is None
    assert result["metadata"] == {"stateless": True, "data_access": False}
    assert agent.stream_called is True


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["text_to_sql", "rag", "hybrid"])
async def test_guest_cannot_ask_queries_that_require_business_tools(route):
    use_case, agent = build_guest_chat(route)

    with pytest.raises(PermissionError):
        await use_case.execute_guest("Cho tôi xem doanh thu cửa hàng")

    assert agent.stream_called is False


def test_staff_is_scoped_to_self_while_admin_has_global_scope():
    assert conversation_read_scope({"id": "staff-1", "role": "staff"}) == "staff-1"
    assert conversation_read_scope({"id": "admin-1", "role": "admin"}) is None


class OwnershipUseCase:
    async def get_conversation(self, _conversation_id, user_id, turn_limit=1):
        if user_id == "staff-owner":
            return {"id": "conversation-1", "user_id": "staff-owner"}
        if user_id is None:
            return {"id": "conversation-1", "user_id": "staff-owner"}
        return None


@pytest.mark.asyncio
async def test_admin_can_view_but_cannot_write_staff_conversation():
    with pytest.raises(HTTPException) as exc_info:
        await ensure_conversation_write_access(
            "conversation-1",
            {"id": "admin-1", "role": "admin"},
            OwnershipUseCase(),
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_conversation_owner_retains_write_access():
    await ensure_conversation_write_access(
        "conversation-1",
        {"id": "staff-owner", "role": "staff"},
        OwnershipUseCase(),
    )


@pytest.mark.asyncio
async def test_guest_is_rejected_by_staff_admin_role_dependency():
    dependency = require_role("staff", "admin")
    with pytest.raises(HTTPException) as exc_info:
        await dependency({"id": "guest-1", "role": "guest"})
    assert exc_info.value.status_code == 403
