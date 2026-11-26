"""How debt-ledger rows are matched to displayable documents.

Shared by the order-ledger export (``order_ledger_builder``) and the customer
debt-history page so both always show the same voucher for the same ledger row.

* ``sale`` rows store the legacy source invoice id, not ``sales_invoices.invoice_id``;
  they match invoices numbered ``XB...`` by ``(customer_id, issued_at == occurred_at)``.
  When several invoices share that key, the first by invoice number takes the
  movement.
* ``sales_return`` rows match ``sales_returns`` numbered ``NT...`` by ``source_id``.
* ``receipt`` rows have no document; their voucher is derived from ``source_id``.
"""
from collections.abc import Iterable
from datetime import datetime

SALE_VOUCHER_PATTERN = "XB%"
RETURN_VOUCHER_PATTERN = "NT%"

SaleKey = tuple[str, datetime]


def receipt_voucher(source_id: str, occurred_at: datetime) -> str:
    month_suffix = occurred_at.strftime("%m%y")
    return source_id if source_id.endswith(f"-{month_suffix}") else f"{source_id}-{month_suffix}"


def first_invoice_by_sale_key(
    invoices: Iterable[tuple[str, datetime, str, str]],
) -> dict[SaleKey, tuple[str, str]]:
    """Map ``(customer_id, occurred_at)`` to ``(document_id, voucher_number)`` of its first invoice.

    ``invoices`` yields ``(customer_id, occurred_at, voucher_number, document_id)``;
    duplicates (one per invoice line) are fine.
    """
    first: dict[SaleKey, tuple[str, str]] = {}
    for customer_id, occurred_at, voucher_number, document_id in sorted(
        invoices, key=lambda row: (row[2], row[3])
    ):
        first.setdefault((customer_id, occurred_at), (document_id, voucher_number))
    return first
