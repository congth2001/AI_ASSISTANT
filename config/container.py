from dependency_injector import containers
from dependency_injector.providers import Configuration, Dependency, Factory, Singleton

from src.application.use_cases.chat_use_case import ChatUseCase
from src.application.use_cases.ingest_data_use_case import IngestDataUseCase
from src.application.use_cases.query_report_use_case import QueryReportUseCase
from src.application.services.rag_orchestrator import RAGOrchestrator
from src.application.services.query_analyzer import QueryAnalyzer

from src.domain.services.intent_classifier import IntentClassifier
from src.domain.services.context_builder import ContextBuilder

from src.infrastructure.llm.openai_adapter import OpenAIAdapter
from src.infrastructure.repositories.milvus_ingestion_repository import MilvusIngestionRepository
from src.infrastructure.serializers.customer_serializer import CustomerSerializer
from src.infrastructure.serializers.period_summary_serializer import PeriodSummarySerializer
from src.infrastructure.serializers.transaction_serializer import TransactionSerializer
from src.infrastructure.vector_db.milvus_adapter import MilvusAdapter
from src.infrastructure.embedding.openai_embedding import OpenAIEmbedding
from src.infrastructure.persistence.conversation_repository import ConversationRepository
from src.infrastructure.persistence.business_data_repository import BusinessDataRepository
from src.infrastructure.cache.redis_cache import RedisCache

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


class Container(containers.DeclarativeContainer):
    """Dependency injection container"""

    # Configuration
    config = Configuration()

    # Database
    database_url = Dependency()
    engine = Singleton(
        create_async_engine,
        url=database_url,
        echo=False
    )

    session_factory = Singleton(
        sessionmaker,
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    # Domain Services
    intent_classifier = Singleton(IntentClassifier)
    context_builder = Singleton(ContextBuilder)

    # Infrastructure - LLM
    llm_service = Singleton(
        OpenAIAdapter,
        api_key=config.llm.openai_api_key,
        model=config.llm.model
    )

    # Infrastructure - Vector DB
    vector_db = Singleton(
        MilvusAdapter,
        uri=config.vector_db.uri
    )

    # Infrastructure - Embedding
    embedding_service = Singleton(
        OpenAIEmbedding,
        api_key=config.llm.openai_api_key,
        model=config.embedding.model
    )

    # Infrastructure - Milvus repository
    milvus_ingestion_repository = Singleton(
        MilvusIngestionRepository,
        host=config.vector_db.host,
        port=config.vector_db.port,
        collection_name=config.vector_db.collection_name,
        embedding_service=embedding_service,
        embedding_dim=config.vector_db.vector_dimension
    )

    # Infrastructure - Persistence
    conversation_repo = Singleton(
        ConversationRepository,
        session_factory=session_factory
    )

    business_data_repo = Singleton(
        BusinessDataRepository,
        session_factory=session_factory
    )

    # Infrastructure - Cache
    cache_service = Singleton(
        RedisCache,
        host=config.cache.host,
        port=config.cache.port,
        db=config.cache.db,
        password=config.cache.password
    )

    # Infrastructure - Serializers
    transaction_serializer = Singleton(TransactionSerializer)
    customer_serializer = Singleton(CustomerSerializer)
    period_serializer = Singleton(PeriodSummarySerializer)

    # Application Services
    rag_orchestrator = Singleton(
        RAGOrchestrator,
        vector_db=vector_db,
        embedding_service=embedding_service,
        llm_service=llm_service,
        context_builder=context_builder
    )

    query_analyzer = Singleton(
        QueryAnalyzer,
        context_builder=context_builder
    )

    # Use Cases
    chat_use_case = Singleton(
        ChatUseCase,
        llm_service=llm_service,
        conversation_repo=conversation_repo,
        intent_classifier=intent_classifier,
        context_builder=context_builder
    )

    ingest_data_use_case = Singleton(
        IngestDataUseCase,
        transaction_serializer=transaction_serializer,
        customer_serializer=customer_serializer,
        period_serializer=period_serializer,
        repository=milvus_ingestion_repository,
    )

    query_report_use_case = Singleton(
        QueryReportUseCase,
        data_repo=business_data_repo,
        llm_service=llm_service
    )


# Global container instance
container = Container()