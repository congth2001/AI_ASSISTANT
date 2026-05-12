from dependency_injector import containers, providers
from dependency_injector.providers import Factory, Singleton

from src.application.use_cases.chat_use_case import ChatUseCase
from src.application.use_cases.ingest_data_use_case import IngestDataUseCase
from src.application.use_cases.query_report_use_case import QueryReportUseCase
from src.application.services.rag_orchestrator import RAGOrchestrator
from src.application.services.query_analyzer import QueryAnalyzer

from src.domain.services.intent_classifier import IntentClassifier
from src.domain.services.context_builder import ContextBuilder

from src.infrastructure.llm.openai_adapter import OpenAIAdapter
from src.infrastructure.vector_db.chroma_adapter import ChromaAdapter
from src.infrastructure.embedding.openai_embedding import OpenAIEmbeddingService
from src.infrastructure.persistence.conversation_repository import ConversationRepository
from src.infrastructure.persistence.business_data_repository import BusinessDataRepository
from src.infrastructure.cache.redis_cache import RedisCache

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


class Container(containers.DeclarativeContainer):
    """Dependency injection container"""

    # Configuration
    config = providers.Configuration()

    # Database
    database_url = providers.Dependency()
    engine = providers.Singleton(
        create_async_engine,
        url=database_url,
        echo=False
    )

    session_factory = providers.Singleton(
        sessionmaker,
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    # Domain Services
    intent_classifier = providers.Singleton(IntentClassifier)
    context_builder = providers.Singleton(ContextBuilder)

    # Infrastructure - LLM
    llm_service = providers.Singleton(
        OpenAIAdapter,
        api_key=config.llm.openai_api_key,
        model=config.llm.model
    )

    # Infrastructure - Vector DB
    vector_db = providers.Singleton(
        ChromaAdapter,
        collection_name=config.vector_db.collection_name,
        persist_directory=config.vector_db.persist_directory
    )

    # Infrastructure - Embedding
    embedding_service = providers.Singleton(
        OpenAIEmbeddingService,
        api_key=config.llm.openai_api_key,
        model=config.embedding.model
    )

    # Infrastructure - Persistence
    conversation_repo = providers.Singleton(
        ConversationRepository,
        session_factory=session_factory
    )

    business_data_repo = providers.Singleton(
        BusinessDataRepository,
        session_factory=session_factory
    )

    # Infrastructure - Cache
    cache_service = providers.Singleton(
        RedisCache,
        host=config.cache.host,
        port=config.cache.port,
        db=config.cache.db,
        password=config.cache.password
    )

    # Application Services
    rag_orchestrator = providers.Singleton(
        RAGOrchestrator,
        vector_db=vector_db,
        embedding_service=embedding_service,
        llm_service=llm_service,
        context_builder=context_builder
    )

    query_analyzer = providers.Singleton(
        QueryAnalyzer,
        context_builder=context_builder
    )

    # Use Cases
    chat_use_case = providers.Singleton(
        ChatUseCase,
        llm_service=llm_service,
        conversation_repo=conversation_repo,
        intent_classifier=intent_classifier,
        context_builder=context_builder
    )

    ingest_data_use_case = providers.Singleton(
        IngestDataUseCase,
        data_repo=business_data_repo,
        vector_db=vector_db,
        embedding_service=embedding_service
    )

    query_report_use_case = providers.Singleton(
        QueryReportUseCase,
        data_repo=business_data_repo,
        llm_service=llm_service
    )


# Global container instance
container = Container()