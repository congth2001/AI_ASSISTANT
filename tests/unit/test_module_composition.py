"""Exercise real module composition without connecting to external services."""
from dependency_injector import providers
from sqlalchemy.orm import configure_mappers

from config.container import Container
from src.bootstrap.orm import Base
from src.modules.auth.domain.ports.i_password_hasher import IPasswordHasher
from src.modules.auth.domain.ports.i_token_service import ITokenService


def test_module_containers_share_ports_and_preserve_provider_overrides():
    container = Container()
    container.config.auth.from_dict({
        "jwt_secret": "module-test-secret-with-at-least-thirty-two-characters",
        "jwt_issuer": "module-test", "jwt_audience": "module-test",
        "access_token_minutes": 15, "refresh_token_days": 30,
    })
    session_factory, engine, llm, cache, search = (object() for _ in range(5))
    with (
        container.session_factory.override(providers.Object(session_factory)),
        container.assistant.engine.override(providers.Object(engine)),
        container.llm_service.override(providers.Object(llm)),
        container.cache_service.override(providers.Object(cache)),
        container.milvus_search_repository.override(providers.Object(search)),
    ):
        auth = container.auth_use_case()
        assert auth.repository.session_factory is session_factory
        assert isinstance(auth.password_hasher, IPasswordHasher)
        assert isinstance(auth.token_service, ITokenService)
        assert container.auth().auth_use_case() is auth
        assert container.conversation_repo().session_factory is session_factory
        assert container.customer_repo().session_factory is session_factory
        assert container.dashboard_analytics_repository()._session_factory is session_factory
        analyzer = container.query_analyzer()
        assert analyzer._customer_repo is container.sales().customer_repo()
        assert analyzer._good_repo is container.sales().sales_invoice_line_repo()
        assert container.sql_executor()._engine is engine
        chat = container.chat_use_case()
        assert chat.conversation_repo is container.conversations().conversation_repo()
        assert chat.cache_service is cache
        assert chat.agent_service is container.assistant().agent_service()


def test_all_orm_mappings_and_foreign_keys_share_one_metadata_registry():
    configure_mappers()
    assert set(Base.metadata.tables) == {
        "users", "refresh_tokens", "conversations", "messages", "customers",
        "sales_invoices", "sales_invoice_lines", "customer_debt_transactions",
        "sales_returns", "sales_return_lines",
        "etl_sync_runs", "customer_debt_transaction_changes", "customer_debt_revisions",
    }
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.metadata is Base.metadata
    assert len(Base.metadata.sorted_tables) == 13
