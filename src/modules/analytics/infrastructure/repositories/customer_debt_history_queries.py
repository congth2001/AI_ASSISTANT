"""Customer debt-history and revision-audit queries (mixin of ``DashboardAnalyticsRepository``).

Every query filters by one customer (index ``ix_debt_transactions_customer_occurred``)
or by run time. Documents are matched only for the rows of the current page, with
the rules of ``ledger_document_matching`` shared with the order-ledger export.
"""
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import case, func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.domain.time import VIETNAM_TIMEZONE
from src.modules.analytics.domain.models.customer_debt_history import (
    CustomerDebtProfile,
    CustomerDebtRevisionItem,
    DebtHistoryEntry,
    DebtHistoryEntryCursor,
    DebtHistoryEntryFilters,
    DebtLedgerEntry,
    DebtRevisionChangeItem,
    DebtRevisionFilters,
    DebtRevisionListItem,
    DebtRevisionSummary,
    LatestSyncRun,
    RunCursor,
)
from src.modules.analytics.domain.services.debt_history import TYPE_ORDER, UNKNOWN_TYPE_ORDER
from src.modules.analytics.infrastructure.repositories.ledger_document_matching import (
    RETURN_VOUCHER_PATTERN,
    SALE_VOUCHER_PATTERN,
    first_invoice_by_sale_key,
    receipt_voucher,
)
from src.modules.sales.infrastructure.models import (
    Customer,
    CustomerDebtRevision,
    CustomerDebtTransaction,
    CustomerDebtTransactionChange,
    EtlSyncRun,
    SalesInvoice,
    SalesReturn,
)


def _type_order(column):
    return case(TYPE_ORDER, value=column, else_=UNKNOWN_TYPE_ORDER)


def _day_start(day: date) -> datetime:
    """Naive Vietnam-local midnight, for the naive ``occurred_at`` columns."""
    return datetime.combine(day, time.min)


def _vietnam_day_start(day: date) -> datetime:
    """Aware Vietnam midnight, for ``timestamptz`` run columns."""
    return datetime.combine(day, time.min, tzinfo=VIETNAM_TIMEZONE)


def _decimal(value) -> Decimal | None:
    return None if value is None else Decimal(value)


class _DocumentRef:
    __slots__ = ("voucher_number", "invoice_id", "return_id")

    def __init__(self, voucher_number: str, invoice_id: str | None = None, return_id: str | None = None):
        self.voucher_number = voucher_number
        self.invoice_id = invoice_id
        self.return_id = return_id


async def _match_documents(
    session: AsyncSession,
    rows: Sequence[tuple[str, str, str, datetime]],
) -> list[_DocumentRef]:
    """Voucher (and document ids) for ``(source_type, source_id, customer_id, occurred_at)`` rows."""
    sale_rows = [row for row in rows if row[0] == "sale"]
    return_rows = [row for row in rows if row[0] == "sales_return"]

    first_invoice = {}
    if sale_rows:
        invoices = (await session.execute(
            select(
                SalesInvoice.customer_id, SalesInvoice.issued_at,
                SalesInvoice.invoice_number, SalesInvoice.invoice_id,
            ).where(
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.invoice_number.ilike(SALE_VOUCHER_PATTERN),
                SalesInvoice.customer_id.in_({row[2] for row in sale_rows}),
                SalesInvoice.issued_at.in_({row[3] for row in sale_rows}),
            )
        )).all()
        first_invoice = first_invoice_by_sale_key(
            (str(r.customer_id), r.issued_at, r.invoice_number, str(r.invoice_id)) for r in invoices
        )

    returns_by_source = {}
    if return_rows:
        returns = (await session.execute(
            select(
                SalesReturn.source_id, SalesReturn.customer_id,
                SalesReturn.return_number, SalesReturn.return_id,
            ).where(
                SalesReturn.deleted_at.is_(None),
                SalesReturn.return_number.ilike(RETURN_VOUCHER_PATTERN),
                SalesReturn.source_id.in_({row[1] for row in return_rows}),
                SalesReturn.customer_id.in_({row[2] for row in return_rows}),
            )
        )).all()
        returns_by_source = {
            (str(r.source_id), str(r.customer_id)): (r.return_number, str(r.return_id))
            for r in returns
        }

    refs: list[_DocumentRef] = []
    for source_type, source_id, customer_id, occurred_at in rows:
        if source_type == "sale" and (customer_id, occurred_at) in first_invoice:
            invoice_id, number = first_invoice[(customer_id, occurred_at)]
            refs.append(_DocumentRef(number, invoice_id=invoice_id))
        elif source_type == "sales_return" and (source_id, customer_id) in returns_by_source:
            number, return_id = returns_by_source[(source_id, customer_id)]
            refs.append(_DocumentRef(number, return_id=return_id))
        elif source_type == "receipt":
            refs.append(_DocumentRef(receipt_voucher(source_id, occurred_at)))
        else:
            refs.append(_DocumentRef(source_id))
    return refs


def _run_position(cursor: RunCursor):
    return (
        literal(cursor.started_at, type_=EtlSyncRun.started_at.type),
        literal(cursor.run_id, type_=EtlSyncRun.run_id.type),
    )


class CustomerDebtHistoryQueriesMixin:
    async def get_customer_profile(self, customer_id: str) -> CustomerDebtProfile | None:
        statement = select(
            Customer.customer_id, Customer.customer_name, Customer.address_detail,
            Customer.village_name, Customer.ward_name,
        ).where(Customer.customer_id == customer_id, Customer.deleted_at.is_(None))
        async with self._session_factory() as session:
            row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        return CustomerDebtProfile(
            customer_id=str(row.customer_id),
            customer_name=row.customer_name,
            address_detail=row.address_detail or None,
            village_name=row.village_name or None,
            ward_name=row.ward_name or None,
        )

    async def list_ledger_entries(
        self, customer_id: str, until: datetime, limit: int
    ) -> list[DebtLedgerEntry]:
        statement = (
            select(
                CustomerDebtTransaction.debt_transaction_id,
                CustomerDebtTransaction.occurred_at,
                CustomerDebtTransaction.source_type,
                CustomerDebtTransaction.source_id,
                CustomerDebtTransaction.amount,
            )
            .where(
                CustomerDebtTransaction.customer_id == customer_id,
                CustomerDebtTransaction.deleted_at.is_(None),
                CustomerDebtTransaction.occurred_at < until,
            )
            .order_by(
                CustomerDebtTransaction.occurred_at,
                _type_order(CustomerDebtTransaction.source_type),
                CustomerDebtTransaction.source_id,
            )
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [
            DebtLedgerEntry(
                entry_id=row.debt_transaction_id, occurred_at=row.occurred_at,
                source_type=row.source_type, source_id=row.source_id, amount=Decimal(row.amount),
            )
            for row in rows
        ]

    async def get_current_balance(self, customer_id: str) -> Decimal:
        statement = select(func.coalesce(func.sum(CustomerDebtTransaction.amount), 0)).where(
            CustomerDebtTransaction.customer_id == customer_id,
            CustomerDebtTransaction.deleted_at.is_(None),
        )
        async with self._session_factory() as session:
            return Decimal((await session.execute(statement)).scalar_one())

    async def get_revision_summary(self, customer_id: str) -> DebtRevisionSummary:
        count_statement = select(func.count()).select_from(CustomerDebtRevision).where(
            CustomerDebtRevision.customer_id == customer_id
        )
        latest_statement = (
            select(EtlSyncRun.started_at, CustomerDebtRevision.balance_delta)
            .join(EtlSyncRun, EtlSyncRun.run_id == CustomerDebtRevision.run_id)
            .where(CustomerDebtRevision.customer_id == customer_id)
            .order_by(EtlSyncRun.started_at.desc(), EtlSyncRun.run_id.desc())
            .limit(1)
        )
        async with self._session_factory() as session:
            count = int((await session.execute(count_statement)).scalar_one())
            latest = (await session.execute(latest_statement)).one_or_none()
        return DebtRevisionSummary(
            revision_count=count,
            last_revision_at=latest.started_at if latest else None,
            last_revision_delta=_decimal(latest.balance_delta) if latest else None,
        )

    async def list_entry_page(
        self,
        customer_id: str,
        filters: DebtHistoryEntryFilters,
        cursor: DebtHistoryEntryCursor | None,
        limit: int,
    ) -> tuple[list[tuple[DebtHistoryEntry, DebtHistoryEntryCursor]], bool]:
        ledger = (
            select(
                CustomerDebtTransaction.debt_transaction_id.label("entry_id"),
                CustomerDebtTransaction.occurred_at,
                CustomerDebtTransaction.source_type,
                CustomerDebtTransaction.source_id,
                CustomerDebtTransaction.amount,
                _type_order(CustomerDebtTransaction.source_type).label("type_order"),
            )
            .where(
                CustomerDebtTransaction.customer_id == customer_id,
                CustomerDebtTransaction.deleted_at.is_(None),
            )
            .subquery("ledger")
        )
        # Running balance over the WHOLE ledger, before any page/range filter.
        ordered = select(
            ledger,
            func.sum(ledger.c.amount).over(
                order_by=(ledger.c.occurred_at, ledger.c.type_order, ledger.c.source_id),
                rows=(None, 0),
            ).label("balance_after"),
        ).subquery("ordered")

        predicates = []
        if filters.date_from:
            predicates.append(ordered.c.occurred_at >= _day_start(filters.date_from))
        if filters.date_to:
            predicates.append(ordered.c.occurred_at < _day_start(filters.date_to + timedelta(days=1)))
        if filters.source_types:
            predicates.append(ordered.c.source_type.in_(filters.source_types))
        if cursor:
            predicates.append(
                tuple_(ordered.c.occurred_at, ordered.c.type_order, ordered.c.source_id)
                < tuple_(
                    literal(cursor.occurred_at, type_=CustomerDebtTransaction.occurred_at.type),
                    literal(cursor.type_order),
                    literal(cursor.source_id, type_=CustomerDebtTransaction.source_id.type),
                )
            )
        statement = (
            select(ordered)
            .where(*predicates)
            .order_by(
                ordered.c.occurred_at.desc(), ordered.c.type_order.desc(), ordered.c.source_id.desc()
            )
            .limit(limit + 1)
        )

        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
            has_more = len(rows) > limit
            rows = rows[:limit]
            refs = await _match_documents(
                session, [(r.source_type, r.source_id, customer_id, r.occurred_at) for r in rows]
            )
            revised = {}
            if rows:
                revised = dict((await session.execute(
                    select(
                        CustomerDebtTransactionChange.debt_transaction_id,
                        func.max(EtlSyncRun.started_at),
                    )
                    .join(EtlSyncRun, EtlSyncRun.run_id == CustomerDebtTransactionChange.run_id)
                    .where(CustomerDebtTransactionChange.debt_transaction_id.in_([r.entry_id for r in rows]))
                    .group_by(CustomerDebtTransactionChange.debt_transaction_id)
                )).all())

        items = []
        for row, ref in zip(rows, refs):
            entry = DebtHistoryEntry(
                entry_id=row.entry_id,
                occurred_at=row.occurred_at,
                source_type=row.source_type,
                source_id=row.source_id,
                voucher_number=ref.voucher_number,
                invoice_id=ref.invoice_id,
                return_id=ref.return_id,
                amount=Decimal(row.amount),
                balance_after=Decimal(row.balance_after),
                revised=row.entry_id in revised,
                last_revised_at=revised.get(row.entry_id),
            )
            position = DebtHistoryEntryCursor(
                occurred_at=row.occurred_at, type_order=int(row.type_order), source_id=row.source_id
            )
            items.append((entry, position))
        return items, has_more

    async def list_customer_revisions(
        self, customer_id: str, cursor: RunCursor | None, limit: int, max_changes: int
    ) -> tuple[list[CustomerDebtRevisionItem], bool]:
        predicates = [CustomerDebtRevision.customer_id == customer_id]
        if cursor:
            predicates.append(
                tuple_(EtlSyncRun.started_at, EtlSyncRun.run_id) < tuple_(*_run_position(cursor))
            )
        revision_statement = (
            select(
                CustomerDebtRevision.run_id, EtlSyncRun.started_at, EtlSyncRun.entrypoint,
                CustomerDebtRevision.balance_before, CustomerDebtRevision.balance_after,
                CustomerDebtRevision.balance_delta, CustomerDebtRevision.earliest_affected_at,
                CustomerDebtRevision.change_count,
            )
            .join(EtlSyncRun, EtlSyncRun.run_id == CustomerDebtRevision.run_id)
            .where(*predicates)
            .order_by(EtlSyncRun.started_at.desc(), EtlSyncRun.run_id.desc())
            .limit(limit + 1)
        )
        async with self._session_factory() as session:
            revisions = (await session.execute(revision_statement)).all()
            has_more = len(revisions) > limit
            revisions = revisions[:limit]
            changes_by_run: dict[str, list] = defaultdict(list)
            refs: list[_DocumentRef] = []
            change_rows = []
            if revisions:
                numbered = (
                    select(
                        CustomerDebtTransactionChange,
                        func.row_number().over(
                            partition_by=CustomerDebtTransactionChange.run_id,
                            order_by=CustomerDebtTransactionChange.change_id,
                        ).label("position"),
                    )
                    .where(
                        CustomerDebtTransactionChange.run_id.in_([str(r.run_id) for r in revisions]),
                        or_(
                            CustomerDebtTransactionChange.customer_id == customer_id,
                            CustomerDebtTransactionChange.previous_customer_id == customer_id,
                        ),
                    )
                    .subquery("numbered")
                )
                change_rows = (await session.execute(
                    select(numbered)
                    .where(numbered.c.position <= max_changes + 1)
                    .order_by(numbered.c.run_id, numbered.c.position)
                )).all()
                refs = await _match_documents(session, [
                    (
                        r.source_type, r.source_id,
                        str(r.customer_id),
                        r.new_occurred_at or r.old_occurred_at,
                    )
                    for r in change_rows
                ])
        for row, ref in zip(change_rows, refs):
            changes_by_run[str(row.run_id)].append((row, ref))

        items = []
        for revision in revisions:
            run_changes = changes_by_run.get(str(revision.run_id), [])
            items.append(CustomerDebtRevisionItem(
                run_id=str(revision.run_id),
                run_at=revision.started_at,
                entrypoint=revision.entrypoint,
                balance_before=Decimal(revision.balance_before),
                balance_after=Decimal(revision.balance_after),
                balance_delta=Decimal(revision.balance_delta),
                earliest_affected_at=revision.earliest_affected_at,
                change_count=revision.change_count,
                changes=tuple(
                    DebtRevisionChangeItem(
                        change_type=row.change_type,
                        source_type=row.source_type,
                        source_id=row.source_id,
                        voucher_number=ref.voucher_number,
                        customer_id=str(row.customer_id),
                        previous_customer_id=str(row.previous_customer_id) if row.previous_customer_id else None,
                        old_occurred_at=row.old_occurred_at,
                        new_occurred_at=row.new_occurred_at,
                        old_amount=_decimal(row.old_amount),
                        new_amount=_decimal(row.new_amount),
                        balance_delta=Decimal(row.balance_delta),
                    )
                    for row, ref in run_changes[:max_changes]
                ),
                has_more_changes=len(run_changes) > max_changes,
            ))
        return items, has_more

    async def list_debt_revisions(
        self, filters: DebtRevisionFilters, cursor: RunCursor | None, limit: int
    ) -> tuple[LatestSyncRun | None, list[DebtRevisionListItem], bool]:
        predicates = []
        if filters.date_from:
            predicates.append(EtlSyncRun.started_at >= _vietnam_day_start(filters.date_from))
        if filters.date_to:
            predicates.append(
                EtlSyncRun.started_at < _vietnam_day_start(filters.date_to + timedelta(days=1))
            )
        if filters.ward_names:
            predicates.append(Customer.ward_name.in_(filters.ward_names))
        if cursor:
            predicates.append(
                tuple_(EtlSyncRun.started_at, EtlSyncRun.run_id, CustomerDebtRevision.customer_id)
                < tuple_(
                    *_run_position(cursor),
                    literal(cursor.customer_id, type_=CustomerDebtRevision.customer_id.type),
                )
            )
        statement = (
            select(
                CustomerDebtRevision.run_id, EtlSyncRun.started_at, CustomerDebtRevision.customer_id,
                Customer.customer_name, Customer.ward_name, Customer.village_name,
                CustomerDebtRevision.balance_before, CustomerDebtRevision.balance_after,
                CustomerDebtRevision.balance_delta, CustomerDebtRevision.earliest_affected_at,
                CustomerDebtRevision.change_count,
            )
            .join(EtlSyncRun, EtlSyncRun.run_id == CustomerDebtRevision.run_id)
            .join(Customer, Customer.customer_id == CustomerDebtRevision.customer_id)
            .where(*predicates)
            .order_by(
                EtlSyncRun.started_at.desc(), EtlSyncRun.run_id.desc(),
                CustomerDebtRevision.customer_id.desc(),
            )
            .limit(limit + 1)
        )
        latest_statement = (
            select(EtlSyncRun.run_id, EtlSyncRun.started_at, EtlSyncRun.entrypoint, EtlSyncRun.is_baseline)
            .order_by(EtlSyncRun.started_at.desc(), EtlSyncRun.run_id.desc())
            .limit(1)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
            latest = (await session.execute(latest_statement)).one_or_none()
            latest_totals = None
            if latest is not None:
                latest_totals = (await session.execute(
                    select(func.count(), func.coalesce(func.sum(CustomerDebtRevision.balance_delta), 0))
                    .where(CustomerDebtRevision.run_id == latest.run_id)
                )).one()

        has_more = len(rows) > limit
        items = [
            DebtRevisionListItem(
                run_id=str(row.run_id), run_at=row.started_at, customer_id=str(row.customer_id),
                customer_name=row.customer_name, ward_name=row.ward_name or None,
                village_name=row.village_name or None,
                balance_before=Decimal(row.balance_before), balance_after=Decimal(row.balance_after),
                balance_delta=Decimal(row.balance_delta),
                earliest_affected_at=row.earliest_affected_at, change_count=row.change_count,
            )
            for row in rows[:limit]
        ]
        latest_run = None
        if latest is not None:
            latest_run = LatestSyncRun(
                run_id=str(latest.run_id), run_at=latest.started_at, entrypoint=latest.entrypoint,
                is_baseline=latest.is_baseline, revised_customers=int(latest_totals[0]),
                retroactive_delta=Decimal(latest_totals[1]),
            )
        return latest_run, items, has_more
