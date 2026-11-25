"""Validated application settings and Pydantic source precedence."""
import re
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
    # Used when the collection (and its index) is created; searches follow the existing index.
    metric_type: Literal["L2", "IP", "COSINE"] = "COSINE"

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
    username: NonEmpty = "postgres"
    password: SecretStr = SecretStr("")
    db_name: NonEmpty = "ai_assistant"
    echo: bool = False
    # Driver query options may carry credentials (e.g. sslpassword): keep them out of repr().
    query: dict[str, str | tuple[str, ...]] = Field(default_factory=dict, repr=False)
    # NOLOGIN role (SELECT on the sales tables only) that LLM-generated SQL runs under via
    # SET LOCAL ROLE; created by Alembic. Empty/null disables the switch (not recommended).
    sql_reader_role: str | None = "sales_sql_reader"

    @model_validator(mode="before")
    @classmethod
    def accept_url(cls, value):
        return expand_database_url(value)

    @field_validator("query", mode="before")
    @classmethod
    def accept_url_query(cls, value):
        return dict(value) if isinstance(value, tuple) else value

    @field_validator("sql_reader_role", mode="before")
    @classmethod
    def validate_sql_reader_role(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value.strip()):
            raise ValueError("sql_reader_role must be a lower-case PostgreSQL identifier")
        return value.strip()

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
        """Unmasked URL for drivers only.

        WARNING: contains the plaintext password. Never log, print or include it in an error
        message; use ``sqlalchemy_url.render_as_string(hide_password=True)`` for display.
        """
        return self.sqlalchemy_url.render_as_string(hide_password=False)


class CacheSettings(ConfigModel):
    provider: Literal["redis"] = "redis"
    host: NonEmpty = "localhost"
    port: Port = 6379
    db: int = Field(default=0, ge=0)
    password: SecretStr | None = None


def normalize_origin(value: str) -> str:
    origin = value.strip().rstrip("/")
    if origin == "*" or "*" in origin:
        raise ValueError("CORS origins must be explicit; wildcard origins are not allowed")
    scheme, separator, host = origin.partition("://")
    if scheme not in {"http", "https"} or not separator or not host or "/" in host:
        raise ValueError("CORS origin must look like http(s)://host[:port]")
    return origin


class APISettings(ConfigModel):
    # Loopback by default; bind 0.0.0.0 explicitly (api.host) when the API must be reachable remotely.
    host: NonEmpty = "127.0.0.1"
    port: Port = 8000
    debug: bool = False
    # Swagger UI and ReDoc; disable (api.docs_enabled: false) on public deployments.
    docs_enabled: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    # Deployed frontend origins; the legacy PUBLIC_FRONTEND_ORIGINS env var is merged in main.py.
    public_frontend_origins: list[str] = Field(default_factory=list)

    @field_validator("cors_origins", "public_frontend_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        return [normalize_origin(value) for value in values]


class RateLimitSettings(ConfigModel):
    """In-memory, per-process sliding-window limits for auth and chat endpoints."""
    enabled: bool = True
    window_seconds: int = Field(default=60, gt=0)
    login_per_ip: int = Field(default=10, gt=0)
    login_per_email: int = Field(default=5, gt=0)
    guest_per_ip: int = Field(default=10, gt=0)
    refresh_per_ip: int = Field(default=30, gt=0)
    # /chat and /chat/stream: each request may run several LLM calls and SQL queries.
    chat_per_user: int = Field(default=20, gt=0)
    # Guest sessions are free to create, so guests are also limited per client IP.
    chat_guest_per_ip: int = Field(default=10, gt=0)
    # Read the client IP from the right-most X-Forwarded-For entry. Enable only behind one
    # trusted reverse proxy (ngrok, Cloudflare tunnel); otherwise clients could spoof it.
    trust_forwarded_for: bool = False

    def limits(self) -> dict[str, int]:
        return {
            "login_ip": self.login_per_ip,
            "login_email": self.login_per_email,
            "guest_ip": self.guest_per_ip,
            "refresh_ip": self.refresh_per_ip,
            "chat_user": self.chat_per_user,
            "chat_guest_ip": self.chat_guest_per_ip,
        }


class AuthSettings(ConfigModel):
    jwt_secret: SecretStr
    jwt_issuer: NonEmpty = "business-chatbot"
    jwt_audience: NonEmpty = "business-chatbot-web"
    access_token_minutes: int = Field(default=15, gt=0)
    refresh_token_days: int = Field(default=30, gt=0)
    # Seconds after a refresh token is rotated during which replaying it only returns 401.
    # 0 (default) treats any replay as theft and revokes all of the user's refresh tokens;
    # set a few seconds if several browser tabs may refresh with the same token concurrently.
    refresh_reuse_grace_seconds: int = Field(default=30, ge=0, le=60)
    # Lifetime of a stateless guest access token (no refresh token, no users row).
    guest_token_minutes: int = Field(default=60, gt=0, le=24 * 60)

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
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    etl: ETLSettings = Field(default_factory=ETLSettings)

    def to_container_config(self) -> dict[str, Any]:
        """Unwrap secrets only at the DI boundary; model_dump/repr remain redacted.

        WARNING: the returned dict (and ``["database"]["url"]``) contains plaintext secrets
        (API keys, JWT secret, passwords). Pass it straight to the DI container; never log,
        print, serialize or attach it to an error.
        """
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
