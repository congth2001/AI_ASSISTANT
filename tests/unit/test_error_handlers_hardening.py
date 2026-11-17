"""429 mapping, 5xx logging and the catch-all handler."""
import logging

from dependency_injector import providers
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.container import Container
from src.common.errors import ApplicationError, ErrorType, InternalError, NotFoundError, RateLimitedError
from src.common.presentation.error_handlers import ERROR_STATUS, register_error_handlers
from src.modules.auth.domain.ports.i_password_hasher import IPasswordHasher


def test_rate_limited_error_carries_retry_after_and_has_its_own_status():
    error = RateLimitedError(retry_after=7)
    assert isinstance(error, ApplicationError)
    assert error.retry_after == 7 and error.code == "rate_limited"
    assert ERROR_STATUS[ErrorType.RATE_LIMITED] == 429
    assert RateLimitedError(retry_after=0).retry_after == 1


def _app_raising(error):
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/")
    def fail():
        raise error

    return app


def test_429_response_keeps_detail_contract_and_sets_retry_after():
    with TestClient(_app_raising(RateLimitedError(retry_after=12))) as client:
        response = client.get("/")
    assert response.status_code == 429
    assert response.json() == {"detail": RateLimitedError().message}
    assert response.headers["Retry-After"] == "12"


def test_5xx_application_errors_are_logged_with_cause(caplog):
    with caplog.at_level(logging.ERROR):
        with TestClient(_app_raising(InternalError())) as client:
            response = client.get("/")
    assert response.status_code == 500
    assert response.json() == {"detail": InternalError().message}
    assert any(record.name.endswith("error_handlers") and record.exc_info for record in caplog.records)


def test_4xx_application_errors_are_not_logged_as_errors(caplog):
    with caplog.at_level(logging.ERROR):
        with TestClient(_app_raising(NotFoundError())) as client:
            assert client.get("/").status_code == 404
    assert not caplog.records


def test_unexpected_exception_returns_generic_500_without_leaking_details(caplog):
    app = _app_raising(RuntimeError("secret connection string"))
    with caplog.at_level(logging.ERROR):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/")
    assert response.status_code == 500
    assert response.json() == {"detail": "internal_error"}
    assert "secret" not in response.text
    assert any(
        record.exc_info and "secret connection string" in str(record.exc_info[1])
        for record in caplog.records
    )


def test_sse_error_event_contract_is_not_changed_by_catch_all_handler():
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/stream")
    def stream():
        def events():
            yield 'data: {"type": "token", "content": "hi"}\n\n'
            yield 'data: {"type": "error", "message": "boom"}\n\n'

        return StreamingResponse(events(), media_type="text/event-stream")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/stream")
    assert response.status_code == 200
    assert response.text.endswith('data: {"type": "error", "message": "boom"}\n\n')


def test_conversation_use_case_has_one_provider_with_a_legacy_alias():
    container = Container()
    fake = object()
    assert container.use_case_conversation is container.conversation_use_case
    with container.conversation_use_case.override(providers.Object(fake)):
        assert container.use_case_conversation() is fake
    assert Container.use_case_conversation is Container.conversation_use_case


def test_password_hasher_port_is_async_and_exposes_a_dummy_hash():
    import inspect

    assert inspect.iscoroutinefunction(IPasswordHasher.hash)
    assert inspect.iscoroutinefunction(IPasswordHasher.verify)
    assert "dummy_hash" in IPasswordHasher.__abstractmethods__
