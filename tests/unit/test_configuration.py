"""Configuration contracts: source priority, secret protection and a shared database URL."""
import os
import runpy
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from config.config_manager import ConfigManager
from src.common.errors import ConfigurationError
from config.settings import AuthSettings, DatabaseSettings, Settings


BACKEND = Path(__file__).resolve().parents[2]
SECRET = "test-config-secret-with-at-least-thirty-two-characters"


@pytest.fixture(autouse=True)
def isolated_config_environment(monkeypatch):
    sections = {"LLM", "AUTH", "DATABASE", "CACHE", "API", "VECTOR_DB", "EMBEDDING", "ETL"}
    for key in list(os.environ):
        if key.upper().split("__")[0] in sections or key.upper() in {"DATABASE_URL", "AI_ASSISTANT_CONFIG_FILE"}:
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


def test_environment_dotenv_yaml_defaults_precedence_and_nested_merge(yaml_config, tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        'DATABASE__HOST=dotenv-host\nDATABASE__PASSWORD="001234"\n'
        'API__DEBUG=true\nAPI__CORS_ORIGINS=["https://example.test"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE__HOST", "environment-host")
    settings = ConfigManager(yaml_config, env_file=dotenv).get_settings()
    assert settings.database.host == "environment-host"
    assert settings.database.password.get_secret_value() == "001234"
    assert settings.database.port == 5432
    assert settings.llm.openai_api_key.get_secret_value() == "synthetic-key"
    assert settings.api.debug is True
    assert settings.api.cors_origins == ["https://example.test"]


def test_dotenv_is_optional_and_does_not_replace_yaml(yaml_config, tmp_path):
    settings = ConfigManager(yaml_config, env_file=tmp_path / "missing.env").get_settings()
    assert settings.database.host == "yaml-host"


def test_quoted_dotenv_values_and_comments_are_parsed_by_pydantic(yaml_config, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text('export DATABASE__PASSWORD="0012 # keep" # comment\n', encoding="utf-8")
    assert ConfigManager(yaml_config, env_file=dotenv).get_settings().database.password.get_secret_value() == "0012 # keep"


def test_yaml_selection_is_explicit_and_independent_of_working_directory(yaml_config, monkeypatch, tmp_path):
    import config.config_manager as configuration

    monkeypatch.setenv("AI_ASSISTANT_CONFIG_FILE", str(yaml_config))
    monkeypatch.chdir(tmp_path)
    assert ConfigManager(env_file=None).get_settings().database.host == "yaml-host"
    monkeypatch.setattr(configuration, "BACKEND_DIR", tmp_path)
    assert ConfigManager(yaml_config.name, env_file=None).get_settings().database.host == "yaml-host"


def test_explicit_argument_wins_over_config_file_environment(yaml_config, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ASSISTANT_CONFIG_FILE", str(tmp_path / "does-not-exist.yml"))
    assert ConfigManager(yaml_config, env_file=None).get_settings().database.host == "yaml-host"


def test_explicit_missing_file_fails_even_if_secrets_are_in_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM__OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("AUTH__JWT_SECRET", SECRET)
    with pytest.raises(FileNotFoundError):
        ConfigManager(tmp_path / "missing.yml", env_file=None).get_settings()


@pytest.mark.parametrize("missing", ["llm", "auth"])
def test_missing_required_configuration_fails(tmp_path, missing):
    data = {"llm": {"openai_api_key": "synthetic-key"}, "auth": {"jwt_secret": SECRET}}
    del data[missing]
    path = tmp_path / "missing.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=missing):
        ConfigManager(path, env_file=None).get_settings()


@pytest.mark.parametrize("secret", ["", "short", " " * 40,
    "change-this-development-secret-key-before-production", "replace-with-at-least-32-random-characters",
    " replace-with-at-least-32-random-characters "])
def test_jwt_secret_must_be_private_and_non_placeholder(secret):
    with pytest.raises(ValidationError):
        AuthSettings(jwt_secret=secret)


def test_secrets_are_redacted_but_are_unwrapped_for_di(yaml_config):
    settings = ConfigManager(yaml_config, env_file=None).get_settings()
    serialized = repr(settings) + settings.model_dump_json()
    for value in (SECRET, "synthetic-key", "yaml-password"):
        assert value not in serialized
    data = settings.to_container_config()
    assert data["auth"]["jwt_secret"] == SECRET
    assert data["llm"]["openai_api_key"] == "synthetic-key"
    assert data["database"]["url"].password == "yaml-password"


@pytest.mark.parametrize("password", ["001234", "p@ss:/?#% word", "đặc-biệt@123"])
def test_database_url_preserves_credentials(password):
    database = DatabaseSettings(username="user@name", password=password)
    parsed = make_url(database.url)
    assert parsed.username == "user@name"
    assert parsed.password == password
    assert parsed.host == "localhost"


def test_url_sources_and_component_overrides_obey_same_priority(yaml_config, tmp_path, monkeypatch):
    data = yaml.safe_load(yaml_config.read_text(encoding="utf-8"))
    data["database"] = {"url": "postgresql://yaml:password@yaml-host:5555/yaml-db?ssl=require"}
    yaml_config.write_text(yaml.safe_dump(data), encoding="utf-8")
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=postgresql://dotenv:pwd@dotenv-host/dotenv-db\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE__HOST", "environment-host")
    settings = ConfigManager(yaml_config, env_file=dotenv).get_settings()
    assert settings.database.host == "environment-host"
    assert settings.database.username == "dotenv"
    assert settings.database.db_name == "dotenv-db"
    assert settings.database.port == 5432
    assert settings.database.query == {}


def test_environment_dsn_overrides_dotenv_components(yaml_config, tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE__HOST=dotenv-host\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://env:password@environment-host/environment-db")
    assert ConfigManager(yaml_config, env_file=dotenv).get_settings().database.host == "environment-host"


def test_nested_database_url_wins_over_legacy_alias_within_source(yaml_config, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://old:pwd@old-host/old-db")
    monkeypatch.setenv("DATABASE__URL", "postgresql://new:pwd@new-host/new-db")
    assert ConfigManager(yaml_config, env_file=None).get_settings().database.host == "new-host"


@pytest.mark.parametrize("url", ["not-a-url", "sqlite:///wrong.db", "postgresql://user:pwd@host", ""])
def test_invalid_database_url_fails_without_leaking_credentials(yaml_config, monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ConfigurationError) as error:
        ConfigManager(yaml_config, env_file=None).get_settings()
    assert "user:pwd" not in str(error.value)


@pytest.mark.parametrize("key,value", [
    ("DATABASE__PORT", "0"), ("API__PORT", "65536"), ("AUTH__ACCESS_TOKEN_MINUTES", "-1"),
    ("AUTH__REFRESH_TOKEN_DAYS", "0"), ("VECTOR_DB__VECTOR_DIMENSION", "0"),
    ("CACHE__DB", "-1"), ("LLM__MAX_TOKENS", "0"), ("LLM__TEMPERATURE", "3"),
    ("EMBEDDING__PROVIDER", "unsupported"), ("CACHE__PROVIDER", "unsupported"),
    ("VECTOR_DB__PROVIDER", "unsupported"), ("LLM__OPENAI_API_KEY", ""),
])
def test_invalid_values_fail_before_connections(yaml_config, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigurationError):
        ConfigManager(yaml_config, env_file=None).get_settings()


def test_invalid_secret_error_does_not_expose_input(yaml_config, monkeypatch):
    monkeypatch.setenv("AUTH__JWT_SECRET", "sensitive-short-secret")
    with pytest.raises(ConfigurationError) as error:
        ConfigManager(yaml_config, env_file=None).get_settings()
    assert "sensitive-short-secret" not in str(error.value)


def test_reload_revalidates_both_settings_caches(yaml_config, monkeypatch):
    manager = ConfigManager(yaml_config, env_file=None)
    assert manager.get_settings() is manager.get_settings()
    monkeypatch.setenv("DATABASE__HOST", "after-reload")
    assert manager.get_database_settings().host == "yaml-host"
    assert manager.reload_config().database.host == "after-reload"
    assert manager.get_database_settings().host == "after-reload"


def test_alembic_and_backend_share_url_without_reading_ini_dsn(yaml_config, monkeypatch):
    import alembic
    import config.config_manager as configuration

    manager = ConfigManager(yaml_config, env_file=None)
    settings = manager.get_settings()
    monkeypatch.setattr(configuration, "get_database_settings", manager.get_database_settings)
    context = MagicMock()
    context.config = Config()
    context.config.set_main_option("sqlalchemy.url", "postgresql://wrong:wrong@wrong/wrong")
    context.is_offline_mode.return_value = True
    context.begin_transaction.side_effect = nullcontext
    monkeypatch.setattr(alembic, "context", context)
    runpy.run_path(str(BACKEND / "migrations/env.py"))
    assert context.configure.call_args.kwargs["url"] == settings.database.sqlalchemy_url


def test_database_only_configuration_does_not_require_llm_or_auth(tmp_path, monkeypatch):
    path = tmp_path / "database.yml"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://migration:pwd@migration-host/migration-db")
    database = ConfigManager(path, env_file=None).get_database_settings()
    assert database.host == "migration-host"
    assert database.sqlalchemy_url.drivername == "postgresql+asyncpg"


def test_environment_only_deployment_does_not_require_a_yaml_file(tmp_path, monkeypatch):
    import config.config_manager as configuration

    monkeypatch.setattr(configuration, "BACKEND_DIR", tmp_path)
    monkeypatch.setenv("LLM__OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("AUTH__JWT_SECRET", SECRET)
    manager = ConfigManager(env_file=None)
    assert manager.config_path is None
    assert manager.get_settings().auth.jwt_secret.get_secret_value() == SECRET


@pytest.mark.parametrize("text", ["[]", "unexpected: value", "database:\n  typo: invalid"])
def test_invalid_yaml_structure_or_unknown_keys_fail(tmp_path, text):
    path = tmp_path / "invalid.yml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        ConfigManager(path, env_file=None).get_settings()


def test_malformed_yaml_does_not_echo_secret_values(tmp_path):
    path = tmp_path / "invalid.yml"
    path.write_text('auth:\n  jwt_secret: "sensitive-unclosed-value', encoding="utf-8")
    with pytest.raises(ConfigurationError) as error:
        ConfigManager(path, env_file=None).get_settings()
    assert "sensitive-unclosed-value" not in str(error.value)


def test_dotenv_database_alias_overrides_yaml_url_query_options(yaml_config, tmp_path):
    data = yaml.safe_load(yaml_config.read_text(encoding="utf-8"))
    data["database"] = {"url": "postgresql://yaml:pwd@yaml-host/db?ssl=require&timeout=10"}
    yaml_config.write_text(yaml.safe_dump(data), encoding="utf-8")
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=postgresql://env:pwd@env-host/db?timeout=20\n", encoding="utf-8")
    assert ConfigManager(yaml_config, env_file=dotenv).get_database_settings().query == {"timeout": "20"}


def test_invalid_config_prevents_app_initialization(tmp_path, monkeypatch):
    import main

    path = tmp_path / "missing-secrets.yml"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(main, "get_settings", ConfigManager(path, env_file=None).get_settings)
    with pytest.raises(ConfigurationError, match="llm"):
        main.create_app()


def test_etl_uses_selected_project_configuration(yaml_config, tmp_path, monkeypatch):
    from etl_business.shop_data_extractor import config as extractor_config

    extraction = tmp_path / "extract.yml"
    extraction.write_text("datasets: {}", encoding="utf-8")
    data = yaml.safe_load(yaml_config.read_text(encoding="utf-8"))
    data["etl"] = {"extract_config_path": str(extraction), "mdb_password": "001234"}
    yaml_config.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setenv("AI_ASSISTANT_CONFIG_FILE", str(yaml_config))
    monkeypatch.setattr(extractor_config, "ConfigManager", lambda: ConfigManager(env_file=None))
    runtime = extractor_config.load_settings()["_runtime"]
    assert runtime["project_config_path"] == str(yaml_config)
    assert runtime["mdb_password"] == "001234"


@pytest.mark.asyncio
async def test_postgres_client_uses_same_url_as_settings(yaml_config):
    from config.container import Container

    settings = ConfigManager(yaml_config, env_file=None).get_settings()
    container = Container()
    container.config.from_dict(settings.to_container_config())
    client = container.postgres_client()
    try:
        assert client.engine.url == settings.database.sqlalchemy_url
    finally:
        await client.close()
