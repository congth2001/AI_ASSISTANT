"""Opt-in PostgreSQL regression tests using only transaction-local temp tables.

Run with AI_ANALYTICS_LOCAL_DB_TEST=1 to use configured local PostgreSQL, or
AI_ANALYTICS_TEST_DSN for a dedicated database. No public table is read/written.
"""
import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from config.config_manager import get_database_settings
from src.modules.analytics.domain.models.dashboard import DashboardFilters
from src.modules.analytics.infrastructure.repositories.dashboard_analytics_repository import DashboardAnalyticsRepository


@pytest.mark.asyncio
async def test_overview_queries_on_isolated_postgres_tables():
    dsn = os.getenv('AI_ANALYTICS_TEST_DSN')
    if not dsn and os.getenv('AI_ANALYTICS_LOCAL_DB_TEST') != '1':
        pytest.skip('Set AI_ANALYTICS_LOCAL_DB_TEST=1 or AI_ANALYTICS_TEST_DSN')
    engine = create_async_engine(dsn or get_database_settings().sqlalchemy_url, echo=False, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text('SET LOCAL search_path TO pg_temp'))
            definitions = {
                'customers': 'customer_id uuid, customer_name text, ward_name text, village_name text, created_at timestamptz, updated_at timestamptz, deleted_at timestamptz',
                'sales_invoices': 'invoice_id text, customer_id uuid, issued_at timestamp, invoice_total_amount numeric(18,2), created_at timestamp, deleted_at timestamp',
                'sales_invoice_lines': 'created_at timestamp',
                'sales_returns': 'returned_at timestamp, created_at timestamptz, updated_at timestamptz, deleted_at timestamptz',
                'sales_return_lines': 'created_at timestamptz, updated_at timestamptz',
                'customer_debt_transactions': 'customer_id uuid, occurred_at timestamp, source_type text, amount numeric(18,2), created_at timestamptz, updated_at timestamptz, deleted_at timestamptz',
            }
            for table, columns in definitions.items():
                await connection.execute(text(f'CREATE TEMP TABLE {table} ({columns}) ON COMMIT DROP'))
            ids = [f'00000000-0000-0000-0000-{i:012d}' for i in range(1, 10)]
            for index, customer_id in enumerate(ids, 1):
                await connection.execute(text("INSERT INTO customers VALUES (:id, :name, :ward, 'Thôn 1', '2025-03-06T01:00:00Z', NULL, :deleted)"), {
                    'id': customer_id, 'name': f'Khách {index}',
                    'ward': 'Xã A' if index <= 3 or index == 8 else 'Xã B',
                    'deleted': None if index != 9 else date(2025, 3, 6),
                })
            invoices = [(1, '2025-02-25', '60'), (1, '2025-02-26', '40'),
                        (1, '2025-03-01', '40'), (2, '2025-02-27', '80'),
                        (3, '2025-03-03', '200'), (4, '2025-02-28', '20'),
                        (4, '2025-03-04', '20'), (9, '2025-03-02', '9999'),
                        (1, '2025-03-05', '9999')]
            for index, (customer, occurred_at, amount) in enumerate(invoices):
                await connection.execute(text("INSERT INTO sales_invoices VALUES (:id, :customer, CAST(:day AS timestamp), :amount, '2025-03-06 02:00:00', NULL)"), {
                    'id': str(index), 'customer': ids[customer - 1], 'day': date.fromisoformat(occurred_at), 'amount': Decimal(amount),
                })
            await connection.execute(text("INSERT INTO sales_invoices VALUES ('deleted', :id, '2025-03-02', 5000, '2025-03-06', '2025-03-06')"), {'id': ids[0]})
            ledger = [(i, 'opening', str(110 - i * 10), '2025-01-01') for i in range(1, 8)]
            ledger += [(1, 'sales_return', '-10', '2025-03-01'), (2, 'sales_return', '-5', '2025-03-02'),
                       (5, 'sales_return', '-7', '2025-03-03'), (1, 'receipt', '-20', '2025-03-04'),
                       (8, 'opening', '-30', '2025-01-01')]
            for customer, kind, amount, occurred_at in ledger:
                await connection.execute(text("INSERT INTO customer_debt_transactions VALUES (:id, CAST(:day AS timestamp), :kind, :amount, '2025-03-06T03:00:00Z', NULL, NULL)"), {
                    'id': ids[customer - 1], 'day': date.fromisoformat(occurred_at), 'kind': kind, 'amount': Decimal(amount),
                })
            # A future deleted transaction must not affect latest active date.
            await connection.execute(text("INSERT INTO customer_debt_transactions VALUES (:id, '2099-01-01', 'sale', 999, '2025-03-06T03:00:00Z', NULL, '2025-03-06')"), {'id': ids[0]})
            repository = DashboardAnalyticsRepository(lambda: AsyncSession(bind=connection))
            filters = DashboardFilters(date(2025, 3, 1), date(2025, 3, 5))
            result = await repository.get_overview_insights(filters)
            assert result.declining_customer_count == 2
            assert result.inactive_customer_count == 1
            assert result.declining_revenue_change == Decimal('-155')
            assert result.declining_customers[0].customer_id == ids[1]
            assert result.declining_customers[0].current_revenue == Decimal('-5')
            assert result.declining_customers[1].current_revenue == Decimal('30')
            assert result.debtor_count == 7
            assert result.total_receivables == Decimal('448')
            assert result.top_receivables == Decimal('358')
            assert result.top_receivables_share_percent == Decimal('79.91')
            assert {w.ward_name: w.revenue_change for w in result.ward_movements} == {'Xã A': Decimal('45'), 'Xã B': Decimal('-7')}
            narrowed = await repository.get_overview_insights(DashboardFilters(
                date(2025, 3, 1), date(2025, 3, 5), customer_id=ids[0], ward_names=('Xã A',), village_names=('Thôn 1',),
            ))
            assert narrowed.declining_customer_count == 1
            assert narrowed.total_receivables == Decimal('70')
            assert narrowed.top_receivables_share_percent == Decimal('100')
            empty = await repository.get_overview_insights(DashboardFilters(
                date(2025, 3, 1), date(2025, 3, 5), ward_names=('Không tồn tại',),
            ))
            assert empty.total_receivables == 0 and empty.top_receivables_share_percent is None
            await connection.execute(text('UPDATE pg_temp.customers SET ward_name = NULL WHERE customer_id = :id'), {'id': ids[4]})
            missing_ward = await repository.get_overview_insights(filters)
            assert any(w.ward_name is None and w.revenue_change == Decimal('-7') for w in missing_ward.ward_movements)
            freshness = await repository.get_data_freshness()
            assert freshness.latest_transaction_date == date(2025, 3, 5)
            assert freshness.last_recorded_at.isoformat() == '2025-03-06T03:00:00+00:00'
            for table in definitions:
                await connection.execute(text(f'DELETE FROM pg_temp.{table}'))
            no_data = await repository.get_data_freshness()
            assert no_data.latest_transaction_date is None and no_data.last_recorded_at is None
            await transaction.rollback()
    finally:
        await engine.dispose()
