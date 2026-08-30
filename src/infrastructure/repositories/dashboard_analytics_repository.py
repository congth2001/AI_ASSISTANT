"""PostgreSQL implementation of deterministic dashboard analytics."""

from datetime import datetime, timedelta
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
    CustomerDebtExportFilters,
    CustomerDebtExportItem,
    CustomerDebtWardSummary,
    OrderDetail,
    OrderFilters,
    OrderLedgerExportData,
    OrderLedgerExportFilters,
    OrderLedgerExportItem,
    OrderLine,
    OrderSummary,
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
        offset: int = 0,
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
            func.count(overview.c.key)
            .filter(overview.c.current_debt > 0)
            .label("debtor_customers"),
            func.count(overview.c.key)
            .filter(overview.c.current_debt <= 0)
            .label("non_debtor_customers"),
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
        ward_label = func.coalesce(overview.c.ward_name, "Chưa xác định")
        ward_debt_statement = (
            select(
                ward_label.label("ward_name"),
                func.count(overview.c.key).label("debtor_customers"),
                func.coalesce(func.sum(overview.c.current_debt), 0).label(
                    "receivables"
                ),
            )
            .where(overview.c.current_debt > 0)
            .group_by(ward_label)
            .order_by(func.sum(overview.c.current_debt).desc(), ward_label.asc())
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
        )
        if offset:
            page_statement = page_statement.offset(offset)
        page_statement = page_statement.limit(limit + 1)

        async with self._session_factory() as session:
            metric_row = (await session.execute(metrics_statement)).one()
            ward_rows = (await session.execute(ward_debt_statement)).all()
            rows = (await session.execute(page_statement)).all()

        has_more = len(rows) > limit
        rows = rows[:limit]

        metrics = CustomerOverviewMetrics(
            total_customers=int(metric_row.total_customers),
            purchasing_customers=int(metric_row.purchasing_customers),
            debtor_customers=int(metric_row.debtor_customers),
            non_debtor_customers=int(metric_row.non_debtor_customers),
            total_revenue=Decimal(metric_row.total_revenue),
            invoice_count=int(metric_row.invoice_count),
            receivables=Decimal(metric_row.receivables),
            advances=Decimal(metric_row.advances),
            net_balance=Decimal(metric_row.net_balance),
            debt_by_ward=tuple(
                CustomerDebtWardSummary(
                    ward_name=row.ward_name,
                    debtor_customers=int(row.debtor_customers),
                    receivables=Decimal(row.receivables),
                )
                for row in ward_rows
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
        """Return all matching customers and signed debt for the selected period."""
        debt_predicates = [CustomerDebtTransaction.deleted_at.is_(None)]
        if filters.date_from:
            debt_predicates.append(
                CustomerDebtTransaction.occurred_at >= filters.date_from
            )
        if filters.date_to:
            debt_predicates.append(
                CustomerDebtTransaction.occurred_at
                < filters.date_to + timedelta(days=1)
            )
        debt_balance = (
            select(
                CustomerDebtTransaction.customer_id.label("customer_id"),
                func.coalesce(func.sum(CustomerDebtTransaction.amount), 0).label(
                    "current_debt"
                ),
            )
            .where(*debt_predicates)
            .group_by(CustomerDebtTransaction.customer_id)
            .subquery("customer_debt_export_balance")
        )

        customer_predicates = [Customer.deleted_at.is_(None)]
        if filters.customer_ids:
            customer_predicates.append(Customer.customer_id.in_(filters.customer_ids))
        if filters.ward_names:
            customer_predicates.append(Customer.ward_name.in_(filters.ward_names))

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
            .outerjoin(
                debt_balance,
                debt_balance.c.customer_id == Customer.customer_id,
            )
            .where(*customer_predicates)
            .order_by(current_debt.desc(), Customer.customer_name.asc())
        )
        if filters.positive_debt_only:
            statement = statement.where(current_debt > 0)

        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
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

    async def list_orders(
        self, filters: OrderFilters, limit: int, offset: int
    ) -> tuple[list[OrderSummary], int]:
        """Return active sales invoices newest first."""
        line_counts = (
            select(
                SalesInvoiceLine.invoice_id.label("invoice_id"),
                func.count(SalesInvoiceLine.invoice_line_id).label("line_count"),
            )
            .where(SalesInvoiceLine.deleted_at.is_(None))
            .group_by(SalesInvoiceLine.invoice_id)
            .subquery("order_line_counts")
        )
        predicates = [SalesInvoice.deleted_at.is_(None)]
        if filters.date_from:
            predicates.append(SalesInvoice.issued_at >= filters.date_from)
        if filters.date_to:
            predicates.append(SalesInvoice.issued_at < filters.date_to)
        if filters.invoice_number:
            predicates.append(
                SalesInvoice.invoice_number.icontains(
                    filters.invoice_number, autoescape=True
                )
            )
        if filters.customer_id:
            predicates.append(SalesInvoice.customer_id == filters.customer_id)
        if filters.ward_names:
            predicates.append(
                SalesInvoice.customer_ward_name_snapshot.in_(filters.ward_names)
            )
        if filters.village_names:
            predicates.append(
                SalesInvoice.customer_village_name_snapshot.in_(
                    filters.village_names
                )
            )
        statement = (
            select(
                SalesInvoice.invoice_id,
                SalesInvoice.invoice_number,
                SalesInvoice.issued_at,
                SalesInvoice.customer_name_snapshot.label("customer_name"),
                SalesInvoice.customer_ward_name_snapshot.label("customer_ward_name"),
                SalesInvoice.customer_village_name_snapshot.label("customer_village_name"),
                SalesInvoice.invoice_total_amount,
                func.coalesce(line_counts.c.line_count, 0).label("line_count"),
            )
            .outerjoin(line_counts, line_counts.c.invoice_id == SalesInvoice.invoice_id)
            .where(*predicates)
            .order_by(
                SalesInvoice.issued_at.desc(),
                SalesInvoice.invoice_number.desc(),
                SalesInvoice.invoice_id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        count_statement = select(func.count(SalesInvoice.invoice_id)).where(
            *predicates
        )
        async with self._session_factory() as session:
            total = int((await session.execute(count_statement)).scalar_one())
            rows = (await session.execute(statement)).all()
        return [
            OrderSummary(
                invoice_id=str(row.invoice_id),
                invoice_number=row.invoice_number,
                issued_at=row.issued_at,
                customer_name=row.customer_name,
                customer_ward_name=row.customer_ward_name,
                customer_village_name=row.customer_village_name,
                invoice_total_amount=Decimal(row.invoice_total_amount),
                line_count=int(row.line_count),
            )
            for row in rows
        ], total

    async def get_order_detail(self, invoice_id: str) -> OrderDetail | None:
        invoice_statement = select(
            SalesInvoice.invoice_id,
            SalesInvoice.invoice_number,
            SalesInvoice.issued_at,
            SalesInvoice.customer_name_snapshot.label("customer_name"),
            SalesInvoice.customer_address_detail_snapshot.label(
                "customer_address_detail"
            ),
            SalesInvoice.customer_ward_name_snapshot.label("customer_ward_name"),
            SalesInvoice.customer_village_name_snapshot.label(
                "customer_village_name"
            ),
            SalesInvoice.invoice_total_amount,
        ).where(
            SalesInvoice.invoice_id == invoice_id,
            SalesInvoice.deleted_at.is_(None),
        )
        lines_statement = (
            select(
                SalesInvoiceLine.line_number,
                SalesInvoiceLine.product_name,
                SalesInvoiceLine.product_category_name,
                SalesInvoiceLine.unit_name,
                SalesInvoiceLine.unit_price,
                SalesInvoiceLine.quantity,
                SalesInvoiceLine.line_amount,
            )
            .where(
                SalesInvoiceLine.invoice_id == invoice_id,
                SalesInvoiceLine.deleted_at.is_(None),
            )
            .order_by(SalesInvoiceLine.line_number.asc())
        )
        async with self._session_factory() as session:
            invoice = (await session.execute(invoice_statement)).one_or_none()
            if invoice is None:
                return None
            rows = (await session.execute(lines_statement)).all()
        return OrderDetail(
            invoice_id=str(invoice.invoice_id),
            invoice_number=invoice.invoice_number,
            issued_at=invoice.issued_at,
            customer_name=invoice.customer_name,
            customer_address_detail=invoice.customer_address_detail,
            customer_ward_name=invoice.customer_ward_name,
            customer_village_name=invoice.customer_village_name,
            invoice_total_amount=Decimal(invoice.invoice_total_amount),
            lines=tuple(
                OrderLine(
                    line_number=int(row.line_number),
                    product_name=row.product_name,
                    product_category_name=row.product_category_name,
                    unit_name=row.unit_name,
                    unit_price=Decimal(row.unit_price),
                    quantity=Decimal(row.quantity),
                    line_amount=Decimal(row.line_amount),
                )
                for row in rows
            ),
        )

    async def get_order_ledger_export(
        self, filters: OrderLedgerExportFilters
    ) -> OrderLedgerExportData:
        """Build customer debt-ledger rows from sales, returns and receipts."""
        end_exclusive = filters.date_to + timedelta(days=1) if filters.date_to else None

        def date_predicates(column) -> list:
            predicates = []
            if filters.date_from:
                predicates.append(column >= filters.date_from)
            if end_exclusive:
                predicates.append(column < end_exclusive)
            return predicates

        def snapshot_predicates(customer_id, ward, village) -> list:
            predicates = []
            if filters.customer_id:
                predicates.append(customer_id == filters.customer_id)
            if filters.ward_names:
                predicates.append(ward.in_(filters.ward_names))
            if filters.village_names:
                predicates.append(village.in_(filters.village_names))
            return predicates

        sale_statement = (
            select(
                SalesInvoice.invoice_id,
                SalesInvoice.invoice_number.label("voucher_number"),
                SalesInvoice.issued_at.label("occurred_at"),
                SalesInvoice.customer_id,
                SalesInvoice.customer_name_snapshot.label("customer_name"),
                SalesInvoice.customer_address_detail_snapshot.label("address_detail"),
                SalesInvoice.customer_village_name_snapshot.label("village_name"),
                SalesInvoice.customer_ward_name_snapshot.label("ward_name"),
                SalesInvoice.invoice_total_amount,
                SalesInvoice.debt_delta_amount,
                SalesInvoiceLine.line_number,
                SalesInvoiceLine.product_name,
                SalesInvoiceLine.unit_name,
                SalesInvoiceLine.unit_price,
                SalesInvoiceLine.quantity,
            )
            .select_from(SalesInvoice.__table__.outerjoin(
                SalesInvoiceLine.__table__,
                and_(
                    SalesInvoiceLine.invoice_id == SalesInvoice.invoice_id,
                    SalesInvoiceLine.deleted_at.is_(None),
                ),
            ))
            .where(
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.invoice_number.ilike("XB%"),
                *date_predicates(SalesInvoice.issued_at),
                *snapshot_predicates(
                    SalesInvoice.customer_id,
                    SalesInvoice.customer_ward_name_snapshot,
                    SalesInvoice.customer_village_name_snapshot,
                ),
            )
            .order_by(
                SalesInvoice.customer_name_snapshot,
                SalesInvoice.issued_at,
                SalesInvoice.invoice_number,
                SalesInvoiceLine.line_number,
            )
        )
        return_statement = (
            select(
                SalesReturn.return_id,
                SalesReturn.return_number.label("voucher_number"),
                SalesReturn.returned_at.label("occurred_at"),
                SalesReturn.customer_id,
                SalesReturn.customer_name_snapshot.label("customer_name"),
                SalesReturn.customer_address_detail_snapshot.label("address_detail"),
                SalesReturn.customer_village_name_snapshot.label("village_name"),
                SalesReturn.customer_ward_name_snapshot.label("ward_name"),
                SalesReturn.return_total_amount,
                SalesReturnLine.line_number,
                SalesReturnLine.product_name,
                SalesReturnLine.unit_name,
                SalesReturnLine.unit_price,
                SalesReturnLine.quantity,
            )
            .select_from(SalesReturn.__table__.outerjoin(
                SalesReturnLine.__table__,
                and_(
                    SalesReturnLine.return_id == SalesReturn.return_id,
                    SalesReturnLine.deleted_at.is_(None),
                ),
            ))
            .where(
                SalesReturn.deleted_at.is_(None),
                SalesReturn.return_number.ilike("NT%"),
                *date_predicates(SalesReturn.returned_at),
                *snapshot_predicates(
                    SalesReturn.customer_id,
                    SalesReturn.customer_ward_name_snapshot,
                    SalesReturn.customer_village_name_snapshot,
                ),
            )
            .order_by(
                SalesReturn.customer_name_snapshot,
                SalesReturn.returned_at,
                SalesReturn.return_number,
                SalesReturnLine.line_number,
            )
        )
        receipt_statement = (
            select(
                CustomerDebtTransaction.source_id.label("voucher_number"),
                CustomerDebtTransaction.occurred_at,
                CustomerDebtTransaction.customer_id,
                Customer.customer_name,
                Customer.address_detail,
                Customer.village_name,
                Customer.ward_name,
                CustomerDebtTransaction.amount,
            )
            .select_from(CustomerDebtTransaction.__table__.join(
                Customer.__table__,
                Customer.customer_id == CustomerDebtTransaction.customer_id,
            ))
            .where(
                CustomerDebtTransaction.deleted_at.is_(None),
                CustomerDebtTransaction.source_type == "receipt",
                Customer.deleted_at.is_(None),
                *date_predicates(CustomerDebtTransaction.occurred_at),
                *snapshot_predicates(
                    CustomerDebtTransaction.customer_id,
                    Customer.ward_name,
                    Customer.village_name,
                ),
            )
            .order_by(
                Customer.customer_name,
                CustomerDebtTransaction.occurred_at,
                CustomerDebtTransaction.source_id,
            )
        )
        balance_predicates = [
            CustomerDebtTransaction.deleted_at.is_(None),
            Customer.deleted_at.is_(None),
        ]
        if filters.date_from:
            balance_predicates.append(
                CustomerDebtTransaction.occurred_at < filters.date_from
            )
        else:
            balance_predicates.append(
                CustomerDebtTransaction.source_type == "opening"
            )
        balance_predicates.extend(snapshot_predicates(
            CustomerDebtTransaction.customer_id,
            Customer.ward_name,
            Customer.village_name,
        ))
        opening_balance_statement = (
            select(
                CustomerDebtTransaction.customer_id,
                func.coalesce(func.sum(CustomerDebtTransaction.amount), 0).label(
                    "opening_balance"
                ),
            )
            .select_from(CustomerDebtTransaction.__table__.join(
                Customer.__table__,
                Customer.customer_id == CustomerDebtTransaction.customer_id,
            ))
            .where(*balance_predicates)
            .group_by(CustomerDebtTransaction.customer_id)
        )

        async with self._session_factory() as session:
            customer_row = None
            if filters.customer_id:
                customer_row = (
                    await session.execute(
                        select(
                            Customer.customer_id,
                            Customer.customer_name,
                            Customer.address_detail,
                            Customer.village_name,
                            Customer.ward_name,
                        ).where(
                            Customer.customer_id == filters.customer_id,
                            Customer.deleted_at.is_(None),
                        )
                    )
                ).one_or_none()
                if customer_row is None:
                    raise ValueError("Customer not found")
            opening_rows = (await session.execute(opening_balance_statement)).all()
            sale_rows = (await session.execute(sale_statement)).all()
            return_rows = (await session.execute(return_statement)).all()
            receipt_rows = (await session.execute(receipt_statement)).all()

        events: dict[str, list[dict]] = {}

        def address(row) -> str | None:
            return row.address_detail or None

        seen_sales: set[str] = set()
        for row in sale_rows:
            first_line = str(row.invoice_id) not in seen_sales
            seen_sales.add(str(row.invoice_id))
            total = Decimal(row.invoice_total_amount) if first_line else Decimal("0")
            debt_delta = Decimal(row.debt_delta_amount or 0) if first_line else Decimal("0")
            events.setdefault(str(row.customer_id), []).append({
                "customer_name": row.customer_name,
                "customer_address": address(row),
                "occurred_at": row.occurred_at,
                "voucher_number": row.voucher_number,
                "reason": "Xuất bán",
                "reason_order": 1,
                "line_number": int(row.line_number or 0),
                "product_name": row.product_name,
                "unit_name": row.unit_name,
                "unit_price": Decimal(row.unit_price or 0),
                "quantity": Decimal(row.quantity or 0),
                "payment_amount": total - debt_delta,
                "debt_amount": debt_delta,
                "movement": debt_delta,
            })

        seen_returns: set[str] = set()
        for row in return_rows:
            first_line = str(row.return_id) not in seen_returns
            seen_returns.add(str(row.return_id))
            total = Decimal(row.return_total_amount) if first_line else Decimal("0")
            events.setdefault(str(row.customer_id), []).append({
                "customer_name": row.customer_name,
                "customer_address": address(row),
                "occurred_at": row.occurred_at,
                "voucher_number": row.voucher_number,
                "reason": "Nhập trả",
                "reason_order": 2,
                "line_number": int(row.line_number or 0),
                "product_name": row.product_name,
                "unit_name": row.unit_name,
                "unit_price": Decimal(row.unit_price or 0),
                "quantity": Decimal(row.quantity or 0),
                "payment_amount": Decimal("0"),
                "debt_amount": -total,
                "movement": -total,
            })

        for row in receipt_rows:
            amount = Decimal(row.amount)
            receipt_number = str(row.voucher_number)
            month_suffix = row.occurred_at.strftime("%m%y")
            if not receipt_number.endswith(f"-{month_suffix}"):
                receipt_number = f"{receipt_number}-{month_suffix}"
            events.setdefault(str(row.customer_id), []).append({
                "customer_name": row.customer_name,
                "customer_address": address(row),
                "occurred_at": row.occurred_at,
                "voucher_number": receipt_number,
                "reason": "Thu nợ",
                "reason_order": 3,
                "line_number": 0,
                "product_name": None,
                "unit_name": None,
                "unit_price": Decimal("0"),
                "quantity": Decimal("0"),
                "payment_amount": abs(amount),
                "debt_amount": Decimal("0"),
                "movement": amount,
            })

        opening_balances = {
            str(row.customer_id): Decimal(row.opening_balance)
            for row in opening_rows
        }
        invoice_search = filters.invoice_number.casefold() if filters.invoice_number else None
        output: list[OrderLedgerExportItem] = []
        customer_ids = sorted(
            events,
            key=lambda customer_id: (
                events[customer_id][0]["customer_name"].casefold(),
                customer_id,
            ),
        )
        for customer_id in customer_ids:
            running_debt = opening_balances.get(customer_id, Decimal("0"))
            customer_events = sorted(events[customer_id], key=lambda event: (
                event["occurred_at"],
                event["reason_order"],
                event["voucher_number"],
                event["line_number"],
            ))
            for event in customer_events:
                running_debt += event["movement"]
                if invoice_search and invoice_search not in event["voucher_number"].casefold():
                    continue
                output.append(OrderLedgerExportItem(
                    customer_id=customer_id,
                    customer_name=event["customer_name"],
                    customer_address=event["customer_address"],
                    occurred_at=event["occurred_at"],
                    voucher_number=event["voucher_number"],
                    reason=event["reason"],
                    product_name=event["product_name"],
                    unit_name=event["unit_name"],
                    unit_price=event["unit_price"],
                    quantity=event["quantity"],
                    payment_amount=event["payment_amount"],
                    debt_amount=event["debt_amount"],
                    running_debt=running_debt,
                ))
        first_item = output[0] if output else None
        return OrderLedgerExportData(
            customer_id=(
                str(customer_row.customer_id)
                if customer_row
                else (first_item.customer_id if first_item else filters.customer_id or "")
            ),
            customer_name=(
                customer_row.customer_name
                if customer_row
                else (first_item.customer_name if first_item else "")
            ),
            customer_address=(
                address(customer_row)
                if customer_row
                else (first_item.customer_address if first_item else None)
            ),
            items=tuple(output),
        )

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
