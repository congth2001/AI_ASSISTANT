"""PostgreSQL implementation of deterministic dashboard analytics.

This class owns the KPI/time-series/ranking/insight/filter-option queries. The order,
order-ledger and customer-debt query groups live in their own modules and are mixed in
so the public repository interface stays unchanged. Every query takes its customer and
line scope from ``analytics_scope``.
"""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Date, Select, and_, case, cast, distinct, exists, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.analytics.domain.models.dashboard import (
    DashboardFilterOptions,
    DashboardFilters,
    DashboardMetricSnapshot,
    FilterOption,
    RankingDimension,
    RankingItem,
    TimeGrain,
    TimeSeriesPoint,
)
from src.modules.analytics.domain.models.overview import (
    CustomerRevenueMovement, DataFreshness, DebtConcentrationItem,
    OverviewInsightSnapshot, WardRevenueMovement,
)
from src.modules.analytics.domain.repositories.i_dashboard_analytics_repository import (
    IDashboardAnalyticsRepository,
)
from src.modules.analytics.infrastructure.repositories.analytics_scope import (
    customer_scope,
    has_line_filters,
    return_line_predicates,
    return_lines_from,
    revenue_movements,
    sales_line_conditions,
    sales_line_predicates,
    sales_lines_from,
)
from src.modules.analytics.infrastructure.repositories.customer_debt_queries import (
    CustomerDebtQueriesMixin,
)
from src.modules.analytics.infrastructure.repositories.order_ledger_queries import (
    OrderLedgerQueriesMixin,
)
from src.modules.analytics.infrastructure.repositories.order_queries import OrderQueriesMixin
from src.modules.sales.infrastructure.models import (
    Customer,
    CustomerDebtTransaction,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
)


def _as_date(value) -> date:
    return value.date() if isinstance(value, datetime) else value


class DashboardAnalyticsRepository(
    OrderQueriesMixin,
    OrderLedgerQueriesMixin,
    CustomerDebtQueriesMixin,
    IDashboardAnalyticsRepository,
):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def get_data_freshness(self) -> DataFreshness:
        """Expose observed record timestamps, never claim a completed ETL run."""
        transactions = union_all(*[
            select(func.max(column).label("occurred_at")).where(model.deleted_at.is_(None))
            for model, column in (
                (SalesInvoice, SalesInvoice.issued_at),
                (SalesReturn, SalesReturn.returned_at),
                (CustomerDebtTransaction, CustomerDebtTransaction.occurred_at),
            )
        ]).subquery("latest_transactions")
        recordings = union_all(*[
            select(func.max(column).label("recorded_at"))
            for column in (
                Customer.created_at, Customer.updated_at,
                SalesInvoice.created_at,
                SalesInvoiceLine.created_at,
                SalesReturn.created_at, SalesReturn.updated_at,
                SalesReturnLine.created_at, SalesReturnLine.updated_at,
                CustomerDebtTransaction.created_at, CustomerDebtTransaction.updated_at,
            )
        ]).subquery("latest_recordings")
        statement = select(
            select(cast(func.max(transactions.c.occurred_at), Date)).scalar_subquery().label("latest_date"),
            select(func.max(recordings.c.recorded_at)).scalar_subquery().label("last_recorded_at"),
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one()
        return DataFreshness(row.latest_date, row.last_recorded_at)

    @staticmethod
    def _overview_activity(filters: DashboardFilters):
        """One row/customer for both periods; include return-only customers.

        Built on the shared ``revenue_movements`` (invoice totals + ledger returns),
        aggregated per customer so money is never multiplied by joins.
        """
        start = filters.previous_period().date_from
        movements = revenue_movements(filters, start, filters.date_to, "overview_movements")
        in_current = movements.c.occurred_at >= filters.date_from
        is_sale = movements.c.invoice_id.is_not(None)
        return select(
            Customer.customer_id, Customer.customer_name,
            Customer.ward_name, Customer.village_name,
            func.sum(case((in_current, movements.c.amount), else_=0)).label("current_revenue"),
            func.sum(case((~in_current, movements.c.amount), else_=0)).label("previous_revenue"),
            func.sum(case((and_(in_current, is_sale), 1), else_=0)).label("current_invoice_count"),
            func.sum(case((and_(~in_current, is_sale), 1), else_=0)).label("previous_invoice_count"),
        ).select_from(Customer.__table__.join(
            movements, movements.c.customer_id == Customer.customer_id,
        )).where(*customer_scope(filters).conditions()).group_by(
            Customer.customer_id, Customer.customer_name, Customer.ward_name, Customer.village_name,
        ).cte("overview_customer_activity")

    async def get_overview_insights(self, filters: DashboardFilters) -> OverviewInsightSnapshot:
        activity = self._overview_activity(filters)
        delta = activity.c.current_revenue - activity.c.previous_revenue
        declines = select(
            activity, delta.label("revenue_change"),
            func.count().over().label("total_count"),
            func.sum(delta).over().label("total_change"),
            func.sum(case((activity.c.current_invoice_count == 0, 1), else_=0)).over().label("inactive_count"),
        ).where(
            activity.c.previous_revenue > 0,
            activity.c.previous_invoice_count > 0,
            delta < 0,
        ).order_by(delta, activity.c.customer_id).limit(5)

        balances = self._customer_debt_balance(filters)
        debts = select(
            Customer.customer_id, Customer.customer_name, Customer.ward_name, Customer.village_name,
            balances.c.current_debt.label("receivables"),
            func.sum(balances.c.current_debt).over().label("total_receivables"),
            func.count().over().label("debtor_count"),
        ).select_from(Customer.__table__.join(
            balances, balances.c.customer_id == Customer.customer_id,
        )).where(*customer_scope(filters).conditions(), balances.c.current_debt > 0).order_by(
            balances.c.current_debt.desc(), Customer.customer_id,
        ).limit(5)

        ward_change = func.sum(delta)
        wards = select(
            activity.c.ward_name,
            func.sum(activity.c.current_revenue).label("current_revenue"),
            func.sum(activity.c.previous_revenue).label("previous_revenue"),
            ward_change.label("revenue_change"),
        ).group_by(activity.c.ward_name).having(ward_change != 0).order_by(
            func.abs(ward_change).desc(), activity.c.ward_name.asc().nulls_last(),
        ).limit(5)

        async with self._session_factory() as session:
            decline_rows = (await session.execute(declines)).all()
            debt_rows = (await session.execute(debts)).all()
            ward_rows = (await session.execute(wards)).all()
        top_receivables = sum((Decimal(r.receivables) for r in debt_rows), Decimal(0))
        total_receivables = Decimal(debt_rows[0].total_receivables) if debt_rows else Decimal(0)
        share = (top_receivables * 100 / total_receivables).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        ) if total_receivables else None
        return OverviewInsightSnapshot(
            declining_customers=tuple(CustomerRevenueMovement(
                customer_id=str(r.customer_id), customer_name=r.customer_name,
                ward_name=r.ward_name, village_name=r.village_name,
                current_revenue=Decimal(r.current_revenue), previous_revenue=Decimal(r.previous_revenue),
                revenue_change=Decimal(r.revenue_change), current_invoice_count=int(r.current_invoice_count),
                previous_invoice_count=int(r.previous_invoice_count),
            ) for r in decline_rows),
            declining_customer_count=int(decline_rows[0].total_count) if decline_rows else 0,
            inactive_customer_count=int(decline_rows[0].inactive_count) if decline_rows else 0,
            declining_revenue_change=Decimal(decline_rows[0].total_change) if decline_rows else Decimal(0),
            debt_customers=tuple(DebtConcentrationItem(
                customer_id=str(r.customer_id), customer_name=r.customer_name,
                ward_name=r.ward_name, village_name=r.village_name, receivables=Decimal(r.receivables),
            ) for r in debt_rows),
            total_receivables=total_receivables,
            debtor_count=int(debt_rows[0].debtor_count) if debt_rows else 0,
            top_receivables=top_receivables, top_receivables_share_percent=share,
            ward_movements=tuple(WardRevenueMovement(
                ward_name=r.ward_name, current_revenue=Decimal(r.current_revenue),
                previous_revenue=Decimal(r.previous_revenue), revenue_change=Decimal(r.revenue_change),
            ) for r in ward_rows),
        )

    @staticmethod
    def _invoice_scope(filters: DashboardFilters):
        """Return the FROM clause and predicates at invoice grain.

        With category/product filters an invoice is kept when it has a matching line;
        its revenue is then measured by lines (``revenue_movements``), not its total.
        """
        predicates = [
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.issued_at >= filters.date_from,
            SalesInvoice.issued_at < filters.date_to,
            customer_scope(filters).contains(SalesInvoice.customer_id),
        ]
        if has_line_filters(filters):
            predicates.append(exists(select(1).where(
                SalesInvoiceLine.invoice_id == SalesInvoice.invoice_id,
                *sales_line_conditions(filters),
            )))
        return SalesInvoice.__table__, predicates

    @staticmethod
    def _sales_return_scope(filters: DashboardFilters):
        """Return FROM/predicates for revenue-reducing customer returns (ledger rows)."""
        return CustomerDebtTransaction.__table__, [
            CustomerDebtTransaction.deleted_at.is_(None),
            CustomerDebtTransaction.source_type == "sales_return",
            CustomerDebtTransaction.occurred_at >= filters.date_from,
            CustomerDebtTransaction.occurred_at < filters.date_to,
            customer_scope(filters).contains(CustomerDebtTransaction.customer_id),
        ]

    async def get_metric_snapshot(
        self, filters: DashboardFilters
    ) -> DashboardMetricSnapshot:
        """KPIs of one period.

        ``total_revenue`` comes from the shared ``revenue_movements`` so it equals the
        customer ranking/overview totals. ``net_debt_delta`` is the signed ledger movement
        of in-scope customers: the ledger has no product grain, so category/product
        filters do not change it.
        """
        from_clause, predicates = self._invoice_scope(filters)
        debt_delta = (
            select(func.coalesce(func.sum(CustomerDebtTransaction.amount), 0))
            .where(
                CustomerDebtTransaction.deleted_at.is_(None),
                CustomerDebtTransaction.occurred_at >= filters.date_from,
                CustomerDebtTransaction.occurred_at < filters.date_to,
                customer_scope(filters).contains(CustomerDebtTransaction.customer_id),
            )
            .scalar_subquery()
        )
        movements = revenue_movements(
            filters, filters.date_from, filters.date_to, "summary_movements"
        )
        total_revenue = select(
            func.coalesce(func.sum(movements.c.amount), 0)
        ).scalar_subquery()
        if has_line_filters(filters):
            # Same grain as total_revenue: only the matching lines of each invoice,
            # not the full total of every invoice that contains one such line.
            matching_line_sales = (
                select(func.coalesce(func.sum(SalesInvoiceLine.line_amount), 0))
                .select_from(sales_lines_from())
                .where(*sales_line_predicates(filters, filters.date_from, filters.date_to))
                .scalar_subquery()
            )
            average_invoice_value = func.coalesce(
                matching_line_sales / func.nullif(func.count(SalesInvoice.invoice_id), 0), 0
            )
        else:
            average_invoice_value = func.coalesce(func.avg(SalesInvoice.invoice_total_amount), 0)
        statement = (
            select(
                total_revenue.label("total_revenue"),
                func.count(SalesInvoice.invoice_id).label("invoice_count"),
                func.count(distinct(SalesInvoice.customer_id)).label("customer_count"),
                average_invoice_value.label("average_invoice_value"),
                debt_delta.label("net_debt_delta"),
            )
            .select_from(from_clause)
            .where(*predicates)
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one()
        return DashboardMetricSnapshot(
            total_revenue=Decimal(row.total_revenue),
            invoice_count=int(row.invoice_count),
            customer_count=int(row.customer_count),
            average_invoice_value=Decimal(row.average_invoice_value),
            net_debt_delta=Decimal(row.net_debt_delta),
        )

    async def get_time_series(
        self, filters: DashboardFilters, grain: TimeGrain
    ) -> list[TimeSeriesPoint]:
        if has_line_filters(filters):
            movements = union_all(
                select(
                    func.date_trunc(grain.value, SalesInvoice.issued_at).label("period_start"),
                    SalesInvoiceLine.line_amount.label("amount"),
                    func.concat("sale:", SalesInvoice.invoice_id).label("document_key"),
                ).select_from(sales_lines_from()).where(
                    *sales_line_predicates(filters, filters.date_from, filters.date_to)
                ),
                select(
                    func.date_trunc(grain.value, SalesReturn.returned_at).label("period_start"),
                    (-SalesReturnLine.line_amount).label("amount"),
                    func.concat("return:", SalesReturn.return_id).label("document_key"),
                ).select_from(return_lines_from()).where(
                    *return_line_predicates(filters, filters.date_from, filters.date_to)
                ),
            ).subquery("line_movements")
            statement = (
                select(
                    movements.c.period_start,
                    func.sum(movements.c.amount).label("revenue"),
                    func.count(distinct(movements.c.document_key)).label("invoice_count"),
                )
                .group_by(movements.c.period_start)
                .order_by(movements.c.period_start)
            )
            async with self._session_factory() as session:
                rows = (await session.execute(statement)).all()
            return [
                TimeSeriesPoint(
                    period_start=_as_date(row.period_start),
                    revenue=Decimal(row.revenue), invoice_count=int(row.invoice_count),
                )
                for row in rows
            ]

        from_clause, predicates = self._invoice_scope(filters)
        bucket = func.date_trunc(grain.value, SalesInvoice.issued_at).label("period_start")
        statement = (
            select(
                bucket,
                func.coalesce(func.sum(SalesInvoice.invoice_total_amount), 0).label("revenue"),
                func.count(SalesInvoice.invoice_id).label("invoice_count"),
            )
            .select_from(from_clause)
            .where(*predicates)
            .group_by(bucket)
            .order_by(bucket)
        )
        return_from, return_predicates = self._sales_return_scope(filters)
        return_bucket = func.date_trunc(
            grain.value, CustomerDebtTransaction.occurred_at
        ).label("period_start")
        return_statement = (
            select(return_bucket, func.sum(CustomerDebtTransaction.amount).label("amount"))
            .select_from(return_from)
            .where(*return_predicates)
            .group_by(return_bucket)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
            return_rows = (await session.execute(return_statement)).all()

        points: dict[date, list] = {}
        for row in rows:
            points[_as_date(row.period_start)] = [Decimal(row.revenue), int(row.invoice_count)]
        for row in return_rows:
            current = points.setdefault(_as_date(row.period_start), [Decimal("0"), 0])
            current[0] += Decimal(row.amount)
        return [
            TimeSeriesPoint(period_start=period, revenue=value[0], invoice_count=value[1])
            for period, value in sorted(points.items())
        ]

    async def get_ranking(
        self,
        filters: DashboardFilters,
        dimension: RankingDimension,
        limit: int,
        offset: int,
    ) -> tuple[list[RankingItem], int]:
        grouped = self._ranking_statement(filters, dimension)
        count_statement = select(func.count()).select_from(grouped.subquery())
        # ``key`` is the final tie-breaker so offset pagination is deterministic.
        page_statement = grouped.order_by(
            grouped.selected_columns.revenue.desc(),
            grouped.selected_columns.label.asc(),
            grouped.selected_columns.key.asc(),
        ).limit(limit).offset(offset)

        async with self._session_factory() as session:
            total = int((await session.execute(count_statement)).scalar_one())
            rows = (await session.execute(page_statement)).all()

        items = [
            RankingItem(
                key=str(row.key),
                label=row.label,
                revenue=Decimal(row.revenue),
                invoice_count=int(row.invoice_count),
                quantity=(
                    Decimal(row.quantity)
                    if hasattr(row, "quantity") and row.quantity is not None
                    else None
                ),
                unit_name=(
                    row.unit_name if hasattr(row, "unit_name") else None
                ),
            )
            for row in rows
        ]
        return items, total

    def _ranking_statement(
        self, filters: DashboardFilters, dimension: RankingDimension
    ) -> Select:
        if dimension == RankingDimension.CUSTOMER:
            # Same movements as customer-overview: includes return-only customers and
            # measures revenue by lines when a category/product filter is active.
            movements = revenue_movements(
                filters, filters.date_from, filters.date_to, "customer_ranking_movements"
            )
            return (
                select(
                    Customer.customer_id.label("key"),
                    Customer.customer_name.label("label"),
                    func.sum(movements.c.amount).label("revenue"),
                    func.count(distinct(movements.c.invoice_id)).label("invoice_count"),
                )
                .select_from(movements.join(
                    Customer.__table__, Customer.customer_id == movements.c.customer_id
                ))
                .group_by(Customer.customer_id, Customer.customer_name)
            )

        from_clause = sales_lines_from()
        predicates = sales_line_predicates(filters, filters.date_from, filters.date_to)
        return_from = return_lines_from()
        return_predicates = return_line_predicates(filters, filters.date_from, filters.date_to)

        if dimension == RankingDimension.PRODUCT:
            sales_key = func.concat_ws(
                "|", SalesInvoiceLine.product_name, SalesInvoiceLine.unit_name
            )
            return_key = func.concat_ws(
                "|", SalesReturnLine.product_name, SalesReturnLine.unit_name
            )
            movements = union_all(
                select(
                    sales_key.label("key"),
                    SalesInvoiceLine.product_name.label("label"),
                    SalesInvoiceLine.unit_name.label("unit_name"),
                    SalesInvoiceLine.line_amount.label("revenue"),
                    SalesInvoiceLine.quantity.label("quantity"),
                    func.concat("sale:", SalesInvoiceLine.invoice_id).label("document_key"),
                ).select_from(from_clause).where(*predicates),
                select(
                    return_key.label("key"),
                    SalesReturnLine.product_name.label("label"),
                    SalesReturnLine.unit_name.label("unit_name"),
                    (-SalesReturnLine.line_amount).label("revenue"),
                    (-SalesReturnLine.quantity).label("quantity"),
                    func.concat("return:", SalesReturnLine.return_id).label("document_key"),
                ).select_from(return_from).where(*return_predicates),
            ).subquery("product_movements")
            return (
                select(
                    movements.c.key,
                    movements.c.label,
                    func.sum(movements.c.revenue).label("revenue"),
                    func.count(distinct(movements.c.document_key)).label("invoice_count"),
                    func.sum(movements.c.quantity).label("quantity"),
                    movements.c.unit_name,
                )
                .select_from(movements)
                .group_by(movements.c.key, movements.c.label, movements.c.unit_name)
            )

        movements = union_all(
            select(
                SalesInvoiceLine.product_category_name.label("key"),
                SalesInvoiceLine.product_category_name.label("label"),
                SalesInvoiceLine.line_amount.label("revenue"),
                func.concat("sale:", SalesInvoiceLine.invoice_id).label("document_key"),
            ).select_from(from_clause).where(*predicates, SalesInvoiceLine.product_category_name.is_not(None)),
            select(
                SalesReturnLine.product_category_name.label("key"),
                SalesReturnLine.product_category_name.label("label"),
                (-SalesReturnLine.line_amount).label("revenue"),
                func.concat("return:", SalesReturnLine.return_id).label("document_key"),
            ).select_from(return_from).where(*return_predicates, SalesReturnLine.product_category_name.is_not(None)),
        ).subquery("category_movements")
        return (
            select(
                movements.c.key,
                movements.c.label,
                func.sum(movements.c.revenue).label("revenue"),
                func.count(distinct(movements.c.document_key)).label("invoice_count"),
            )
            .select_from(movements)
            .group_by(movements.c.key, movements.c.label)
        )

    async def get_filter_options(
        self,
        search: str | None,
        limit: int,
        ward_names: tuple[str, ...] = (),
        village_names: tuple[str, ...] = (),
    ) -> DashboardFilterOptions:
        customer_statement = select(
            Customer.customer_id, Customer.customer_name
        ).where(Customer.deleted_at.is_(None))
        if ward_names:
            customer_statement = customer_statement.where(Customer.ward_name.in_(ward_names))
        if village_names:
            customer_statement = customer_statement.where(Customer.village_name.in_(village_names))
        if search:
            customer_statement = customer_statement.where(
                Customer.customer_name.icontains(search, autoescape=True)
            )
        customer_statement = customer_statement.order_by(
            Customer.customer_name, Customer.customer_id
        ).limit(limit)

        async with self._session_factory() as session:
            customer_rows = (await session.execute(customer_statement)).all()
            wards = await self._distinct_values(
                session, Customer.ward_name, Customer.deleted_at, search, limit
            )
            villages = await self._distinct_values(
                session,
                Customer.village_name,
                Customer.deleted_at,
                search,
                limit,
                extra_predicates=(
                    (Customer.ward_name.in_(ward_names),) if ward_names else ()
                ),
            )
            categories = await self._distinct_line_values(
                session, SalesInvoiceLine.product_category_name, search, limit,
            )
            products = await self._distinct_line_values(
                session, SalesInvoiceLine.product_name, search, limit,
            )

        return DashboardFilterOptions(
            customers=tuple(
                FilterOption(value=str(row.customer_id), label=row.customer_name)
                for row in customer_rows
            ),
            wards=tuple(wards),
            villages=tuple(villages),
            categories=tuple(categories),
            products=tuple(products),
        )

    @staticmethod
    async def _distinct_values(
        session: AsyncSession,
        value_column,
        deleted_column,
        search: str | None,
        limit: int,
        extra_predicates: tuple = (),
    ) -> list[str]:
        statement = select(distinct(value_column).label("value")).where(
            deleted_column.is_(None), value_column.is_not(None), *extra_predicates
        )
        if search:
            # autoescape: '%' and '_' typed by the user are literals, not wildcards.
            statement = statement.where(value_column.icontains(search, autoescape=True))
        statement = statement.order_by(value_column).limit(limit)
        return list((await session.execute(statement)).scalars().all())

    @staticmethod
    async def _distinct_line_values(
        session: AsyncSession,
        value_column,
        search: str | None,
        limit: int,
    ) -> list[str]:
        sales_statement = (
            select(distinct(value_column).label("value"))
            .select_from(sales_lines_from())
            .where(
                SalesInvoiceLine.deleted_at.is_(None),
                SalesInvoice.deleted_at.is_(None),
                value_column.is_not(None),
            )
        )
        return_column = getattr(SalesReturnLine, value_column.key)
        return_statement = (
            select(distinct(return_column).label("value"))
            .select_from(return_lines_from())
            .where(
                SalesReturnLine.deleted_at.is_(None),
                SalesReturn.deleted_at.is_(None),
                return_column.is_not(None),
            )
        )
        if search:
            sales_statement = sales_statement.where(value_column.icontains(search, autoescape=True))
            return_statement = return_statement.where(return_column.icontains(search, autoescape=True))
        values = union_all(sales_statement, return_statement).subquery("line_filter_values")
        statement = select(distinct(values.c.value)).order_by(values.c.value).limit(limit)
        return list((await session.execute(statement)).scalars().all())
