"""Order-ledger export queries (see ``order_ledger_builder`` for the assembly rules)."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select

from src.modules.analytics.domain.errors import CustomerNotFoundError, OrderLedgerRowLimitError
from src.modules.analytics.domain.models.export_limits import MAX_SHEET_DATA_ROWS
from src.modules.analytics.domain.models.order_ledger import (
    OrderLedgerExportData,
    OrderLedgerExportFilters,
)
from src.modules.analytics.infrastructure.repositories.analytics_scope import CustomerScope
from src.modules.analytics.infrastructure.repositories.order_ledger_builder import (
    CustomerProfile,
    DocumentLine,
    LedgerEntry,
    build_ledger_items,
)
from src.modules.sales.infrastructure.models import (
    Customer,
    CustomerDebtTransaction,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
)


def ledger_scope(filters: OrderLedgerExportFilters) -> CustomerScope:
    """Customer scope of the ledger.

    An explicit customer wins: geography filters are ignored so opening balance,
    receipts, sales and returns all come from the same customer. Geography (current
    ``customers`` values, never invoice snapshots) only applies to customer-less exports.
    """
    if filters.customer_id:
        return CustomerScope(customer_id=filters.customer_id)
    return CustomerScope(
        ward_names=tuple(filters.ward_names), village_names=tuple(filters.village_names)
    )


class OrderLedgerQueriesMixin:
    async def get_order_ledger_export(
        self, filters: OrderLedgerExportFilters
    ) -> OrderLedgerExportData:
        scope = ledger_scope(filters)
        end_exclusive = filters.date_to + timedelta(days=1) if filters.date_to else None

        def in_range(column) -> list:
            predicates = []
            if filters.date_from:
                predicates.append(column >= filters.date_from)
            if end_exclusive:
                predicates.append(column < end_exclusive)
            return predicates

        limit = MAX_SHEET_DATA_ROWS + 1
        entry_statement = (
            select(
                CustomerDebtTransaction.customer_id,
                CustomerDebtTransaction.source_type,
                CustomerDebtTransaction.source_id,
                CustomerDebtTransaction.occurred_at,
                CustomerDebtTransaction.amount,
            )
            .where(
                CustomerDebtTransaction.deleted_at.is_(None),
                CustomerDebtTransaction.source_type != "opening",
                scope.contains(CustomerDebtTransaction.customer_id),
                *in_range(CustomerDebtTransaction.occurred_at),
            )
            .order_by(
                CustomerDebtTransaction.occurred_at,
                CustomerDebtTransaction.source_type,
                CustomerDebtTransaction.source_id,
            )
            .limit(limit)
        )

        # Opening balance = rows typed 'opening' plus everything before date_from,
        # never anything at or after the end of the range.
        opening_cutoff = [CustomerDebtTransaction.source_type == "opening"]
        if filters.date_from:
            opening_cutoff.append(CustomerDebtTransaction.occurred_at < filters.date_from)
        opening_predicates = [
            CustomerDebtTransaction.deleted_at.is_(None),
            scope.contains(CustomerDebtTransaction.customer_id),
            or_(*opening_cutoff),
        ]
        if end_exclusive:
            opening_predicates.append(CustomerDebtTransaction.occurred_at < end_exclusive)
        opening_statement = (
            select(
                CustomerDebtTransaction.customer_id,
                func.coalesce(func.sum(CustomerDebtTransaction.amount), 0).label("opening_balance"),
            )
            .where(*opening_predicates)
            .group_by(CustomerDebtTransaction.customer_id)
        )

        sale_statement = (
            select(
                SalesInvoice.invoice_id.label("document_id"),
                SalesInvoice.invoice_number.label("voucher_number"),
                SalesInvoice.issued_at.label("occurred_at"),
                SalesInvoice.customer_id,
                SalesInvoice.invoice_total_amount.label("total_amount"),
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
                scope.contains(SalesInvoice.customer_id),
                *in_range(SalesInvoice.issued_at),
            )
            .order_by(SalesInvoice.issued_at, SalesInvoice.invoice_number, SalesInvoiceLine.line_number)
            .limit(limit)
        )
        return_statement = (
            select(
                SalesReturn.return_id.label("document_id"),
                SalesReturn.return_number.label("voucher_number"),
                SalesReturn.returned_at.label("occurred_at"),
                SalesReturn.customer_id,
                SalesReturn.return_total_amount.label("total_amount"),
                SalesReturn.source_id,
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
                scope.contains(SalesReturn.customer_id),
                *in_range(SalesReturn.returned_at),
            )
            .order_by(SalesReturn.returned_at, SalesReturn.return_number, SalesReturnLine.line_number)
            .limit(limit)
        )
        profile_statement = select(
            Customer.customer_id, Customer.customer_name, Customer.address_detail
        ).where(*scope.conditions())

        async with self._session_factory() as session:
            if filters.customer_id:
                customer_row = (await session.execute(
                    profile_statement
                )).one_or_none()
                if customer_row is None:
                    raise CustomerNotFoundError()
            else:
                customer_row = None
            entry_rows = (await session.execute(entry_statement)).all()
            if len(entry_rows) > MAX_SHEET_DATA_ROWS:
                raise OrderLedgerRowLimitError(max_rows=MAX_SHEET_DATA_ROWS)
            sale_rows = (await session.execute(sale_statement)).all()
            if len(sale_rows) > MAX_SHEET_DATA_ROWS:
                raise OrderLedgerRowLimitError(max_rows=MAX_SHEET_DATA_ROWS)
            return_rows = (await session.execute(return_statement)).all()
            if len(return_rows) > MAX_SHEET_DATA_ROWS:
                raise OrderLedgerRowLimitError(max_rows=MAX_SHEET_DATA_ROWS)
            opening_rows = (await session.execute(opening_statement)).all()
            profile_rows = (
                [customer_row] if customer_row is not None
                else (await session.execute(profile_statement)).all()
            )

        profiles = {
            str(row.customer_id): CustomerProfile(
                customer_id=str(row.customer_id),
                name=row.customer_name,
                address=row.address_detail or None,
            )
            for row in profile_rows
        }
        items = build_ledger_items(
            profiles=profiles,
            opening_balances={str(r.customer_id): Decimal(r.opening_balance) for r in opening_rows},
            entries=[
                LedgerEntry(
                    customer_id=str(r.customer_id), source_type=r.source_type,
                    source_id=str(r.source_id), occurred_at=r.occurred_at, amount=Decimal(r.amount),
                )
                for r in entry_rows
            ],
            sale_lines=[
                DocumentLine(
                    document_id=str(r.document_id), voucher_number=r.voucher_number,
                    occurred_at=r.occurred_at, customer_id=str(r.customer_id),
                    total_amount=Decimal(r.total_amount), source_id=None,
                    line_number=r.line_number, product_name=r.product_name,
                    unit_name=r.unit_name, unit_price=Decimal(r.unit_price or 0),
                    quantity=Decimal(r.quantity or 0),
                )
                for r in sale_rows
            ],
            return_lines=[
                DocumentLine(
                    document_id=str(r.document_id), voucher_number=r.voucher_number,
                    occurred_at=r.occurred_at, customer_id=str(r.customer_id),
                    total_amount=Decimal(r.total_amount), source_id=str(r.source_id),
                    line_number=r.line_number, product_name=r.product_name,
                    unit_name=r.unit_name, unit_price=Decimal(r.unit_price or 0),
                    quantity=Decimal(r.quantity or 0),
                )
                for r in return_rows
            ],
            invoice_search=filters.invoice_number,
        )
        if len(items) > MAX_SHEET_DATA_ROWS:
            raise OrderLedgerRowLimitError(max_rows=MAX_SHEET_DATA_ROWS)

        first = items[0] if items else None
        if customer_row is not None:
            return OrderLedgerExportData(
                customer_id=str(customer_row.customer_id),
                customer_name=customer_row.customer_name,
                customer_address=customer_row.address_detail or None,
                items=tuple(items),
            )
        return OrderLedgerExportData(
            customer_id=first.customer_id if first else (filters.customer_id or ""),
            customer_name=first.customer_name if first else "",
            customer_address=first.customer_address if first else None,
            items=tuple(items),
        )
