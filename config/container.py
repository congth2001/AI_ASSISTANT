from dependency_injector import containers
from dependency_injector.providers import Configuration, Singleton

from src.application.use_cases.chat_use_case import ChatUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.application.use_cases.search_document_use_case import SearchDocumentsUseCase
from src.application.use_cases.analytics_use_case import AnalyticsUseCase
from src.application.use_cases.sync_business_data_use_case import (
    SyncBusinessDataUseCase,
)
from src.application.use_cases.conversation_use_case import ConversationUseCase
from src.application.services.query_analyzer import QueryAnalyzer
from src.application.services.query_contextualizer import QueryContextualizer
from src.application.services.intent_classifier import IntentClassifier
from src.application.services.context_builder import ContextBuilder
from src.application.services.schema_linker import SchemaLinker
from src.application.services.sql_service import SQLService
from src.application.agent.tools.text_to_sql import TextToSQLTool
from src.application.agent.tools.rag_tool import RAGTool
from src.application.agent.agent_service import AgentService

from src.infrastructure.repositories.analytics_repository import AnalyticsRepository
from src.infrastructure.repositories.auth_repository import AuthRepository
from src.infrastructure.repositories.milvus_search_repository import (
    MilvusSearchRepository,
)
from src.infrastructure.repositories.milvus_ingestion_repository import (
    MilvusIngestionRepository,
)
from src.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from src.infrastructure.repositories.customer_repository import CustomerRepository
from src.infrastructure.repositories.sales_invoice_repository import (
    SalesInvoiceRepository,
)
from src.infrastructure.repositories.sales_invoice_line_repository import (
    SalesInvoiceLineRepository,
)
from src.infrastructure.database.milvus_client import MilvusClient
from src.infrastructure.database.postgres_client import PostgresClient
from src.infrastructure.llm.openai_adapter import OpenAIAdapter
from src.infrastructure.llm.openai_embedding import OpenAIEmbedding
from src.infrastructure.cache.redis_cache import RedisCache


class Container(containers.DeclarativeContainer):
    """Dependency injection container"""

    # Configuration
    config = Configuration()

    # Database
    postgres_client = Singleton(
        PostgresClient,
        host=config.database.host,
        port=config.database.port,
        username=config.database.username,
        password=config.database.password,
        db_name=config.database.db_name,
        echo=config.database.echo,
    )

    session_factory = postgres_client.provided.session_factory

    milvus_client = Singleton(
        MilvusClient,
        host=config.vector_db.host,
        port=config.vector_db.port,
        collection_name=config.vector_db.collection_name,
        vector_dimension=config.vector_db.vector_dimension,
        metric_type=config.vector_db.metric_type,
    )

    # Infrastructure - LLM
    llm_service = Singleton(
        OpenAIAdapter, api_key=config.llm.openai_api_key, model=config.llm.model
    )

    # Infrastructure - Vector DB
    # vector_db = Singleton(
    #     MilvusClient,
    #     uri=config.vector_db.uri
    # )

    # Infrastructure - Embedding
    embedding_service = Singleton(
        OpenAIEmbedding,
        api_key=config.llm.openai_api_key,
        model=config.embedding.model,
        vector_dimension=config.vector_db.vector_dimension,
    )

    # Infrastructure - Milvus repository
    milvus_ingestion_repository = Singleton(
        MilvusIngestionRepository,
        client=milvus_client,
        embedding_service=embedding_service,
        embedding_dim=config.vector_db.vector_dimension,
    )

    milvus_search_repository = Singleton(
        MilvusSearchRepository,
        client=milvus_client,
        embedding_service=embedding_service,
    )

    # Infrastructure - Persistence
    conversation_repo = Singleton(
        ConversationRepository, session_factory=session_factory
    )

    customer_repo = Singleton(CustomerRepository, session_factory=session_factory)

    sales_invoice_repo = Singleton(
        SalesInvoiceRepository, session_factory=session_factory
    )

    sales_invoice_line_repo = Singleton(
        SalesInvoiceLineRepository, session_factory=session_factory
    )

    # Infrastructure - Cache
    cache_service = Singleton(
        RedisCache,
        host=config.cache.host,
        port=config.cache.port,
        db=config.cache.db,
        password=config.cache.password,
    )

    # Application Services
    context_builder = Singleton(ContextBuilder)

    intent_classifier = Singleton(
        IntentClassifier,
        llm_service=llm_service,
    )

    query_contextualizer = Singleton(
        QueryContextualizer,
        llm_service=llm_service,
    )

    query_analyzer = Singleton(
        QueryAnalyzer,
        customer_repo=customer_repo,
        good_repo=sales_invoice_line_repo,
    )

    analytics_repository = Singleton(
        AnalyticsRepository,
        engine=postgres_client.provided.engine,
    )

    # SQL pipeline services (steps 4-6)
    schema_linker = Singleton(SchemaLinker)
    sql_service = Singleton(SQLService, llm_service=llm_service)

    analytics_use_case = Singleton(
        AnalyticsUseCase,
        analytics_repo=analytics_repository,
        schema_linker=schema_linker,
        sql_service=sql_service,
    )

    # Use Cases
    search_documents_use_case = Singleton(
        SearchDocumentsUseCase,
        search_repo=milvus_search_repository,
        query_analyzer=query_analyzer,
    )

    sync_business_data_use_case = Singleton(
        SyncBusinessDataUseCase,
        customer_repository=customer_repo,
        sales_invoice_repository=sales_invoice_repo,
        sales_invoice_line_repository=sales_invoice_line_repo,
    )

    auth_repository = Singleton(AuthRepository, session_factory=session_factory)

    auth_use_case = Singleton(
        AuthUseCase,
        auth_repository=auth_repository,
        jwt_secret=config.auth.jwt_secret,
        jwt_issuer=config.auth.jwt_issuer,
        jwt_audience=config.auth.jwt_audience,
        access_token_minutes=config.auth.access_token_minutes,
        refresh_token_days=config.auth.refresh_token_days,
    )

    use_case_conversation = Singleton(
        ConversationUseCase,
        conversation_repo=conversation_repo,
    )

    # Agent tools
    text_to_sql_tool = Singleton(
        TextToSQLTool,
        analytics_use_case=analytics_use_case,
    )

    rag_tool = Singleton(
        RAGTool,
        search_use_case=search_documents_use_case,
        context_builder=context_builder,
    )

    # Agent service (holds compiled LangGraph)
    agent_service = Singleton(
        AgentService,
        classifier=intent_classifier,
        query_analyzer=query_analyzer,
        contextualizer=query_contextualizer,
        text_to_sql_tool=text_to_sql_tool,
        rag_tool=rag_tool,
        llm_service=llm_service,
    )

    chat_use_case = Singleton(
        ChatUseCase,
        agent_service=agent_service,
        conversation_repo=conversation_repo,
        cache_service=cache_service,
    )


# Global container instance
container = Container()
