"""Invoice list and invoice detail queries."""

from decimal import Decimal

from sqlalchemy import func, select

from src.modules.analytics.domain.models.orders import (
    OrderDetail,
    OrderFilters,
    OrderLine,
    OrderSummary,
)
from src.modules.analytics.infrastructure.repositories.analytics_scope import customer_scope
from src.modules.sales.infrastructure.models import Customer, SalesInvoice, SalesInvoiceLine


class OrderQueriesMixin:
    async def list_orders(
        self, filters: OrderFilters, limit: int, offset: int
    ) -> tuple[list[OrderSummary], int]:
        """Return active sales invoices newest first.

        Line counts are computed only for the page's invoices (after LIMIT/OFFSET),
        never by grouping the whole line table.
        """
        predicates = [SalesInvoice.deleted_at.is_(None)]
        order_from = SalesInvoice.__table__
        if filters.customer_id:
            predicates.append(SalesInvoice.customer_id == filters.customer_id)
        if filters.customer_geography:
            # Current customer geography; same scope definition as the dashboards.
            order_from = order_from.join(
                Customer.__table__, Customer.customer_id == SalesInvoice.customer_id
            )
            predicates.extend(customer_scope(filters).conditions())
        else:
            if filters.ward_names:
                predicates.append(
                    SalesInvoice.customer_ward_name_snapshot.in_(filters.ward_names)
                )
            if filters.village_names:
                predicates.append(
                    SalesInvoice.customer_village_name_snapshot.in_(filters.village_names)
                )
        if filters.date_from:
            predicates.append(SalesInvoice.issued_at >= filters.date_from)
        if filters.date_to:
            predicates.append(SalesInvoice.issued_at < filters.date_to)
        if filters.invoice_number:
            predicates.append(
                SalesInvoice.invoice_number.icontains(filters.invoice_number, autoescape=True)
            )

        page = (
            select(
                SalesInvoice.invoice_id,
                SalesInvoice.invoice_number,
                SalesInvoice.issued_at,
                SalesInvoice.customer_name_snapshot.label("customer_name"),
                SalesInvoice.customer_ward_name_snapshot.label("customer_ward_name"),
                SalesInvoice.customer_village_name_snapshot.label("customer_village_name"),
                SalesInvoice.invoice_total_amount,
            )
            .select_from(order_from)
            .where(*predicates)
            .order_by(
                SalesInvoice.issued_at.desc(),
                SalesInvoice.invoice_number.desc(),
                SalesInvoice.invoice_id.desc(),
            )
            .offset(offset)
            .limit(limit)
            .subquery("order_page")
        )
        line_count = (
            select(func.count(SalesInvoiceLine.invoice_line_id))
            .where(
                SalesInvoiceLine.invoice_id == page.c.invoice_id,
                SalesInvoiceLine.deleted_at.is_(None),
            )
            .correlate(page)
            .scalar_subquery()
        )
        statement = select(page, line_count.label("line_count")).order_by(
            page.c.issued_at.desc(),
            page.c.invoice_number.desc(),
            page.c.invoice_id.desc(),
        )
        count_statement = (
            select(func.count(SalesInvoice.invoice_id)).select_from(order_from).where(*predicates)
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
            SalesInvoice.customer_address_detail_snapshot.label("customer_address_detail"),
            SalesInvoice.customer_ward_name_snapshot.label("customer_ward_name"),
            SalesInvoice.customer_village_name_snapshot.label("customer_village_name"),
            SalesInvoice.invoice_total_amount,
            SalesInvoice.customer_id,
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
            customer_id=str(invoice.customer_id) if invoice.customer_id else None,
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
