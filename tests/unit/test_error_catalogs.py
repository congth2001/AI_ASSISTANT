"""Protect central catalogs and their public HTTP/SSE contracts."""
import ast
import importlib
import inspect
import json
import string
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.errors import (
    ApplicationError, ConflictError, NotFoundError, PermissionDeniedError,
    UnauthorizedError, ValidationError, RequestValidationError,
)
from src.common.presentation.error_handlers import register_error_handlers
from src.modules.analytics.domain.errors import InvalidCustomerOverviewCursorError

MODULES = Path(__file__).resolve().parents[2] / "src/modules"


def test_module_errors_are_declared_and_rendered_in_catalogs():
    violations = []
    for source in MODULES.rglob("*.py"):
        if source.name == "errors.py":
            assert source.parent.name == "domain"
            continue
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and node.name.endswith(("Error", "Timeout")):
                violations.append(f"{source}:{node.lineno}: error class outside catalog")
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                call = node.exc
                # Template parameters must be named; messages belong to catalogs.
                if any(isinstance(arg, (ast.Constant, ast.JoinedStr)) for arg in call.args):
                    violations.append(f"{source}:{node.lineno}: inline error message")
                if any(kw.arg == "detail" for kw in call.keywords):
                    violations.append(f"{source}:{node.lineno}: inline HTTP error")
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "error_code":
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            violations.append(f"{source}:{node.lineno}: inline error code")
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("module", ["auth", "assistant", "conversations", "analytics", "sales"])
def test_catalog_codes_are_unique_and_templates_have_named_parameters(module):
    catalog = importlib.import_module(f"src.modules.{module}.domain.errors")
    codes = set()
    for _, cls in inspect.getmembers(catalog, inspect.isclass):
        if cls.__module__ != catalog.__name__:
            continue
        assert issubclass(cls, ApplicationError)
        assert cls.code not in codes
        codes.add(cls.code)
        # Rendering every template catches mismatched placeholders without calling adapters.
        parameters = {
            name: "example" for _, name, _, _ in string.Formatter().parse(cls.message_template)
            if name is not None
        }
        assert cls(**parameters).message

    classes = {name: cls for name, cls in inspect.getmembers(catalog, inspect.isclass)}
    for source in (MODULES / module).rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            cls = classes.get(node.func.id)
            if cls is None or not issubclass(cls, ApplicationError):
                continue
            expected = {name for _, name, _, _ in string.Formatter().parse(cls.message_template) if name}
            actual = {kw.arg for kw in node.keywords}
            assert actual == expected, f"{source}:{node.lineno}: {actual} != {expected}"


@pytest.mark.parametrize("error,status", [
    (NotFoundError(), 404),
    (PermissionDeniedError(), 403),
    (UnauthorizedError(), 401),
    (ValidationError(), 400),
    (ConflictError(), 409),
    (RequestValidationError(error=InvalidCustomerOverviewCursorError()), 422),
])
def test_http_handler_preserves_detail_contract(error, status):
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/")
    def fail():
        raise error

    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == status
    assert response.json() == {"detail": error.message}


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_invalid_conversation_id_uses_module_validation_error(path):
    from tests.unit.test_module_api import client_for
    from src.modules.assistant.domain.errors import InvalidConversationIdError

    with client_for("staff", "owner") as client:
        response = client.post("/api/v1" + path, json={"message": "hi", "conversation_id": "bad-id"})
    assert response.status_code == 400
    assert response.json() == {"detail": InvalidConversationIdError().message}


def test_stream_failure_keeps_sse_contract_and_hides_adapter_details():
    from dependency_injector import providers
    from config.container import container
    from tests.unit.test_module_api import client_for, CONVERSATION_ID
    from src.modules.assistant.domain.errors import StreamingResponseFailedError

    class FailingChat:
        async def execute_stream(self, **kwargs):
            yield 'data: {"type": "token", "content": "hello"}\n\n'
            raise RuntimeError("private-adapter-details")

    with client_for("staff", "owner") as client:
        with container.chat_use_case.override(providers.Object(FailingChat())):
            response = client.post("/api/v1/chat/stream", json={
                "message": "hi", "conversation_id": CONVERSATION_ID,
            })
    assert response.status_code == 200
    events = [json.loads(event.removeprefix("data: ")) for event in response.text.strip().split("\n\n")]
    assert events[-1] == {"type": "error", "message": StreamingResponseFailedError().message}
    assert "private-adapter-details" not in response.text
