"""Composition root: connect modules and expose stable provider names for entry points."""
from dependency_injector import containers, providers

from src.common.container import CommonContainer
from src.modules.auth.container import AuthContainer
from src.modules.conversations.container import ConversationsContainer
from src.modules.sales.container import SalesContainer
from src.modules.analytics.container import AnalyticsContainer
from src.modules.assistant.container import AssistantContainer


class Container(containers.DeclarativeContainer):
    config = providers.Configuration()
    common = providers.Container(CommonContainer, config=config)
    auth = providers.Container(AuthContainer, config=config, session_factory=common.session_factory)
    conversations = providers.Container(ConversationsContainer, session_factory=common.session_factory)
    sales = providers.Container(SalesContainer, session_factory=common.session_factory)
    analytics = providers.Container(AnalyticsContainer, session_factory=common.session_factory)
    assistant = providers.Container(
        AssistantContainer,
        config=config,
        engine=common.postgres_client.provided.engine,
        customer_repo=sales.customer_repo,
        sales_invoice_line_repo=sales.sales_invoice_line_repo,
        conversation_repo=conversations.conversation_repo,
    )

    # Provider aliases keep CLI entry points and dependency overrides stable.
    postgres_client = common.postgres_client
    session_factory = common.session_factory
    auth_repository = auth.auth_repository
    auth_use_case = auth.auth_use_case
    conversation_repo = conversations.conversation_repo
    conversation_use_case = conversations.conversation_use_case
    use_case_conversation = conversation_use_case  # legacy alias (same provider)
    customer_repo = sales.customer_repo
    sales_invoice_repo = sales.sales_invoice_repo
    sales_invoice_line_repo = sales.sales_invoice_line_repo
    customer_debt_transaction_repo = sales.customer_debt_transaction_repo
    sales_return_repo = sales.sales_return_repo
    sync_business_data_use_case = sales.sync_business_data_use_case
    dashboard_analytics_repository = analytics.dashboard_analytics_repository
    dashboard_analytics_use_case = analytics.dashboard_analytics_use_case
    customer_debt_workbook_exporter = analytics.customer_debt_workbook_exporter
    export_customer_debt_use_case = analytics.export_customer_debt_use_case
    order_ledger_workbook_exporter = analytics.order_ledger_workbook_exporter
    export_order_ledger_use_case = analytics.export_order_ledger_use_case
    milvus_client = assistant.milvus_client
    llm_service = assistant.llm_service
    embedding_service = assistant.embedding_service
    milvus_ingestion_repository = assistant.milvus_ingestion_repository
    milvus_search_repository = assistant.milvus_search_repository
    cache_service = assistant.cache_service
    context_builder = assistant.context_builder
    intent_classifier = assistant.intent_classifier
    query_contextualizer = assistant.query_contextualizer
    query_analyzer = assistant.query_analyzer
    sql_executor = assistant.sql_executor
    schema_linker = assistant.schema_linker
    sql_service = assistant.sql_service
    text_to_sql_use_case = assistant.text_to_sql_use_case
    search_documents_use_case = assistant.search_documents_use_case
    text_to_sql_tool = assistant.text_to_sql_tool
    rag_tool = assistant.rag_tool
    agent_service = assistant.agent_service
    chat_use_case = assistant.chat_use_case


container = Container()
