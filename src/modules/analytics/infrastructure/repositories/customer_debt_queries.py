"""Customer overview (period activity + cumulative debt) and debt-export queries."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_, distinct, func, or_, select

from src.modules.analytics.domain.errors import CustomerDebtRowLimitError
from src.modules.analytics.domain.models.customer_debt import (
    CustomerDebtExportFilters,
    CustomerDebtExportItem,
    CustomerDebtWardSummary,
    CustomerOverviewCursor,
    CustomerOverviewItem,
    CustomerOverviewMetrics,
)
from src.modules.analytics.domain.models.dashboard import DashboardFilters
from src.modules.analytics.domain.models.export_limits import MAX_SHEET_DATA_ROWS
from src.modules.analytics.infrastructure.repositories.analytics_scope import (
    customer_scope,
    revenue_movements,
)
from src.modules.sales.infrastructure.models import Customer, CustomerDebtTransaction

UNKNOWN_WARD_LABEL = "Chưa xác định"


class CustomerDebtQueriesMixin:
    @staticmethod
    def _customer_debt_balance(filters: DashboardFilters):
        """Signed ledger balance per in-scope customer up to the exclusive period end."""
        return (
            select(
                CustomerDebtTransaction.customer_id.label("customer_id"),
                func.coalesce(func.sum(CustomerDebtTransaction.amount), 0).label("current_debt"),
            )
            .where(
                CustomerDebtTransaction.deleted_at.is_(None),
                CustomerDebtTransaction.occurred_at < filters.date_to,
                customer_scope(filters).contains(CustomerDebtTransaction.customer_id),
            )
            .group_by(CustomerDebtTransaction.customer_id)
            .subquery("customer_debt_balance")
        )

    @staticmethod
    def _customer_period_activity(filters: DashboardFilters):
        """Revenue (net of returns), sales count and last purchase per customer in the period.

        Shares ``revenue_movements`` with the customer ranking, so both screens agree,
        also under category/product filters (line grain, returns by return line).
        """
        movements = revenue_movements(
            filters, filters.date_from, filters.date_to, "customer_period_movements"
        )
        return (
            select(
                movements.c.customer_id.label("customer_id"),
                func.sum(movements.c.amount).label("revenue"),
                func.count(distinct(movements.c.invoice_id)).label("invoice_count"),
                func.max(movements.c.occurred_at)
                .filter(movements.c.invoice_id.is_not(None))
                .label("last_purchase_at"),
            )
            .group_by(movements.c.customer_id)
            .subquery("customer_period_activity")
        )

    @classmethod
    def _customer_overview_subquery(cls, filters: DashboardFilters):
        period = cls._customer_period_activity(filters)
        balance = cls._customer_debt_balance(filters)
        return (
            select(
                Customer.customer_id.label("key"),
                Customer.customer_name.label("label"),
                Customer.ward_name.label("ward_name"),
                Customer.village_name.label("village_name"),
                func.coalesce(period.c.revenue, 0).label("revenue"),
                func.coalesce(period.c.invoice_count, 0).label("invoice_count"),
                period.c.last_purchase_at.label("last_purchase_at"),
                func.coalesce(balance.c.current_debt, 0).label("current_debt"),
            )
            .select_from(Customer.__table__)
            .outerjoin(period, period.c.customer_id == Customer.customer_id)
            .outerjoin(balance, balance.c.customer_id == Customer.customer_id)
            .where(*customer_scope(filters).conditions())
            .subquery("customer_overview")
        )

    async def get_customer_overview(
        self,
        filters: DashboardFilters,
        limit: int,
        cursor: CustomerOverviewCursor | None,
        offset: int = 0,
    ) -> tuple[CustomerOverviewMetrics, list[CustomerOverviewItem], int, bool]:
        """Return period activity and debt balance as of the period end.

        Totals and the per-ward debt chart come from one ``GROUP BY ward`` pass (every
        metric is additive across wards); the page is a second statement.
        """
        overview = self._customer_overview_subquery(filters)

        ward_label = func.coalesce(overview.c.ward_name, UNKNOWN_WARD_LABEL)
        aggregate_statement = select(
            ward_label.label("ward_name"),
            func.count(overview.c.key).label("total_customers"),
            func.count(overview.c.key).filter(overview.c.invoice_count > 0).label("purchasing_customers"),
            func.count(overview.c.key).filter(overview.c.current_debt > 0).label("debtor_customers"),
            func.count(overview.c.key).filter(overview.c.current_debt <= 0).label("non_debtor_customers"),
            func.coalesce(func.sum(overview.c.revenue), 0).label("total_revenue"),
            func.coalesce(func.sum(overview.c.invoice_count), 0).label("invoice_count"),
            func.coalesce(func.sum(func.greatest(overview.c.current_debt, 0)), 0).label("receivables"),
            func.coalesce(func.sum(func.greatest(-overview.c.current_debt, 0)), 0).label("advances"),
            func.coalesce(func.sum(overview.c.current_debt), 0).label("net_balance"),
        ).group_by(ward_label)

        page_statement = select(overview)
        if cursor:
            page_statement = page_statement.where(
                or_(
                    overview.c.current_debt < cursor.current_debt,
                    and_(
                        overview.c.current_debt == cursor.current_debt,
                        overview.c.revenue < cursor.revenue,
                    ),
                    and_(
                        overview.c.current_debt == cursor.current_debt,
                        overview.c.revenue == cursor.revenue,
                        overview.c.label > cursor.label,
                    ),
                    and_(
                        overview.c.current_debt == cursor.current_debt,
                        overview.c.revenue == cursor.revenue,
                        overview.c.label == cursor.label,
                        overview.c.key > cursor.key,
                    ),
                )
            )
        page_statement = page_statement.order_by(
            overview.c.current_debt.desc(),
            overview.c.revenue.desc(),
            overview.c.label.asc(),
            overview.c.key.asc(),
        )
        if offset:
            page_statement = page_statement.offset(offset)
        page_statement = page_statement.limit(limit + 1)

        async with self._session_factory() as session:
            ward_rows = (await session.execute(aggregate_statement)).all()
            rows = (await session.execute(page_statement)).all()

        has_more = len(rows) > limit
        rows = rows[:limit]

        def total(name: str) -> int:
            return sum(int(getattr(row, name)) for row in ward_rows)

        def total_money(name: str) -> Decimal:
            return sum((Decimal(getattr(row, name)) for row in ward_rows), Decimal(0))

        metrics = CustomerOverviewMetrics(
            total_customers=total("total_customers"),
            purchasing_customers=total("purchasing_customers"),
            debtor_customers=total("debtor_customers"),
            non_debtor_customers=total("non_debtor_customers"),
            total_revenue=total_money("total_revenue"),
            invoice_count=total("invoice_count"),
            receivables=total_money("receivables"),
            advances=total_money("advances"),
            net_balance=total_money("net_balance"),
            debt_by_ward=tuple(
                CustomerDebtWardSummary(
                    ward_name=row.ward_name,
                    debtor_customers=int(row.debtor_customers),
                    receivables=Decimal(row.receivables),
                )
                for row in sorted(
                    (r for r in ward_rows if int(r.debtor_customers) > 0),
                    key=lambda r: (-Decimal(r.receivables), r.ward_name),
                )
            ),
        )
        items = [
            CustomerOverviewItem(
                key=str(row.key),
                label=row.label,
                ward_name=row.ward_name,
                village_name=row.village_name,
                revenue=Decimal(row.revenue),
                invoice_count=int(row.invoice_count),
                last_purchase_at=row.last_purchase_at,
                current_debt=Decimal(row.current_debt),
            )
            for row in rows
        ]
        return metrics, items, metrics.total_customers, has_more

    async def get_customer_debt_export(
        self, filters: CustomerDebtExportFilters
    ) -> list[CustomerDebtExportItem]:
        """Return all matching customers and signed debt for the selected period.

        Fetches at most ``MAX_SHEET_DATA_ROWS + 1`` rows so an oversized export fails
        before the whole result is loaded.
        """
        customer_predicates = [Customer.deleted_at.is_(None)]
        if filters.customer_ids:
            customer_predicates.append(Customer.customer_id.in_(filters.customer_ids))
        if filters.ward_names:
            customer_predicates.append(Customer.ward_name.in_(filters.ward_names))

        debt_predicates = [
            CustomerDebtTransaction.deleted_at.is_(None),
            # Only rows of exported customers are aggregated.
            CustomerDebtTransaction.customer_id.in_(
                select(Customer.customer_id).where(*customer_predicates).correlate(None)
            ),
        ]
        if filters.date_from:
            debt_predicates.append(CustomerDebtTransaction.occurred_at >= filters.date_from)
        if filters.date_to:
            debt_predicates.append(
                CustomerDebtTransaction.occurred_at < filters.date_to + timedelta(days=1)
            )
        debt_balance = (
            select(
                CustomerDebtTransaction.customer_id.label("customer_id"),
                func.coalesce(func.sum(CustomerDebtTransaction.amount), 0).label("current_debt"),
            )
            .where(*debt_predicates)
            .group_by(CustomerDebtTransaction.customer_id)
            .subquery("customer_debt_export_balance")
        )

        current_debt = func.coalesce(debt_balance.c.current_debt, 0)
        statement = (
            select(
                Customer.customer_id.label("key"),
                Customer.customer_name.label("label"),
                Customer.ward_name.label("ward_name"),
                Customer.village_name.label("village_name"),
                Customer.address_detail.label("address_detail"),
                current_debt.label("current_debt"),
            )
            .select_from(Customer.__table__)
            .outerjoin(debt_balance, debt_balance.c.customer_id == Customer.customer_id)
            .where(*customer_predicates)
            .order_by(current_debt.desc(), Customer.customer_name.asc(), Customer.customer_id.asc())
            .limit(MAX_SHEET_DATA_ROWS + 1)
        )
        if filters.positive_debt_only:
            statement = statement.where(current_debt > 0)

        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        if len(rows) > MAX_SHEET_DATA_ROWS:
            raise CustomerDebtRowLimitError(raw_name="All", max_rows=MAX_SHEET_DATA_ROWS)
        return [
            CustomerDebtExportItem(
                key=str(row.key),
                label=row.label,
                ward_name=row.ward_name,
                village_name=row.village_name,
                address_detail=row.address_detail,
                current_debt=Decimal(row.current_debt),
            )
            for row in rows
        ]
