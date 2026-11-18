"""Sliding-window limiter, shared FastAPI dependency and auth endpoint limits."""
import threading

from dependency_injector import providers
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from config.container import container
from main import create_app
from src.common.application.rate_limiter import SlidingWindowRateLimiter, hashed_key
from src.common.presentation.error_handlers import register_error_handlers
from src.common.presentation.rate_limit import RateLimitConfig, rate_limit


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_limiter_blocks_after_limit_and_recovers_when_window_slides():
    clock = Clock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    assert [limiter.hit("k", 3, 60) for _ in range(3)] == [0, 0, 0]
    retry_after = limiter.hit("k", 3, 60)
    assert 1 <= retry_after <= 61
    clock.now += 59
    assert limiter.hit("k", 3, 60) > 0
    clock.now += 2
    assert limiter.hit("k", 3, 60) == 0


def test_blocked_attempts_are_not_recorded_so_penalty_does_not_grow():
    clock = Clock()
    limiter = SlidingWindowRateLimiter(clock=clock)
    limiter.hit("k", 1, 10)
    for _ in range(50):
        clock.now += 0.1
        assert limiter.hit("k", 1, 10) > 0
    clock.now += 6  # 11 seconds after the only recorded hit
    assert limiter.hit("k", 1, 10) == 0


def test_keys_are_independent():
    limiter = SlidingWindowRateLimiter(clock=Clock())
    assert limiter.hit("a", 1, 60) == 0
    assert limiter.hit("a", 1, 60) > 0
    assert limiter.hit("b", 1, 60) == 0


def test_expired_keys_are_garbage_collected():
    clock = Clock()
    limiter = SlidingWindowRateLimiter(sweep_interval_seconds=10, clock=clock)
    for index in range(100):
        limiter.hit(f"ip-{index}", 5, 30)
    assert len(limiter) == 100
    clock.now += 31
    limiter.hit("fresh", 5, 30)  # triggers a sweep
    assert len(limiter) == 1


def test_capacity_is_bounded_by_dropping_least_recently_used_keys():
    limiter = SlidingWindowRateLimiter(max_keys=10, clock=Clock())
    for index in range(50):
        limiter.hit(f"k{index}", 5, 60)
    assert len(limiter) == 10
    assert limiter.hit("k49", 1, 60) > 0  # most recent key survived and still counts


def test_disabled_limiter_never_blocks():
    limiter = SlidingWindowRateLimiter(enabled=False)
    assert all(limiter.hit("k", 1, 60) == 0 for _ in range(5))


def test_limiter_is_thread_safe():
    limiter = SlidingWindowRateLimiter()
    allowed = []

    def worker():
        for _ in range(50):
            allowed.append(limiter.hit("shared", 100, 60) == 0)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(allowed) == 100  # exactly the limit, no lost updates


def test_hashed_key_hides_identifier():
    assert "@" not in hashed_key("user@example.com")
    assert hashed_key("a") == hashed_key("a") != hashed_key("b")


def limited_app(**config) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.state.rate_limiter = SlidingWindowRateLimiter(clock=Clock())
    app.state.rate_limit_config = RateLimitConfig(**config)

    @app.get("/ping", dependencies=[Depends(rate_limit("ping_ip", default_limit=2))])
    def ping():
        return {"ok": True}

    return app


def test_dependency_returns_429_with_retry_after_and_detail_contract():
    with TestClient(limited_app()) as client:
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 200
        response = client.get("/ping")
    assert response.status_code == 429
    assert set(response.json()) == {"detail"}
    assert int(response.headers["Retry-After"]) >= 1


def test_configured_limit_overrides_default():
    app = limited_app(limits={"ping_ip": 1})
    with TestClient(app) as client:
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 429


def test_forwarded_for_is_ignored_unless_trusted_and_uses_right_most_entry():
    with TestClient(limited_app(limits={"ping_ip": 1})) as client:
        assert client.get("/ping", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
        # Spoofed header must not give a fresh bucket when the proxy is not trusted.
        assert client.get("/ping", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429

    with TestClient(limited_app(limits={"ping_ip": 1}, trust_forwarded_for=True)) as client:
        assert client.get("/ping", headers={"X-Forwarded-For": "9.9.9.9, 1.1.1.1"}).status_code == 200
        assert client.get("/ping", headers={"X-Forwarded-For": "8.8.8.8, 1.1.1.1"}).status_code == 429
        assert client.get("/ping", headers={"X-Forwarded-For": "9.9.9.9, 3.3.3.3"}).status_code == 200


def test_missing_limiter_state_disables_limit():
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(rate_limit("ping_ip", default_limit=1))])
    def ping():
        return {}

    with TestClient(app) as client:
        assert all(client.get("/ping").status_code == 200 for _ in range(3))


class FakeAuth:
    async def create_guest_session(self):
        return {
            "access_token": "a", "refresh_token": "r", "token_type": "bearer", "expires_in": 1,
            "user": {"id": "g", "email": None, "display_name": "Khach", "role": "guest",
                     "is_active": True, "created_at": "2026-01-01T00:00:00+00:00"},
        }

    async def login(self, email, password):
        from src.modules.auth.domain.errors import InvalidCredentialsError
        raise InvalidCredentialsError()

    async def refresh(self, refresh_token):
        from src.modules.auth.domain.errors import InvalidRefreshTokenError
        raise InvalidRefreshTokenError()


def auth_client():
    app = create_app()
    return app, container.auth_use_case.override(providers.Object(FakeAuth()))


def test_guest_endpoint_is_limited_per_ip():
    app, override = auth_client()
    with override, TestClient(app) as client:
        statuses = [client.post("/api/v1/auth/guest").status_code for _ in range(11)]
    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429


def test_login_is_limited_per_ip_and_per_email():
    app, override = auth_client()
    with override, TestClient(app) as client:
        # 5 attempts per e-mail per minute: the 6th is rejected before reaching the use case.
        codes = [client.post("/api/v1/auth/login", json={"email": "a@x.com", "password": "pw"}).status_code
                 for _ in range(6)]
        assert codes == [401] * 5 + [429]
        # The blocked attempt still counted against the IP (6 so far); 4 more are allowed.
        other = [client.post("/api/v1/auth/login", json={"email": f"u{i}@x.com", "password": "pw"}).status_code
                 for i in range(4)]
        assert other == [401] * 4
        blocked = client.post("/api/v1/auth/login", json={"email": "z@x.com", "password": "pw"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_email_limit_is_case_insensitive():
    app, override = auth_client()
    with override, TestClient(app) as client:
        for index in range(5):
            email = "Same@X.com" if index % 2 else " same@x.com "
            client.post("/api/v1/auth/login", json={"email": email, "password": "pw"})
        response = client.post("/api/v1/auth/login", json={"email": "SAME@x.com", "password": "pw"})
    assert response.status_code == 429


def test_refresh_endpoint_is_limited_per_ip():
    app, override = auth_client()
    with override, TestClient(app) as client:
        statuses = [client.post("/api/v1/auth/refresh", json={"refresh_token": "t"}).status_code
                    for _ in range(31)]
    assert statuses[:30] == [401] * 30
    assert statuses[30] == 429
