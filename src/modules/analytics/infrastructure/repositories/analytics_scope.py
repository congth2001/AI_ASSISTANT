"""One definition of "which customers/lines are in scope" for every analytics query.

Summary, time series, rankings, customer overview and insights all read these
helpers so the same filters always select the same customers and amounts.

Customer scope: a customer is in scope when it is not soft-deleted and matches the
optional ``customer_id``, ``ward_names`` and ``village_names`` (current geography
from ``customers``). The scope is applied to fact tables through a semi-join
(``customer_id IN (SELECT ...)``), so customers with only returns or ledger rows
are treated exactly like customers with invoices.

Line scope: when a category or product filter is present, revenue is measured at
line grain (``sales_invoice_lines.line_amount`` minus ``sales_return_lines.line_amount``)
instead of invoice totals and ledger return rows.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy import Select, String, Subquery, cast, null, select, union_all
from sqlalchemy.sql.elements import ColumnElement

from src.modules.sales.infrastructure.models import (
    Customer,
    CustomerDebtTransaction,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
)


class _CustomerFilters(Protocol):
    customer_id: str | None
    ward_names: tuple[str, ...]
    village_names: tuple[str, ...]


class _LineFilters(Protocol):
    category_names: tuple[str, ...]
    product_names: tuple[str, ...]


@dataclass(frozen=True)
class CustomerScope:
    customer_id: str | None = None
    ward_names: tuple[str, ...] = ()
    village_names: tuple[str, ...] = ()

    def conditions(self) -> list[ColumnElement]:
        """Predicates on ``customers`` (use when the query already joins it)."""
        predicates: list[ColumnElement] = [Customer.deleted_at.is_(None)]
        if self.customer_id:
            predicates.append(Customer.customer_id == self.customer_id)
        if self.ward_names:
            predicates.append(Customer.ward_name.in_(self.ward_names))
        if self.village_names:
            predicates.append(Customer.village_name.in_(self.village_names))
        return predicates

    def customer_ids(self) -> Select:
        # correlate(None): never merge this subquery's FROM into an outer ``customers``.
        return select(Customer.customer_id).where(*self.conditions()).correlate(None)

    def contains(self, customer_id_column) -> ColumnElement:
        """Semi-join predicate for a fact table's ``customer_id`` column."""
        return customer_id_column.in_(self.customer_ids())


def customer_scope(filters: _CustomerFilters) -> CustomerScope:
    return CustomerScope(
        customer_id=filters.customer_id,
        ward_names=tuple(filters.ward_names),
        village_names=tuple(filters.village_names),
    )


def has_line_filters(filters: _LineFilters) -> bool:
    return bool(filters.category_names or filters.product_names)


def sales_line_conditions(filters: _LineFilters) -> list[ColumnElement]:
    predicates: list[ColumnElement] = [SalesInvoiceLine.deleted_at.is_(None)]
    if filters.category_names:
        predicates.append(SalesInvoiceLine.product_category_name.in_(filters.category_names))
    if filters.product_names:
        predicates.append(SalesInvoiceLine.product_name.in_(filters.product_names))
    return predicates


def return_line_conditions(filters: _LineFilters) -> list[ColumnElement]:
    predicates: list[ColumnElement] = [SalesReturnLine.deleted_at.is_(None)]
    if filters.category_names:
        predicates.append(SalesReturnLine.product_category_name.in_(filters.category_names))
    if filters.product_names:
        predicates.append(SalesReturnLine.product_name.in_(filters.product_names))
    return predicates


def sales_line_predicates(filters, date_from: date, date_to: date) -> list[ColumnElement]:
    """Predicates for ``SalesInvoiceLine JOIN SalesInvoice`` in ``[date_from, date_to)``."""
    return [
        SalesInvoice.deleted_at.is_(None),
        SalesInvoice.issued_at >= date_from,
        SalesInvoice.issued_at < date_to,
        customer_scope(filters).contains(SalesInvoice.customer_id),
        *sales_line_conditions(filters),
    ]


def return_line_predicates(filters, date_from: date, date_to: date) -> list[ColumnElement]:
    """Predicates for ``SalesReturnLine JOIN SalesReturn`` in ``[date_from, date_to)``."""
    return [
        SalesReturn.deleted_at.is_(None),
        SalesReturn.returned_at >= date_from,
        SalesReturn.returned_at < date_to,
        customer_scope(filters).contains(SalesReturn.customer_id),
        *return_line_conditions(filters),
    ]


def sales_lines_from():
    return SalesInvoiceLine.__table__.join(
        SalesInvoice.__table__, SalesInvoice.invoice_id == SalesInvoiceLine.invoice_id
    )


def return_lines_from():
    return SalesReturnLine.__table__.join(
        SalesReturn.__table__, SalesReturn.return_id == SalesReturnLine.return_id
    )


def revenue_movements(filters, date_from: date, date_to: date, name: str) -> Subquery:
    """Signed revenue movements per customer in ``[date_from, date_to)``.

    Columns: ``customer_id``, ``occurred_at``, ``amount`` and ``invoice_id``
    (``NULL`` for returns, so ``count(distinct invoice_id)`` counts sales only).

    Without line filters: invoice totals plus ``sales_return`` ledger rows (already
    negative). With category/product filters: matching sales line amounts minus
    matching return line amounts. Both shapes honour ``customer_scope``.
    """
    scope = customer_scope(filters)
    if has_line_filters(filters):
        sales = (
            select(
                SalesInvoice.customer_id.label("customer_id"),
                SalesInvoice.issued_at.label("occurred_at"),
                SalesInvoiceLine.line_amount.label("amount"),
                SalesInvoice.invoice_id.label("invoice_id"),
            )
            .select_from(sales_lines_from())
            .where(*sales_line_predicates(filters, date_from, date_to))
        )
        returns = (
            select(
                SalesReturn.customer_id,
                SalesReturn.returned_at,
                -SalesReturnLine.line_amount,
                cast(null(), String),
            )
            .select_from(return_lines_from())
            .where(*return_line_predicates(filters, date_from, date_to))
        )
    else:
        sales = select(
            SalesInvoice.customer_id.label("customer_id"),
            SalesInvoice.issued_at.label("occurred_at"),
            SalesInvoice.invoice_total_amount.label("amount"),
            SalesInvoice.invoice_id.label("invoice_id"),
        ).where(
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.issued_at >= date_from,
            SalesInvoice.issued_at < date_to,
            scope.contains(SalesInvoice.customer_id),
        )
        returns = select(
            CustomerDebtTransaction.customer_id,
            CustomerDebtTransaction.occurred_at,
            CustomerDebtTransaction.amount,
            cast(null(), String),
        ).where(
            CustomerDebtTransaction.deleted_at.is_(None),
            CustomerDebtTransaction.source_type == "sales_return",
            CustomerDebtTransaction.occurred_at >= date_from,
            CustomerDebtTransaction.occurred_at < date_to,
            scope.contains(CustomerDebtTransaction.customer_id),
        )
    return union_all(sales, returns).subquery(name)
