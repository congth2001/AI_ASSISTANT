"""Pure assembly of the customer transaction ledger.

The signed ledger ``customer_debt_transactions`` is the only source of movement and
running balance. Invoices and return slips only add display detail (product lines,
payment split). Consequences:

* the running balance always equals the ledger balance, whatever the invoice data;
* ledger rows without a displayable document still appear as one line;
* documents that never touched the ledger (fully paid invoices, zero returns) show
  with a zero movement.

Matching: returns link by ``SalesReturn.source_id == ledger.source_id``; sales link by
``(customer_id, issued_at == occurred_at)`` because the ledger stores the legacy
source invoice id, not ``sales_invoices.invoice_id``. When several invoices share the
same customer and timestamp, the combined ledger amount is attributed to the first
invoice (by invoice number) and the others show a zero movement.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.modules.analytics.domain.models.order_ledger import OrderLedgerExportItem
from src.modules.analytics.infrastructure.repositories.ledger_document_matching import (
    first_invoice_by_sale_key,
    receipt_voucher,
)

ZERO = Decimal("0")


@dataclass(frozen=True)
class LedgerEntry:
    customer_id: str
    source_type: str
    source_id: str
    occurred_at: datetime
    amount: Decimal


@dataclass(frozen=True)
class DocumentLine:
    """One display row of a sales invoice or return; ``line_number`` is None when the document has no lines."""

    document_id: str
    voucher_number: str
    occurred_at: datetime
    customer_id: str
    total_amount: Decimal
    source_id: str | None
    line_number: int | None
    product_name: str | None
    unit_name: str | None
    unit_price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class CustomerProfile:
    customer_id: str
    name: str
    address: str | None


@dataclass
class _Event:
    customer_id: str
    occurred_at: datetime
    voucher_number: str
    reason: str
    reason_order: int
    line_number: int
    product_name: str | None
    unit_name: str | None
    unit_price: Decimal
    quantity: Decimal
    payment_amount: Decimal
    debt_amount: Decimal
    movement: Decimal


def _document_events(
    lines: list[DocumentLine],
    *,
    reason: str,
    reason_order: int,
    movement_for,
) -> list[_Event]:
    events: list[_Event] = []
    seen: set[str] = set()
    for line in lines:
        first = line.document_id not in seen
        seen.add(line.document_id)
        movement = movement_for(line) if first else ZERO
        events.append(_Event(
            customer_id=line.customer_id,
            occurred_at=line.occurred_at,
            voucher_number=line.voucher_number,
            reason=reason,
            reason_order=reason_order,
            line_number=int(line.line_number or 0),
            product_name=line.product_name,
            unit_name=line.unit_name,
            unit_price=line.unit_price,
            quantity=line.quantity,
            payment_amount=(
                line.total_amount - movement if reason_order == 1 and first else ZERO
            ),
            debt_amount=movement,
            movement=movement,
        ))
    return events


def build_ledger_events(
    entries: list[LedgerEntry],
    sale_lines: list[DocumentLine],
    return_lines: list[DocumentLine],
) -> list[_Event]:
    """Turn ledger entries and document lines into ordered display events."""
    events: list[_Event] = []

    sale_amount_by_key: dict[tuple[str, datetime], Decimal] = defaultdict(lambda: ZERO)
    sale_entries: dict[tuple[str, datetime], list[LedgerEntry]] = defaultdict(list)
    return_amount_by_source: dict[str, Decimal] = defaultdict(lambda: ZERO)
    return_entries: dict[str, list[LedgerEntry]] = defaultdict(list)
    for entry in entries:
        if entry.source_type == "sale":
            key = (entry.customer_id, entry.occurred_at)
            sale_amount_by_key[key] += entry.amount
            sale_entries[key].append(entry)
        elif entry.source_type == "sales_return":
            return_amount_by_source[entry.source_id] += entry.amount
            return_entries[entry.source_id].append(entry)
        elif entry.source_type == "receipt":
            events.append(_Event(
                customer_id=entry.customer_id,
                occurred_at=entry.occurred_at,
                voucher_number=receipt_voucher(entry.source_id, entry.occurred_at),
                reason="Thu nợ",
                reason_order=3,
                line_number=0,
                product_name=None,
                unit_name=None,
                unit_price=ZERO,
                quantity=ZERO,
                payment_amount=abs(entry.amount),
                debt_amount=ZERO,
                movement=entry.amount,
            ))

    # Sales: attribute each (customer, timestamp) ledger amount to the first invoice there.
    first_invoice_at_key = {
        key: document_id
        for key, (document_id, _) in first_invoice_by_sale_key(
            (line.customer_id, line.occurred_at, line.voucher_number, line.document_id)
            for line in sale_lines
        ).items()
    }

    def sale_movement(line: DocumentLine) -> Decimal:
        key = (line.customer_id, line.occurred_at)
        if first_invoice_at_key.get(key) != line.document_id:
            return ZERO
        return sale_amount_by_key.get(key, ZERO)

    events.extend(_document_events(
        sale_lines, reason="Xuất bán", reason_order=1, movement_for=sale_movement,
    ))
    matched_sale_keys = set(first_invoice_at_key)
    for key, rows in sale_entries.items():
        if key in matched_sale_keys:
            continue
        for entry in rows:
            events.append(_standalone_event(entry, reason="Xuất bán", reason_order=1))

    def return_movement(line: DocumentLine) -> Decimal:
        return return_amount_by_source.get(line.source_id or "", ZERO)

    events.extend(_document_events(
        return_lines, reason="Nhập trả", reason_order=2, movement_for=return_movement,
    ))
    matched_return_sources = {line.source_id for line in return_lines if line.source_id}
    for source_id, rows in return_entries.items():
        if source_id in matched_return_sources:
            continue
        for entry in rows:
            events.append(_standalone_event(entry, reason="Nhập trả", reason_order=2))
    return events


def _standalone_event(entry: LedgerEntry, *, reason: str, reason_order: int) -> _Event:
    """Ledger movement whose document is not available for display."""
    return _Event(
        customer_id=entry.customer_id,
        occurred_at=entry.occurred_at,
        voucher_number=entry.source_id,
        reason=reason,
        reason_order=reason_order,
        line_number=0,
        product_name=None,
        unit_name=None,
        unit_price=ZERO,
        quantity=ZERO,
        payment_amount=ZERO,
        debt_amount=entry.amount,
        movement=entry.amount,
    )


def build_ledger_items(
    *,
    profiles: dict[str, CustomerProfile],
    opening_balances: dict[str, Decimal],
    entries: list[LedgerEntry],
    sale_lines: list[DocumentLine],
    return_lines: list[DocumentLine],
    invoice_search: str | None = None,
) -> list[OrderLedgerExportItem]:
    """Order events per customer, accumulate the ledger balance, then apply the voucher filter."""
    by_customer: dict[str, list[_Event]] = defaultdict(list)
    for event in build_ledger_events(entries, sale_lines, return_lines):
        by_customer[event.customer_id].append(event)

    def customer_name(customer_id: str) -> str:
        profile = profiles.get(customer_id)
        return profile.name if profile else ""

    search = invoice_search.casefold() if invoice_search else None
    output: list[OrderLedgerExportItem] = []
    for customer_id in sorted(by_customer, key=lambda cid: (customer_name(cid).casefold(), cid)):
        profile = profiles.get(customer_id)
        running = opening_balances.get(customer_id, ZERO)
        ordered = sorted(by_customer[customer_id], key=lambda e: (
            e.occurred_at, e.reason_order, e.voucher_number, e.line_number,
        ))
        for event in ordered:
            running += event.movement
            if search and search not in event.voucher_number.casefold():
                continue
            output.append(OrderLedgerExportItem(
                customer_id=customer_id,
                customer_name=profile.name if profile else "",
                customer_address=profile.address if profile else None,
                occurred_at=event.occurred_at,
                voucher_number=event.voucher_number,
                reason=event.reason,
                product_name=event.product_name,
                unit_name=event.unit_name,
                unit_price=event.unit_price,
                quantity=event.quantity,
                payment_amount=event.payment_amount,
                debt_amount=event.debt_amount,
                running_debt=running,
            ))
    return output
