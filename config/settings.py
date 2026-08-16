from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import Optional


class LLMSettings(BaseModel):
    openai_api_key: str
    anthropic_api_key: Optional[str] = None
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 400


class VectorDBSettings(BaseModel):
    provider: str = "milvus"
    collection_name: str = "business_data"
    host: str = "localhost"
    port: int = 19530
    vector_dimension: int = 512
    metric_type: str = "L2"


class EmbeddingSettings(BaseModel):
    provider: str = "openai"
    model: str = "text-embedding-3-small"


class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    username: str = "congvq"
    password: str = "congvq"
    db_name: str = "ai_assistant"
    echo: bool = False

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.username}:{self.password}@{self.host}:{self.port}/{self.db_name}"


class CacheSettings(BaseModel):
    provider: str = "redis"
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None


class APISettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )


class AuthSettings(BaseModel):
    jwt_secret: str = "change-this-development-secret-key-before-production"
    jwt_issuer: str = "business-chatbot"
    jwt_audience: str = "business-chatbot-web"
    access_token_minutes: int = 15
    refresh_token_days: int = 30


class ETLSettings(BaseModel):
    source_path: str = ""
    mdb_member: Optional[str] = None
    mdb_password: str = ""
    output_dir: str = "data/etl"
    snapshot_dir: str = "data/documents"
    extract_config_path: str = "etl_business/stats/extract.yml"
    product_aliases_path: str = "etl_business/stats/product_aliases.json"
    lock_path: str = "data/etl/business-etl.lock"


class Settings(BaseSettings):
    """Main application settings — populated from local.yml via ConfigManager"""
    llm: LLMSettings
    vector_db: VectorDBSettings = VectorDBSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    database: DatabaseSettings = DatabaseSettings()
    cache: CacheSettings = CacheSettings()
    api: APISettings = APISettings()
    auth: AuthSettings = AuthSettings()
    etl: ETLSettings = ETLSettings()

    class Config:
        env_nested_delimiter = "__"
