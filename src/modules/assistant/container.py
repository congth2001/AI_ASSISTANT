"""Dependency wiring owned by the assistant module."""
from dependency_injector import containers
from dependency_injector.providers import Configuration, Dependency, Singleton

from src.modules.assistant.application.use_cases.chat_use_case import ChatUseCase
from src.modules.assistant.application.use_cases.search_documents_use_case import SearchDocumentsUseCase
from src.modules.assistant.application.use_cases.text_to_sql_use_case import TextToSQLUseCase
from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.application.services.query_contextualizer import QueryContextualizer
from src.modules.assistant.application.services.intent_classifier import IntentClassifier
from src.modules.assistant.application.services.context_builder import ContextBuilder
from src.modules.assistant.application.services.schema_linker import SchemaLinker
from src.modules.assistant.application.services.sql_service import SQLService
from src.modules.assistant.application.agent.tools.text_to_sql_tool import TextToSQLTool
from src.modules.assistant.application.agent.tools.rag_tool import RAGTool
from src.modules.assistant.application.agent.agent_service import AgentService
from src.modules.assistant.infrastructure.database.postgres_sql_executor import PostgresSQLExecutor
from src.modules.assistant.infrastructure.repositories.milvus_search_repository import (
    MilvusSearchRepository,
)
from src.modules.assistant.infrastructure.repositories.milvus_ingestion_repository import (
    MilvusIngestionRepository,
)
from src.modules.assistant.infrastructure.database.milvus_client import MilvusClient
from src.modules.assistant.infrastructure.llm.openai_adapter import OpenAIAdapter
from src.modules.assistant.infrastructure.llm.openai_embedding import OpenAIEmbedding
from src.modules.assistant.infrastructure.cache.redis_cache import RedisCache


class AssistantContainer(containers.DeclarativeContainer):
    config = Configuration()
    engine = Dependency()
    customer_repo = Dependency()
    sales_invoice_line_repo = Dependency()
    conversation_repo = Dependency()

    milvus_client = Singleton(
        MilvusClient,
        host=config.vector_db.host,
        port=config.vector_db.port,
        collection_name=config.vector_db.collection_name,
        vector_dimension=config.vector_db.vector_dimension,
        metric_type=config.vector_db.metric_type,
    )

    llm_service = Singleton(
        OpenAIAdapter, api_key=config.llm.openai_api_key, model=config.llm.model
    )

    embedding_service = Singleton(
        OpenAIEmbedding,
        api_key=config.llm.openai_api_key,
        model=config.embedding.model,
        vector_dimension=config.vector_db.vector_dimension,
    )

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

    cache_service = Singleton(
        RedisCache,
        host=config.cache.host,
        port=config.cache.port,
        db=config.cache.db,
        password=config.cache.password,
    )

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

    sql_executor = Singleton(
        PostgresSQLExecutor,
        engine=engine,
    )

    schema_linker = Singleton(SchemaLinker)

    sql_service = Singleton(SQLService, llm_service=llm_service)

    text_to_sql_use_case = Singleton(
        TextToSQLUseCase,
        sql_executor=sql_executor,
        schema_linker=schema_linker,
        sql_service=sql_service,
    )

    search_documents_use_case = Singleton(
        SearchDocumentsUseCase,
        search_repo=milvus_search_repository,
        query_analyzer=query_analyzer,
    )

    text_to_sql_tool = Singleton(
        TextToSQLTool,
        text_to_sql_use_case=text_to_sql_use_case,
    )

    rag_tool = Singleton(
        RAGTool,
        search_use_case=search_documents_use_case,
        context_builder=context_builder,
    )

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
