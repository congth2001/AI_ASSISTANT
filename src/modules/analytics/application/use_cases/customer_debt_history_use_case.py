"""Customer debt-history page: summary/series/aging, ledger entries and revision audit."""
import base64
import binascii
import json
from dataclasses import replace
from datetime import datetime, time, timedelta

from src.modules.analytics.domain.errors import (
    CustomerNotFoundError,
    DebtLedgerTooLargeError,
    InvalidDebtHistoryCursorError,
)
from src.modules.analytics.domain.models.customer_debt_history import (
    MAX_CHANGES_PER_REVISION,
    MAX_LEDGER_ENTRIES,
    CustomerDebtHistory,
    CustomerDebtProfile,
    CustomerDebtRevisionPage,
    DebtHistoryEntryCursor,
    DebtHistoryEntryFilters,
    DebtHistoryEntryPage,
    DebtHistoryFilters,
    DebtRevisionFilters,
    DebtRevisionListPage,
    RunCursor,
)
from src.modules.analytics.domain.repositories.i_customer_debt_history_repository import (
    ICustomerDebtHistoryRepository,
)
from src.modules.analytics.domain.services.debt_history import (
    balance_series,
    fifo_aging,
    summarize,
)

def _encode(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str, keys: set[str]) -> dict:
    """Strictly decode an opaque cursor; anything malformed is a 422."""
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise InvalidDebtHistoryCursorError() from exc
    if not isinstance(payload, dict) or set(payload) != keys:
        raise InvalidDebtHistoryCursorError()
    if not all(isinstance(payload[key], (str, int)) and not isinstance(payload[key], bool) for key in keys):
        raise InvalidDebtHistoryCursorError()
    return payload


def encode_entry_cursor(cursor: DebtHistoryEntryCursor) -> str:
    return _encode({
        "at": cursor.occurred_at.isoformat(), "order": cursor.type_order, "source": cursor.source_id,
    })


def decode_entry_cursor(value: str) -> DebtHistoryEntryCursor:
    payload = _decode(value, {"at", "order", "source"})
    try:
        occurred_at = datetime.fromisoformat(str(payload["at"]))
    except ValueError as exc:
        raise InvalidDebtHistoryCursorError() from exc
    if occurred_at.tzinfo is not None or not isinstance(payload["order"], int):
        raise InvalidDebtHistoryCursorError()
    return DebtHistoryEntryCursor(
        occurred_at=occurred_at, type_order=payload["order"], source_id=str(payload["source"])
    )


def encode_run_cursor(cursor: RunCursor) -> str:
    payload = {"at": cursor.started_at.isoformat(), "run": cursor.run_id}
    if cursor.customer_id is not None:
        payload["customer"] = cursor.customer_id
    return _encode(payload)


def decode_run_cursor(value: str, *, with_customer: bool) -> RunCursor:
    keys = {"at", "run", "customer"} if with_customer else {"at", "run"}
    payload = _decode(value, keys)
    try:
        started_at = datetime.fromisoformat(str(payload["at"]))
    except ValueError as exc:
        raise InvalidDebtHistoryCursorError() from exc
    if started_at.tzinfo is None:
        raise InvalidDebtHistoryCursorError()
    return RunCursor(
        started_at=started_at,
        run_id=str(payload["run"]),
        customer_id=str(payload["customer"]) if with_customer else None,
    )


class CustomerDebtHistoryUseCase:
    def __init__(self, repository: ICustomerDebtHistoryRepository):
        self._repository = repository

    async def _profile(self, customer_id: str) -> CustomerDebtProfile:
        profile = await self._repository.get_customer_profile(customer_id)
        if profile is None:
            raise CustomerNotFoundError()
        return profile

    async def get_history(self, customer_id: str, filters: DebtHistoryFilters) -> CustomerDebtHistory:
        profile = await self._profile(customer_id)
        until = datetime.combine(filters.date_to + timedelta(days=1), time.min)
        entries = await self._repository.list_ledger_entries(customer_id, until, MAX_LEDGER_ENTRIES + 1)
        if len(entries) > MAX_LEDGER_ENTRIES:
            raise DebtLedgerTooLargeError(max_entries=MAX_LEDGER_ENTRIES)
        series = balance_series(entries, filters.date_from, filters.date_to, filters.grain)
        current_balance = await self._repository.get_current_balance(customer_id)
        revisions = await self._repository.get_revision_summary(customer_id)
        summary = replace(
            summarize(entries, filters.date_from, filters.date_to, current_balance=current_balance),
            revision_count=revisions.revision_count,
            last_revision_at=revisions.last_revision_at,
            last_revision_delta=revisions.last_revision_delta,
        )
        return CustomerDebtHistory(
            customer=profile,
            date_from=filters.date_from,
            date_to=filters.date_to,
            grain=filters.grain,
            summary=summary,
            aging=fifo_aging(entries, filters.date_to),
            series=series,
        )

    async def list_entries(
        self,
        customer_id: str,
        filters: DebtHistoryEntryFilters,
        cursor: str | None,
        limit: int,
    ) -> DebtHistoryEntryPage:
        decoded = decode_entry_cursor(cursor) if cursor else None
        await self._profile(customer_id)
        rows, has_more = await self._repository.list_entry_page(customer_id, filters, decoded, limit)
        return DebtHistoryEntryPage(
            items=tuple(entry for entry, _ in rows),
            next_cursor=encode_entry_cursor(rows[-1][1]) if has_more and rows else None,
            has_more=has_more,
        )

    async def list_customer_revisions(
        self, customer_id: str, cursor: str | None, limit: int
    ) -> CustomerDebtRevisionPage:
        decoded = decode_run_cursor(cursor, with_customer=False) if cursor else None
        await self._profile(customer_id)
        items, has_more = await self._repository.list_customer_revisions(
            customer_id, decoded, limit, MAX_CHANGES_PER_REVISION
        )
        next_cursor = None
        if has_more and items:
            next_cursor = encode_run_cursor(RunCursor(started_at=items[-1].run_at, run_id=items[-1].run_id))
        return CustomerDebtRevisionPage(items=tuple(items), next_cursor=next_cursor, has_more=has_more)

    async def list_revisions(
        self, filters: DebtRevisionFilters, cursor: str | None, limit: int
    ) -> DebtRevisionListPage:
        decoded = decode_run_cursor(cursor, with_customer=True) if cursor else None
        latest, items, has_more = await self._repository.list_debt_revisions(filters, decoded, limit)
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_run_cursor(
                RunCursor(started_at=last.run_at, run_id=last.run_id, customer_id=last.customer_id)
            )
        return DebtRevisionListPage(
            latest_run=latest, items=tuple(items), next_cursor=next_cursor, has_more=has_more
        )
