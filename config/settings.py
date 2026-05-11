from pydantic_settings import BaseSettings
from typing import Optional


class LLMSettings(BaseSettings):
    """LLM configuration settings"""
    openai_api_key: str
    anthropic_api_key: Optional[str] = None
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 1000


class VectorDBSettings(BaseSettings):
    """Vector database configuration"""
    provider: str = "milvus"  # 'milvus' for Milvus
    collection_name: str = "business_data"
    host: str = "localhost"
    port: int = 19530
    vector_dimension: int = 512
    metric_type: str = "L2"  # L2 distance metric
    
    # Legacy settings (kept for compatibility)
    persist_directory: Optional[str] = None
    
    # Pinecone settings (if using Pinecone)
    pinecone_api_key: Optional[str] = None
    pinecone_environment: Optional[str] = None
    pinecone_index_name: Optional[str] = None


class EmbeddingSettings(BaseSettings):
    """Embedding service configuration"""
    provider: str = "openai"  # 'openai' only for now
    model: str = "text-embedding-3-small"


class DatabaseSettings(BaseSettings):
    """Database configuration"""
    url: str = "sqlite+aiosqlite:///./business_chatbot.db"
    echo: bool = False


class CacheSettings(BaseSettings):
    """Cache configuration"""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None


class APISettings(BaseSettings):
    """API configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False


class Settings(BaseSettings):
    """Main application settings"""
    llm: LLMSettings
    vector_db: VectorDBSettings
    embedding: EmbeddingSettings
    database: DatabaseSettings
    cache: CacheSettings
    api: APISettings

    class Config:
        env_nested_delimiter = "__"


# Global settings instance
settings = Settings()