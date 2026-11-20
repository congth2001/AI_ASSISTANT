"""Dependency wiring owned by the sales module."""
from dependency_injector import containers
from dependency_injector.providers import Dependency, Singleton

from src.modules.sales.application.use_cases.sync_business_data_use_case import (
    SyncBusinessDataUseCase,
)
from src.modules.sales.infrastructure.repositories.customer_repository import CustomerRepository
from src.modules.sales.infrastructure.repositories.customer_debt_transaction_repository import (
    CustomerDebtTransactionRepository,
)
from src.modules.sales.infrastructure.repositories.debt_revision_repository import (
    DebtRevisionRepository,
)
from src.modules.sales.infrastructure.repositories.sales_invoice_repository import (
    SalesInvoiceRepository,
)
from src.modules.sales.infrastructure.repositories.sales_invoice_line_repository import (
    SalesInvoiceLineRepository,
)
from src.modules.sales.infrastructure.repositories.sales_return_repository import SalesReturnRepository
from src.modules.sales.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


class SalesContainer(containers.DeclarativeContainer):
    session_factory = Dependency()

    customer_repo = Singleton(CustomerRepository, session_factory=session_factory)

    sales_invoice_repo = Singleton(
        SalesInvoiceRepository, session_factory=session_factory
    )

    sales_invoice_line_repo = Singleton(
        SalesInvoiceLineRepository, session_factory=session_factory
    )

    customer_debt_transaction_repo = Singleton(
        CustomerDebtTransactionRepository, session_factory=session_factory
    )

    sales_return_repo = Singleton(SalesReturnRepository, session_factory=session_factory)

    debt_revision_repo = Singleton(DebtRevisionRepository, session_factory=session_factory)

    unit_of_work = Singleton(SqlAlchemyUnitOfWork, session_factory=session_factory)

    sync_business_data_use_case = Singleton(
        SyncBusinessDataUseCase,
        customer_repository=customer_repo,
        sales_invoice_repository=sales_invoice_repo,
        sales_invoice_line_repository=sales_invoice_line_repo,
        customer_debt_transaction_repository=customer_debt_transaction_repo,
        sales_return_repository=sales_return_repo,
        unit_of_work=unit_of_work,
        debt_revision_repository=debt_revision_repo,
    )
