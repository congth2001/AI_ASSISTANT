"""PostgreSQL implementation of deterministic dashboard analytics."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, and_, distinct, exists, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.entities.dashboard_analytics import (
    DashboardFilterOptions,
    DashboardFilters,
    DashboardMetricSnapshot,
    CustomerOverviewItem,
    CustomerOverviewCursor,
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
    CustomerDebtTransaction,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
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

    @staticmethod
    def _sales_return_scope(filters: DashboardFilters):
        """Return FROM/predicates for revenue-reducing customer returns."""
        needs_customer = bool(
            filters.customer_id or filters.ward_names or filters.village_names
        )
        from_clause = CustomerDebtTransaction.__table__
        predicates = [
            CustomerDebtTransaction.deleted_at.is_(None),
            CustomerDebtTransaction.source_type == "sales_return",
            CustomerDebtTransaction.occurred_at >= filters.date_from,
            CustomerDebtTransaction.occurred_at < filters.date_to,
        ]
        if needs_customer:
            from_clause = from_clause.join(
                Customer.__table__,
                Customer.customer_id == CustomerDebtTransaction.customer_id,
            )
            predicates.append(Customer.deleted_at.is_(None))
            if filters.customer_id:
                predicates.append(Customer.customer_id == filters.customer_id)
            if filters.ward_names:
                predicates.append(Customer.ward_name.in_(filters.ward_names))
            if filters.village_names:
                predicates.append(Customer.village_name.in_(filters.village_names))
        return from_clause, predicates

    async def get_metric_snapshot(
        self, filters: DashboardFilters
    ) -> DashboardMetricSnapshot:
        from_clause, predicates = self._invoice_scope(filters)
        debt_from = CustomerDebtTransaction.__table__
        debt_predicates = [
            CustomerDebtTransaction.deleted_at.is_(None),
            CustomerDebtTransaction.occurred_at >= filters.date_from,
            CustomerDebtTransaction.occurred_at < filters.date_to,
        ]
        if filters.customer_id or filters.ward_names or filters.village_names:
            debt_from = debt_from.join(
                Customer.__table__,
                Customer.customer_id == CustomerDebtTransaction.customer_id,
            )
            debt_predicates.append(Customer.deleted_at.is_(None))
            if filters.customer_id:
                debt_predicates.append(Customer.customer_id == filters.customer_id)
            if filters.ward_names:
                debt_predicates.append(Customer.ward_name.in_(filters.ward_names))
            if filters.village_names:
                debt_predicates.append(Customer.village_name.in_(filters.village_names))
        debt_delta = (
            select(func.coalesce(func.sum(CustomerDebtTransaction.amount), 0))
            .select_from(debt_from)
            .where(*debt_predicates)
            .scalar_subquery()
        )
        return_from, return_predicates = self._sales_return_scope(filters)
        return_amount = (
            select(func.coalesce(func.sum(CustomerDebtTransaction.amount), 0))
            .select_from(return_from)
            .where(*return_predicates)
            .scalar_subquery()
        )
        gross_revenue = func.coalesce(func.sum(SalesInvoice.invoice_total_amount), 0)
        total_revenue = gross_revenue + return_amount
        if filters.category_names or filters.product_names:
            line_from = SalesInvoiceLine.__table__.join(
                SalesInvoice.__table__, SalesInvoice.invoice_id == SalesInvoiceLine.invoice_id
            )
            if filters.customer_id or filters.ward_names or filters.village_names:
                line_from = line_from.join(Customer.__table__, Customer.customer_id == SalesInvoice.customer_id)
            sales_line_total = (
                select(func.coalesce(func.sum(SalesInvoiceLine.line_amount), 0))
                .select_from(line_from)
                .where(*self._line_predicates(filters))
                .scalar_subquery()
            )
            return_line_from = SalesReturnLine.__table__.join(
                SalesReturn.__table__, SalesReturn.return_id == SalesReturnLine.return_id
            )
            return_line_predicates = [
                SalesReturnLine.deleted_at.is_(None), SalesReturn.deleted_at.is_(None),
                SalesReturn.returned_at >= filters.date_from, SalesReturn.returned_at < filters.date_to,
            ]
            if filters.category_names:
                return_line_predicates.append(SalesReturnLine.product_category_name.in_(filters.category_names))
            if filters.product_names:
                return_line_predicates.append(SalesReturnLine.product_name.in_(filters.product_names))
            if filters.customer_id or filters.ward_names or filters.village_names:
                return_line_from = return_line_from.join(Customer.__table__, Customer.customer_id == SalesReturn.customer_id)
                return_line_predicates.append(Customer.deleted_at.is_(None))
                if filters.customer_id:
                    return_line_predicates.append(Customer.customer_id == filters.customer_id)
                if filters.ward_names:
                    return_line_predicates.append(Customer.ward_name.in_(filters.ward_names))
                if filters.village_names:
                    return_line_predicates.append(Customer.village_name.in_(filters.village_names))
            returned_line_total = (
                select(func.coalesce(func.sum(SalesReturnLine.line_amount), 0))
                .select_from(return_line_from).where(*return_line_predicates).scalar_subquery()
            )
            total_revenue = sales_line_total - returned_line_total
        statement = (
            select(
                total_revenue.label("total_revenue"),
                func.count(SalesInvoice.invoice_id).label("invoice_count"),
                func.count(distinct(SalesInvoice.customer_id)).label("customer_count"),
                func.coalesce(func.avg(SalesInvoice.invoice_total_amount), 0).label(
                    "average_invoice_value"
                ),
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

    @staticmethod
    def _customer_return_activity(filters: DashboardFilters):
        return (
            select(
                CustomerDebtTransaction.customer_id.label("customer_id"),
                func.coalesce(func.sum(CustomerDebtTransaction.amount), 0).label(
                    "return_amount"
                ),
            )
            .where(
                CustomerDebtTransaction.deleted_at.is_(None),
                CustomerDebtTransaction.source_type == "sales_return",
                CustomerDebtTransaction.occurred_at >= filters.date_from,
                CustomerDebtTransaction.occurred_at < filters.date_to,
            )
            .group_by(CustomerDebtTransaction.customer_id)
            .subquery("customer_return_activity")
        )

    @staticmethod
    def _customer_debt_balance(filters: DashboardFilters):
        return (
            select(
                CustomerDebtTransaction.customer_id.label("customer_id"),
                func.coalesce(
                    func.sum(CustomerDebtTransaction.amount), 0
                ).label("current_debt"),
            )
            .where(
                CustomerDebtTransaction.deleted_at.is_(None),
                CustomerDebtTransaction.occurred_at < filters.date_to,
            )
            .group_by(CustomerDebtTransaction.customer_id)
            .subquery("customer_debt_balance")
        )

    async def get_customer_overview(
        self,
        filters: DashboardFilters,
        limit: int,
        cursor: CustomerOverviewCursor | None,
    ) -> tuple[CustomerOverviewMetrics, list[CustomerOverviewItem], int, bool]:
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
        return_activity = self._customer_return_activity(filters)
        debt_balance = self._customer_debt_balance(filters)

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
                (
                    func.coalesce(period_activity.c.revenue, 0)
                    + func.coalesce(return_activity.c.return_amount, 0)
                ).label("revenue"),
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
            .outerjoin(
                return_activity,
                return_activity.c.customer_id == Customer.customer_id,
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
        ).limit(limit + 1)

        async with self._session_factory() as session:
            metric_row = (await session.execute(metrics_statement)).one()
            rows = (await session.execute(page_statement)).all()

        has_more = len(rows) > limit
        rows = rows[:limit]

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
        return metrics, items, metrics.total_customers, has_more

    async def get_time_series(
        self, filters: DashboardFilters, grain: TimeGrain
    ) -> list[TimeSeriesPoint]:
        if filters.category_names or filters.product_names:
            sales_from = SalesInvoiceLine.__table__.join(
                SalesInvoice.__table__, SalesInvoice.invoice_id == SalesInvoiceLine.invoice_id
            )
            returns_from = SalesReturnLine.__table__.join(
                SalesReturn.__table__, SalesReturn.return_id == SalesReturnLine.return_id
            )
            sales_predicates = self._line_predicates(filters)
            return_predicates = [
                SalesReturnLine.deleted_at.is_(None), SalesReturn.deleted_at.is_(None),
                SalesReturn.returned_at >= filters.date_from, SalesReturn.returned_at < filters.date_to,
            ]
            if filters.customer_id or filters.ward_names or filters.village_names:
                sales_from = sales_from.join(Customer.__table__, Customer.customer_id == SalesInvoice.customer_id)
                returns_from = returns_from.join(Customer.__table__, Customer.customer_id == SalesReturn.customer_id)
                return_predicates.append(Customer.deleted_at.is_(None))
                if filters.customer_id:
                    return_predicates.append(Customer.customer_id == filters.customer_id)
                if filters.ward_names:
                    return_predicates.append(Customer.ward_name.in_(filters.ward_names))
                if filters.village_names:
                    return_predicates.append(Customer.village_name.in_(filters.village_names))
            if filters.category_names:
                return_predicates.append(SalesReturnLine.product_category_name.in_(filters.category_names))
            if filters.product_names:
                return_predicates.append(SalesReturnLine.product_name.in_(filters.product_names))
            movements = union_all(
                select(
                    func.date_trunc(grain.value, SalesInvoice.issued_at).label("period_start"),
                    SalesInvoiceLine.line_amount.label("amount"),
                    func.concat("sale:", SalesInvoice.invoice_id).label("document_key"),
                ).select_from(sales_from).where(*sales_predicates),
                select(
                    func.date_trunc(grain.value, SalesReturn.returned_at).label("period_start"),
                    (-SalesReturnLine.line_amount).label("amount"),
                    func.concat("return:", SalesReturn.return_id).label("document_key"),
                ).select_from(returns_from).where(*return_predicates),
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
                    period_start=row.period_start.date() if isinstance(row.period_start, datetime) else row.period_start,
                    revenue=Decimal(row.revenue), invoice_count=int(row.invoice_count),
                )
                for row in rows
            ]

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
            return_rows = []
            if not (filters.category_names or filters.product_names):
                return_from, return_predicates = self._sales_return_scope(filters)
                return_bucket = func.date_trunc(
                    grain.value, CustomerDebtTransaction.occurred_at
                ).label("period_start")
                return_statement = (
                    select(
                        return_bucket,
                        func.sum(CustomerDebtTransaction.amount).label("amount"),
                    )
                    .select_from(return_from)
                    .where(*return_predicates)
                    .group_by(return_bucket)
                )
                return_rows = (await session.execute(return_statement)).all()

        points = {}
        for row in rows:
            period_start = (
                row.period_start.date()
                if isinstance(row.period_start, datetime)
                else row.period_start
            )
            points[period_start] = [Decimal(row.revenue), int(row.invoice_count)]
        for row in return_rows:
            period_start = (
                row.period_start.date()
                if isinstance(row.period_start, datetime)
                else row.period_start
            )
            current = points.setdefault(period_start, [Decimal("0"), 0])
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
            revenue = func.sum(SalesInvoice.invoice_total_amount)
            if not (filters.category_names or filters.product_names):
                customer_returns = (
                    select(func.coalesce(func.sum(CustomerDebtTransaction.amount), 0))
                    .where(
                        CustomerDebtTransaction.deleted_at.is_(None),
                        CustomerDebtTransaction.source_type == "sales_return",
                        CustomerDebtTransaction.customer_id == Customer.customer_id,
                        CustomerDebtTransaction.occurred_at >= filters.date_from,
                        CustomerDebtTransaction.occurred_at < filters.date_to,
                    )
                    .correlate(Customer)
                    .scalar_subquery()
                )
                revenue = revenue + customer_returns
            return (
                select(
                    Customer.customer_id.label("key"),
                    Customer.customer_name.label("label"),
                    revenue.label("revenue"),
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

        return_from = SalesReturnLine.__table__.join(
            SalesReturn.__table__, SalesReturn.return_id == SalesReturnLine.return_id
        )
        if filters.customer_id or filters.ward_names or filters.village_names:
            return_from = return_from.join(
                Customer.__table__, Customer.customer_id == SalesReturn.customer_id
            )
        return_predicates = [
            SalesReturnLine.deleted_at.is_(None),
            SalesReturn.deleted_at.is_(None),
            SalesReturn.returned_at >= filters.date_from,
            SalesReturn.returned_at < filters.date_to,
        ]
        if filters.customer_id:
            return_predicates.append(SalesReturn.customer_id == filters.customer_id)
        if filters.ward_names:
            return_predicates.append(Customer.ward_name.in_(filters.ward_names))
        if filters.village_names:
            return_predicates.append(Customer.village_name.in_(filters.village_names))
        if filters.category_names:
            return_predicates.append(SalesReturnLine.product_category_name.in_(filters.category_names))
        if filters.product_names:
            return_predicates.append(SalesReturnLine.product_name.in_(filters.product_names))
        if filters.customer_id or filters.ward_names or filters.village_names:
            return_predicates.append(Customer.deleted_at.is_(None))

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
        sales_statement = (
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
        return_column = getattr(SalesReturnLine, value_column.key)
        return_statement = (
            select(distinct(return_column).label("value"))
            .select_from(
                SalesReturnLine.__table__.join(
                    SalesReturn.__table__,
                    SalesReturn.return_id == SalesReturnLine.return_id,
                )
            )
            .where(
                SalesReturnLine.deleted_at.is_(None),
                SalesReturn.deleted_at.is_(None),
                return_column.is_not(None),
            )
        )
        if search:
            sales_statement = sales_statement.where(value_column.ilike(f"%{search}%"))
            return_statement = return_statement.where(return_column.ilike(f"%{search}%"))
        values = union_all(sales_statement, return_statement).subquery("line_filter_values")
        statement = select(distinct(values.c.value)).order_by(values.c.value).limit(limit)
        return list((await session.execute(statement)).scalars().all())
