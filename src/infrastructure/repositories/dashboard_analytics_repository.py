"""PostgreSQL implementation of deterministic dashboard analytics."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, distinct, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.entities.dashboard_analytics import (
    DashboardFilterOptions,
    DashboardFilters,
    DashboardMetricSnapshot,
    CustomerOverviewItem,
    CustomerOverviewMetrics,
    FilterOption,
    RankingDimension,
    RankingItem,
    TimeGrain,
    TimeSeriesPoint,
)
from src.domain.repositories.i_dashboard_analytics_repository import (
    IDashboardAnalyticsRepository,
)
from src.infrastructure.repositories.models import (
    Customer,
    SalesInvoice,
    SalesInvoiceLine,
)


class DashboardAnalyticsRepository(IDashboardAnalyticsRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    @staticmethod
    def _invoice_scope(filters: DashboardFilters):
        """Return the FROM clause and predicates at invoice grain."""
        needs_customer = bool(
            filters.customer_id or filters.ward_names or filters.village_names
        )
        from_clause = SalesInvoice.__table__
        predicates = [
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.issued_at >= filters.date_from,
            SalesInvoice.issued_at < filters.date_to,
        ]

        if needs_customer:
            from_clause = SalesInvoice.__table__.join(
                Customer.__table__,
                Customer.customer_id == SalesInvoice.customer_id,
            )
            predicates.append(Customer.deleted_at.is_(None))
            if filters.customer_id:
                predicates.append(Customer.customer_id == filters.customer_id)
            if filters.ward_names:
                predicates.append(Customer.ward_name.in_(filters.ward_names))
            if filters.village_names:
                predicates.append(Customer.village_name.in_(filters.village_names))

        if filters.category_names or filters.product_names:
            line_predicates = [
                SalesInvoiceLine.invoice_id == SalesInvoice.invoice_id,
                SalesInvoiceLine.deleted_at.is_(None),
            ]
            if filters.category_names:
                line_predicates.append(
                    SalesInvoiceLine.product_category_name.in_(
                        filters.category_names
                    )
                )
            if filters.product_names:
                line_predicates.append(
                    SalesInvoiceLine.product_name.in_(filters.product_names)
                )
            predicates.append(exists(select(1).where(*line_predicates)))

        return from_clause, predicates

    @staticmethod
    def _line_predicates(filters: DashboardFilters) -> list:
        predicates = [
            SalesInvoiceLine.deleted_at.is_(None),
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.issued_at >= filters.date_from,
            SalesInvoice.issued_at < filters.date_to,
        ]
        if filters.customer_id:
            predicates.append(SalesInvoice.customer_id == filters.customer_id)
        if filters.ward_names:
            predicates.append(Customer.ward_name.in_(filters.ward_names))
        if filters.village_names:
            predicates.append(Customer.village_name.in_(filters.village_names))
        if filters.category_names:
            predicates.append(
                SalesInvoiceLine.product_category_name.in_(filters.category_names)
            )
        if filters.product_names:
            predicates.append(SalesInvoiceLine.product_name.in_(filters.product_names))
        if filters.customer_id or filters.ward_names or filters.village_names:
            predicates.append(Customer.deleted_at.is_(None))
        return predicates

    async def get_metric_snapshot(
        self, filters: DashboardFilters
    ) -> DashboardMetricSnapshot:
        from_clause, predicates = self._invoice_scope(filters)
        statement = (
            select(
                func.coalesce(func.sum(SalesInvoice.invoice_total_amount), 0).label(
                    "total_revenue"
                ),
                func.count(SalesInvoice.invoice_id).label("invoice_count"),
                func.count(distinct(SalesInvoice.customer_id)).label("customer_count"),
                func.coalesce(func.avg(SalesInvoice.invoice_total_amount), 0).label(
                    "average_invoice_value"
                ),
                func.coalesce(func.sum(SalesInvoice.debt_delta_amount), 0).label(
                    "net_debt_delta"
                ),
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

    async def get_customer_overview(
        self,
        filters: DashboardFilters,
        limit: int,
        offset: int,
    ) -> tuple[CustomerOverviewMetrics, list[CustomerOverviewItem], int]:
        """Return period activity and debt balance as of the period end."""
        period_predicates = [
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.issued_at >= filters.date_from,
            SalesInvoice.issued_at < filters.date_to,
        ]
        if filters.category_names or filters.product_names:
            line_predicates = [
                SalesInvoiceLine.invoice_id == SalesInvoice.invoice_id,
                SalesInvoiceLine.deleted_at.is_(None),
            ]
            if filters.category_names:
                line_predicates.append(
                    SalesInvoiceLine.product_category_name.in_(
                        filters.category_names
                    )
                )
            if filters.product_names:
                line_predicates.append(
                    SalesInvoiceLine.product_name.in_(filters.product_names)
                )
            period_predicates.append(exists(select(1).where(*line_predicates)))

        period_activity = (
            select(
                SalesInvoice.customer_id.label("customer_id"),
                func.sum(SalesInvoice.invoice_total_amount).label("revenue"),
                func.count(SalesInvoice.invoice_id).label("invoice_count"),
                func.max(SalesInvoice.issued_at).label("last_purchase_at"),
            )
            .where(*period_predicates)
            .group_by(SalesInvoice.customer_id)
            .subquery("customer_period_activity")
        )
        debt_balance = (
            select(
                SalesInvoice.customer_id.label("customer_id"),
                func.coalesce(func.sum(SalesInvoice.debt_delta_amount), 0).label(
                    "current_debt"
                ),
            )
            .where(
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.issued_at < filters.date_to,
            )
            .group_by(SalesInvoice.customer_id)
            .subquery("customer_debt_balance")
        )

        customer_predicates = [Customer.deleted_at.is_(None)]
        if filters.customer_id:
            customer_predicates.append(Customer.customer_id == filters.customer_id)
        if filters.ward_names:
            customer_predicates.append(Customer.ward_name.in_(filters.ward_names))
        if filters.village_names:
            customer_predicates.append(
                Customer.village_name.in_(filters.village_names)
            )

        overview = (
            select(
                Customer.customer_id.label("key"),
                Customer.customer_name.label("label"),
                Customer.ward_name.label("ward_name"),
                Customer.village_name.label("village_name"),
                func.coalesce(period_activity.c.revenue, 0).label("revenue"),
                func.coalesce(period_activity.c.invoice_count, 0).label(
                    "invoice_count"
                ),
                period_activity.c.last_purchase_at.label("last_purchase_at"),
                func.coalesce(debt_balance.c.current_debt, 0).label(
                    "current_debt"
                ),
            )
            .select_from(Customer.__table__)
            .outerjoin(
                period_activity,
                period_activity.c.customer_id == Customer.customer_id,
            )
            .outerjoin(
                debt_balance,
                debt_balance.c.customer_id == Customer.customer_id,
            )
            .where(*customer_predicates)
            .subquery("customer_overview")
        )

        metrics_statement = select(
            func.count(overview.c.key).label("total_customers"),
            func.count(overview.c.key)
            .filter(overview.c.invoice_count > 0)
            .label("purchasing_customers"),
            func.coalesce(func.sum(overview.c.revenue), 0).label("total_revenue"),
            func.coalesce(func.sum(overview.c.invoice_count), 0).label(
                "invoice_count"
            ),
            func.coalesce(
                func.sum(func.greatest(overview.c.current_debt, 0)), 0
            ).label("receivables"),
            func.coalesce(
                func.sum(func.greatest(-overview.c.current_debt, 0)), 0
            ).label("advances"),
            func.coalesce(func.sum(overview.c.current_debt), 0).label(
                "net_balance"
            ),
        )
        page_statement = (
            select(overview)
            .order_by(
                overview.c.current_debt.desc(),
                overview.c.revenue.desc(),
                overview.c.label.asc(),
            )
            .limit(limit)
            .offset(offset)
        )

        async with self._session_factory() as session:
            metric_row = (await session.execute(metrics_statement)).one()
            rows = (await session.execute(page_statement)).all()

        metrics = CustomerOverviewMetrics(
            total_customers=int(metric_row.total_customers),
            purchasing_customers=int(metric_row.purchasing_customers),
            total_revenue=Decimal(metric_row.total_revenue),
            invoice_count=int(metric_row.invoice_count),
            receivables=Decimal(metric_row.receivables),
            advances=Decimal(metric_row.advances),
            net_balance=Decimal(metric_row.net_balance),
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
        return metrics, items, metrics.total_customers

    async def get_time_series(
        self, filters: DashboardFilters, grain: TimeGrain
    ) -> list[TimeSeriesPoint]:
        from_clause, predicates = self._invoice_scope(filters)
        bucket = func.date_trunc(grain.value, SalesInvoice.issued_at).label(
            "period_start"
        )
        statement = (
            select(
                bucket,
                func.coalesce(func.sum(SalesInvoice.invoice_total_amount), 0).label(
                    "revenue"
                ),
                func.count(SalesInvoice.invoice_id).label("invoice_count"),
            )
            .select_from(from_clause)
            .where(*predicates)
            .group_by(bucket)
            .order_by(bucket)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [
            TimeSeriesPoint(
                period_start=(
                    row.period_start.date()
                    if isinstance(row.period_start, datetime)
                    else row.period_start
                ),
                revenue=Decimal(row.revenue),
                invoice_count=int(row.invoice_count),
            )
            for row in rows
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
        page_statement = grouped.order_by(
            grouped.selected_columns.revenue.desc(),
            grouped.selected_columns.label.asc(),
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
            from_clause = SalesInvoice.__table__.join(
                Customer.__table__,
                Customer.customer_id == SalesInvoice.customer_id,
            )
            _, predicates = self._invoice_scope(filters)
            predicates.append(Customer.deleted_at.is_(None))
            if filters.customer_id:
                predicates.append(Customer.customer_id == filters.customer_id)
            if filters.ward_names:
                predicates.append(Customer.ward_name.in_(filters.ward_names))
            if filters.village_names:
                predicates.append(Customer.village_name.in_(filters.village_names))
            return (
                select(
                    Customer.customer_id.label("key"),
                    Customer.customer_name.label("label"),
                    func.sum(SalesInvoice.invoice_total_amount).label("revenue"),
                    func.count(SalesInvoice.invoice_id).label("invoice_count"),
                )
                .select_from(from_clause)
                .where(*predicates)
                .group_by(Customer.customer_id, Customer.customer_name)
            )

        from_clause = SalesInvoiceLine.__table__.join(
            SalesInvoice.__table__,
            SalesInvoice.invoice_id == SalesInvoiceLine.invoice_id,
        )
        if filters.customer_id or filters.ward_names or filters.village_names:
            from_clause = from_clause.join(
                Customer.__table__,
                Customer.customer_id == SalesInvoice.customer_id,
            )
        predicates = self._line_predicates(filters)

        if dimension == RankingDimension.PRODUCT:
            key = func.concat_ws(
                "|", SalesInvoiceLine.product_name, SalesInvoiceLine.unit_name
            )
            return (
                select(
                    key.label("key"),
                    SalesInvoiceLine.product_name.label("label"),
                    func.sum(SalesInvoiceLine.line_amount).label("revenue"),
                    func.count(distinct(SalesInvoiceLine.invoice_id)).label(
                        "invoice_count"
                    ),
                    func.sum(SalesInvoiceLine.quantity).label("quantity"),
                    SalesInvoiceLine.unit_name.label("unit_name"),
                )
                .select_from(from_clause)
                .where(*predicates)
                .group_by(SalesInvoiceLine.product_name, SalesInvoiceLine.unit_name)
            )

        return (
            select(
                SalesInvoiceLine.product_category_name.label("key"),
                SalesInvoiceLine.product_category_name.label("label"),
                func.sum(SalesInvoiceLine.line_amount).label("revenue"),
                func.count(distinct(SalesInvoiceLine.invoice_id)).label(
                    "invoice_count"
                ),
            )
            .select_from(from_clause)
            .where(
                *predicates,
                SalesInvoiceLine.product_category_name.is_not(None),
            )
            .group_by(SalesInvoiceLine.product_category_name)
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
            customer_statement = customer_statement.where(
                Customer.ward_name.in_(ward_names)
            )
        if village_names:
            customer_statement = customer_statement.where(
                Customer.village_name.in_(village_names)
            )
        if search:
            customer_statement = customer_statement.where(
                Customer.customer_name.ilike(f"%{search}%")
            )
        customer_statement = customer_statement.order_by(
            Customer.customer_name
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
                session,
                SalesInvoiceLine.product_category_name,
                search,
                limit,
            )
            products = await self._distinct_line_values(
                session,
                SalesInvoiceLine.product_name,
                search,
                limit,
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
            statement = statement.where(value_column.ilike(f"%{search}%"))
        statement = statement.order_by(value_column).limit(limit)
        return list((await session.execute(statement)).scalars().all())

    @staticmethod
    async def _distinct_line_values(
        session: AsyncSession,
        value_column,
        search: str | None,
        limit: int,
    ) -> list[str]:
        statement = (
            select(distinct(value_column).label("value"))
            .select_from(
                SalesInvoiceLine.__table__.join(
                    SalesInvoice.__table__,
                    SalesInvoice.invoice_id == SalesInvoiceLine.invoice_id,
                )
            )
            .where(
                SalesInvoiceLine.deleted_at.is_(None),
                SalesInvoice.deleted_at.is_(None),
                value_column.is_not(None),
            )
        )
        if search:
            statement = statement.where(value_column.ilike(f"%{search}%"))
        statement = statement.order_by(value_column).limit(limit)
        return list((await session.execute(statement)).scalars().all())
