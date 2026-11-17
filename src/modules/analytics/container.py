"""Dependency wiring owned by the analytics module."""
from dependency_injector import containers
from dependency_injector.providers import Dependency, Singleton

from src.modules.analytics.application.use_cases.dashboard_analytics_use_case import (
    DashboardAnalyticsUseCase,
)
from src.modules.analytics.application.use_cases.export_customer_debt_use_case import (
    ExportCustomerDebtUseCase,
)
from src.modules.analytics.application.use_cases.export_order_ledger_use_case import (
    ExportOrderLedgerUseCase,
)
from src.modules.analytics.infrastructure.repositories.dashboard_analytics_repository import (
    DashboardAnalyticsRepository,
)
from src.modules.analytics.infrastructure.exporters.customer_debt_workbook_exporter import (
    OpenpyxlCustomerDebtWorkbookExporter,
)
from src.modules.analytics.infrastructure.exporters.order_ledger_workbook_exporter import (
    OpenpyxlOrderLedgerWorkbookExporter,
)


class AnalyticsContainer(containers.DeclarativeContainer):
    session_factory = Dependency()

    dashboard_analytics_repository = Singleton(
        DashboardAnalyticsRepository,
        session_factory=session_factory,
    )

    dashboard_analytics_use_case = Singleton(
        DashboardAnalyticsUseCase,
        repository=dashboard_analytics_repository,
    )

    customer_debt_workbook_exporter = Singleton(
        OpenpyxlCustomerDebtWorkbookExporter,
    )

    export_customer_debt_use_case = Singleton(
        ExportCustomerDebtUseCase,
        repository=dashboard_analytics_repository,
        workbook_exporter=customer_debt_workbook_exporter,
    )

    order_ledger_workbook_exporter = Singleton(
        OpenpyxlOrderLedgerWorkbookExporter,
    )

    export_order_ledger_use_case = Singleton(
        ExportOrderLedgerUseCase,
        repository=dashboard_analytics_repository,
        workbook_exporter=order_ledger_workbook_exporter,
    )
