"""Origins, docs toggle, rate-limit settings and secret hygiene of the configuration."""
import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from config.config_manager import ConfigManager
from config.settings import APISettings, DatabaseSettings, Settings
from src.common.errors import ConfigurationError

SECRET = "test-config-secret-with-at-least-thirty-two-characters"


@pytest.fixture(autouse=True)
def isolated_config_environment(monkeypatch):
    sections = {"LLM", "AUTH", "DATABASE", "CACHE", "API", "VECTOR_DB", "EMBEDDING", "ETL", "RATE_LIMIT"}
    for key in list(os.environ):
        if key.upper().split("__")[0] in sections or key.upper() in {
            "DATABASE_URL", "AI_ASSISTANT_CONFIG_FILE", "PUBLIC_FRONTEND_ORIGINS",
        }:
            monkeypatch.delenv(key)


@pytest.fixture
def yaml_config(tmp_path):
    path = tmp_path / "settings.yml"
    path.write_text(yaml.safe_dump({
        "llm": {"openai_api_key": "synthetic-key"},
        "auth": {"jwt_secret": SECRET},
        "database": {"host": "yaml-host", "password": "yaml-password"},
    }), encoding="utf-8")
    return path


def test_wildcard_and_malformed_origins_are_rejected():
    for bad in ("*", "https://*.example.com", "example.com", "ftp://example.com", "https://x.com/path"):
        with pytest.raises(ValidationError):
            APISettings(cors_origins=[bad])
        with pytest.raises(ValidationError):
            APISettings(public_frontend_origins=[bad])
    api = APISettings(public_frontend_origins=["https://App.example.com/"])
    assert api.public_frontend_origins == ["https://App.example.com"]


def test_public_origins_come_from_settings_and_legacy_environment_variable():
    import main

    api = APISettings(public_frontend_origins=["https://pages.example.com"])
    origins = main.resolve_cors_origins(api, " https://legacy.example.com/ ,https://pages.example.com,")
    assert origins == [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "https://pages.example.com", "https://legacy.example.com",
    ]
    with pytest.raises(ValueError):
        main.resolve_cors_origins(api, "*")


def test_legacy_origin_variable_reaches_cors_middleware(monkeypatch):
    import main

    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGINS", "https://legacy.example.com/")
    with TestClient(main.create_app()) as client:
        response = client.get("/health", headers={"Origin": "https://legacy.example.com"})
        rejected = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert response.headers["access-control-allow-origin"] == "https://legacy.example.com"
    assert "access-control-allow-origin" not in rejected.headers


def test_public_origins_can_be_set_through_environment(yaml_config, monkeypatch):
    monkeypatch.setenv("API__PUBLIC_FRONTEND_ORIGINS", '["https://env.example.com"]')
    settings = ConfigManager(yaml_config, env_file=None).get_settings()
    assert settings.api.public_frontend_origins == ["https://env.example.com"]


def test_api_defaults_are_safe_for_local_development(yaml_config):
    settings = ConfigManager(yaml_config, env_file=None).get_settings()
    assert settings.api.host == "127.0.0.1"
    assert settings.api.docs_enabled is True
    assert settings.database.username == "postgres"  # no personal account baked into defaults
    assert settings.rate_limit.enabled is True
    assert settings.rate_limit.limits() == {
        "login_ip": 10, "login_email": 5, "guest_ip": 10, "refresh_ip": 30,
        "chat_user": 20, "chat_guest_ip": 10,
    }
    assert settings.auth.refresh_reuse_grace_seconds == 30


def _settings_with(base: Settings, **sections) -> Settings:
    return Settings.model_construct(llm=base.llm, auth=base.auth, **sections)


def test_docs_can_be_disabled_by_configuration(monkeypatch):
    import main

    base = main.get_settings()
    settings = _settings_with(base, api=base.api.model_copy(update={"docs_enabled": False}))
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = main.create_app()
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/").json()["docs"] is None
        assert client.get("/health").status_code == 200


def test_docs_are_enabled_by_default():
    import main

    with TestClient(main.create_app()) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/").json()["docs"] == "/docs"


def test_rate_limit_settings_are_validated(yaml_config, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT__LOGIN_PER_IP", "0")
    with pytest.raises(ConfigurationError):
        ConfigManager(yaml_config, env_file=None).get_settings()
    monkeypatch.setenv("RATE_LIMIT__LOGIN_PER_IP", "3")
    monkeypatch.setenv("RATE_LIMIT__TRUST_FORWARDED_FOR", "true")
    settings = ConfigManager(yaml_config, env_file=None).get_settings()
    assert settings.rate_limit.login_per_ip == 3 and settings.rate_limit.trust_forwarded_for is True


def test_app_wires_rate_limit_settings_into_app_state(monkeypatch):
    import main

    base = main.get_settings()
    settings = _settings_with(
        base, rate_limit=base.rate_limit.model_copy(update={"guest_per_ip": 2, "window_seconds": 5}),
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    app = main.create_app()
    assert app.state.rate_limit_config.limits["guest_ip"] == 2
    assert app.state.rate_limit_config.window_seconds == 5


def test_repr_and_dumps_never_reveal_secrets(yaml_config):
    settings = ConfigManager(yaml_config, env_file=None).get_settings()
    dsn_settings = DatabaseSettings(
        url="postgresql://user:p%40ss-secret@host/db?sslpassword=query-secret"
    )
    rendered = " ".join([
        repr(settings), str(settings), repr(settings.database), repr(dsn_settings),
        settings.model_dump_json(),
    ])
    for secret in ("synthetic-key", SECRET, "yaml-password", "p@ss-secret", "p%40ss-secret", "query-secret"):
        assert secret not in rendered
    # The explicit unwrapping paths are documented as unsafe to log.
    assert "WARNING" in DatabaseSettings.url.fget.__doc__
    assert "WARNING" in Settings.to_container_config.__doc__


def test_obsolete_config_helpers_are_gone():
    import config.config_manager as module

    assert not hasattr(ConfigManager, "load_config")
    assert not hasattr(module, "reload_config")
    assert not (Path(__file__).resolve().parents[2] / "src/common/utils").exists()


def test_lifespan_closes_postgres_redis_and_milvus_even_if_one_fails(monkeypatch):
    import asyncio
    from dependency_injector import providers
    import main
    from config.container import container

    closed = []

    class Postgres:
        async def close(self):
            closed.append("postgres")

    class Redis:
        async def aclose(self):
            closed.append("redis")
            raise RuntimeError("redis is down")

    class Cache:
        redis = Redis()

    class Milvus:
        _connection = None

        def close(self):
            closed.append("milvus")

    async def run():
        async with main.lifespan(main.FastAPI()):
            assert closed == []

    with (
        container.postgres_client.override(providers.Object(Postgres())),
        container.cache_service.override(providers.Object(Cache())),
        container.milvus_client.override(providers.Object(Milvus())),
    ):
        asyncio.run(run())
    assert closed == ["redis", "milvus", "postgres"]
