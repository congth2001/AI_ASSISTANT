"""Validated application settings and Pydantic source precedence."""
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


BACKEND_DIR = Path(__file__).resolve().parents[1]
Port = Annotated[int, Field(ge=1, le=65535)]
NonEmpty = Annotated[str, Field(min_length=1)]


def expand_database_url(value: Any) -> Any:
    """Expand a DSN before source merging so higher-priority components can override it."""
    if not isinstance(value, dict) or "url" not in value:
        return value
    components = dict(value)
    raw_url = components.pop("url")
    if isinstance(raw_url, SecretStr):
        raw_url = raw_url.get_secret_value()
    try:
        url = make_url(raw_url)
        if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
            raise ValueError
        if not url.host or not url.username or not url.database or "@" in url.host:
            raise ValueError
        parsed = {
            "host": url.host,
            "port": url.port if url.port is not None else 5432,
            "username": url.username,
            "password": url.password or "",
            "db_name": url.database,
            # A tuple replaces lower-source query options instead of deep-merging them.
            "query": tuple(url.query.items()),
        }
    except (ArgumentError, TypeError, ValueError):
        raise ValueError("Invalid PostgreSQL URL; percent-encode credentials in DSNs") from None
    # Explicit component fields win over the DSN within a single source.
    return {**parsed, **components}


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, validate_default=True)


class LLMSettings(ConfigModel):
    openai_api_key: SecretStr
    anthropic_api_key: SecretStr | None = None
    model: NonEmpty = "gpt-4o-mini"
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=400, gt=0)

    @field_validator("openai_api_key")
    @classmethod
    def require_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("OpenAI API key must not be blank")
        return value


class VectorDBSettings(ConfigModel):
    provider: Literal["milvus"] = "milvus"
    collection_name: NonEmpty = "business_data"
    host: NonEmpty = "localhost"
    port: Port = 19530
    vector_dimension: int = Field(default=1024, gt=0)
    metric_type: Literal["L2", "IP", "COSINE"] = "L2"

    @field_validator("metric_type", mode="before")
    @classmethod
    def normalize_metric(cls, value):
        return value.upper() if isinstance(value, str) else value


class EmbeddingSettings(ConfigModel):
    provider: Literal["openai"] = "openai"
    model: NonEmpty = "text-embedding-3-small"


class DatabaseSettings(ConfigModel):
    host: NonEmpty = "localhost"
    port: Port = 5432
    username: NonEmpty = "congvq"
    password: SecretStr = SecretStr("")
    db_name: NonEmpty = "ai_assistant"
    echo: bool = False
    query: dict[str, str | tuple[str, ...]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_url(cls, value):
        return expand_database_url(value)

    @field_validator("query", mode="before")
    @classmethod
    def accept_url_query(cls, value):
        return dict(value) if isinstance(value, tuple) else value

    @property
    def sqlalchemy_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.username,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.db_name,
            query=self.query,
        )

    @property
    def url(self) -> str:
        """Unmasked URL for drivers only; never log this value."""
        return self.sqlalchemy_url.render_as_string(hide_password=False)


class CacheSettings(ConfigModel):
    provider: Literal["redis"] = "redis"
    host: NonEmpty = "localhost"
    port: Port = 6379
    db: int = Field(default=0, ge=0)
    password: SecretStr | None = None


class APISettings(ConfigModel):
    host: NonEmpty = "0.0.0.0"
    port: Port = 8000
    debug: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )


class AuthSettings(ConfigModel):
    jwt_secret: SecretStr
    jwt_issuer: NonEmpty = "business-chatbot"
    jwt_audience: NonEmpty = "business-chatbot-web"
    access_token_minutes: int = Field(default=15, gt=0)
    refresh_token_days: int = Field(default=30, gt=0)

    @field_validator("jwt_secret")
    @classmethod
    def require_private_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        placeholders = {
            "change-this-development-secret-key-before-production",
            "replace-with-at-least-32-random-characters",
        }
        if len(secret.strip()) < 32 or secret.strip().lower() in placeholders:
            raise ValueError("JWT secret must contain at least 32 characters and must not be a sample value")
        return value


class ETLSettings(ConfigModel):
    source_path: str = ""
    mdb_member: str | None = None
    mdb_password: SecretStr = SecretStr("")
    output_dir: NonEmpty = "data/etl"
    snapshot_dir: NonEmpty = "data/documents"
    extract_config_path: NonEmpty = "etl_business/stats/extract.yml"
    product_aliases_path: NonEmpty = "etl_business/stats/product_aliases.json"
    customer_ward_aliases_path: NonEmpty = "etl_business/stats/customer_ward_aliases.json"
    lock_path: NonEmpty = "data/etl/business-etl.lock"
    opening_balance_date: str = "2019-01-01"

    @field_validator("opening_balance_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class SourceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
        hide_input_in_errors=True,
    )

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        def prepare(source, *, filter_unrelated=False):
            def load():
                data = dict(source())
                # Pydantic parses env and dotenv. Only map the supported legacy DSN name.
                legacy_url = getattr(source, "env_vars", {}).get("database_url")
                data.pop("database_url", None)
                if legacy_url is not None:
                    database = dict(data.get("database", {}))
                    database.setdefault("url", legacy_url)
                    data["database"] = database
                if filter_unrelated:
                    data = {key: value for key, value in data.items() if key in settings_cls.model_fields}
                if "database" in data:
                    data["database"] = expand_database_url(data["database"])
                return data
            return load

        # Init values are supplied by Pydantic's YAML source through ConfigManager.
        return (
            prepare(env_settings),
            prepare(dotenv_settings, filter_unrelated=True),
            prepare(init_settings),
        )


class DatabaseConfiguration(SourceSettings):
    """Same sources as the app, without unrelated API/auth requirements for Alembic."""
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)


class Settings(SourceSettings):
    llm: LLMSettings
    auth: AuthSettings
    vector_db: VectorDBSettings = Field(default_factory=VectorDBSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    api: APISettings = Field(default_factory=APISettings)
    etl: ETLSettings = Field(default_factory=ETLSettings)

    def to_container_config(self) -> dict[str, Any]:
        """Unwrap secrets only at the DI boundary; model_dump/repr remain redacted."""
        def unwrap(value):
            if isinstance(value, SecretStr):
                return value.get_secret_value()
            if isinstance(value, dict):
                return {key: unwrap(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [unwrap(item) for item in value]
            return value

        data = unwrap(self.model_dump())
        data["database"]["url"] = self.database.sqlalchemy_url
        return data
