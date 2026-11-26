"""Customer debt-history use case and HTTP contract (fake repository, real use case)."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from config.container import container
from main import create_app
from src.modules.analytics.application.use_cases.customer_debt_history_use_case import (
    CustomerDebtHistoryUseCase,
    decode_entry_cursor,
    decode_run_cursor,
    encode_entry_cursor,
    encode_run_cursor,
)
from src.modules.analytics.domain.errors import (
    CustomerNotFoundError,
    DebtLedgerTooLargeError,
    InvalidDebtHistoryCursorError,
)
from src.modules.analytics.domain.models.customer_debt_history import (
    MAX_LEDGER_ENTRIES,
    CustomerDebtProfile,
    CustomerDebtRevisionItem,
    DebtHistoryEntry,
    DebtHistoryEntryCursor,
    DebtHistoryFilters,
    DebtLedgerEntry,
    DebtRevisionChangeItem,
    DebtRevisionListItem,
    DebtRevisionSummary,
    LatestSyncRun,
    RunCursor,
)
from src.modules.auth.presentation.router import get_current_user

CUSTOMER = "11111111-1111-4111-8111-111111111111"
RUN_AT = datetime(2026, 11, 18, 15, 5, tzinfo=timezone.utc)
D = Decimal


def ledger(when, amount, kind="sale", source_id="S"):
    return DebtLedgerEntry(
        entry_id=f"id-{source_id}", occurred_at=datetime.fromisoformat(when),
        source_type=kind, source_id=source_id, amount=D(str(amount)),
    )


class FakeRepository:
    def __init__(self, *, exists=True, entries=None):
        self.exists = exists
        self.entries = entries if entries is not None else [
            ledger("2026-01-10 08:00", 100, "sale", "S1"),
            ledger("2026-06-01 08:00", -40, "receipt", "R1"),
            ledger("2026-11-01 08:00", 30, "sale", "S2"),
        ]
        self.calls = []

    async def get_customer_profile(self, customer_id):
        self.calls.append(("profile", customer_id))
        if not self.exists:
            return None
        return CustomerDebtProfile(customer_id, "Anh An", "Nhà 1", "Xóm 1", "Xã A")

    async def list_ledger_entries(self, customer_id, until, limit):
        self.calls.append(("ledger", until, limit))
        return [entry for entry in self.entries if entry.occurred_at < until][:limit]

    async def get_current_balance(self, customer_id):
        return sum((entry.amount for entry in self.entries), D(0))

    async def get_revision_summary(self, customer_id):
        return DebtRevisionSummary(1, RUN_AT, D("50.00"))

    async def list_entry_page(self, customer_id, filters, cursor, limit):
        self.calls.append(("entries", filters, cursor, limit))
        entry = DebtHistoryEntry(
            entry_id="id-S2", occurred_at=datetime(2026, 11, 1, 8), source_type="sale",
            source_id="S2", voucher_number="XB0002", invoice_id="inv-2", return_id=None,
            amount=D("30.00"), balance_after=D("90.00"), revised=True, last_revised_at=RUN_AT,
        )
        position = DebtHistoryEntryCursor(entry.occurred_at, 1, "S2")
        return [(entry, position)], True

    async def list_customer_revisions(self, customer_id, cursor, limit, max_changes):
        self.calls.append(("revisions", cursor, limit, max_changes))
        change = DebtRevisionChangeItem(
            change_type="updated", source_type="sale", source_id="S1", voucher_number="XB0001",
            customer_id=customer_id, previous_customer_id=None,
            old_occurred_at=datetime(2026, 1, 10, 8), new_occurred_at=datetime(2026, 1, 10, 8),
            old_amount=D("50.00"), new_amount=D("100.00"), balance_delta=D("50.00"),
        )
        item = CustomerDebtRevisionItem(
            run_id="run-1", run_at=RUN_AT, entrypoint="etl_job", balance_before=D("40.00"),
            balance_after=D("90.00"), balance_delta=D("50.00"),
            earliest_affected_at=datetime(2026, 1, 10, 8), change_count=1,
            changes=(change,), has_more_changes=False,
        )
        return [item], False

    async def list_debt_revisions(self, filters, cursor, limit):
        self.calls.append(("all-revisions", filters, cursor, limit))
        item = DebtRevisionListItem(
            run_id="run-1", run_at=RUN_AT, customer_id=CUSTOMER, customer_name="Anh An",
            ward_name="Xã A", village_name="Xóm 1", balance_before=D("40.00"),
            balance_after=D("90.00"), balance_delta=D("50.00"),
            earliest_affected_at=datetime(2026, 1, 10, 8), change_count=1,
        )
        latest = LatestSyncRun("run-1", RUN_AT, "etl_job", False, 1, D("50.00"))
        return latest, [item], True


# --- use case -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_combines_summary_series_aging_and_revisions():
    repository = FakeRepository()
    use_case = CustomerDebtHistoryUseCase(repository)

    history = await use_case.get_history(
        CUSTOMER, DebtHistoryFilters(date_from=date(2026, 9, 1), date_to=date(2026, 11, 19))
    )

    assert repository.calls[1] == ("ledger", datetime(2026, 11, 20), MAX_LEDGER_ENTRIES + 1)
    s = history.summary
    assert (s.opening_balance, s.closing_balance, s.increase_amount) == (D(60), D(90), D(30))
    assert s.debt_since == date(2026, 1, 10) and s.days_in_debt == 313
    assert s.revision_count == 1 and s.last_revision_delta == D("50.00")
    assert [p.closing_balance for p in history.series] == [D(60), D(60), D(90)]
    assert sum(b.amount for b in history.aging) == D(90)


@pytest.mark.asyncio
async def test_unknown_customer_is_not_found_and_huge_ledger_is_refused():
    with pytest.raises(CustomerNotFoundError):
        await CustomerDebtHistoryUseCase(FakeRepository(exists=False)).get_history(
            CUSTOMER, DebtHistoryFilters(date_to=date(2026, 11, 19))
        )
    huge = FakeRepository(entries=[ledger("2026-01-01 08:00", 1, source_id=str(i)) for i in range(3)])
    import src.modules.analytics.application.use_cases.customer_debt_history_use_case as module
    original = module.MAX_LEDGER_ENTRIES
    module.MAX_LEDGER_ENTRIES = 2
    try:
        with pytest.raises(DebtLedgerTooLargeError):
            await CustomerDebtHistoryUseCase(huge).get_history(
                CUSTOMER, DebtHistoryFilters(date_to=date(2026, 11, 19))
            )
    finally:
        module.MAX_LEDGER_ENTRIES = original


def test_cursors_round_trip_and_reject_tampering():
    entry = DebtHistoryEntryCursor(datetime(2026, 11, 1, 8, 30), 3, "R-1")
    assert decode_entry_cursor(encode_entry_cursor(entry)) == entry
    run = RunCursor(RUN_AT, "run-1", CUSTOMER)
    assert decode_run_cursor(encode_run_cursor(run), with_customer=True) == run
    for bad in ("not-base64!", encode_run_cursor(run)):
        with pytest.raises(InvalidDebtHistoryCursorError):
            decode_entry_cursor(bad)
    with pytest.raises(InvalidDebtHistoryCursorError):
        decode_run_cursor(encode_run_cursor(run), with_customer=False)


# --- HTTP -----------------------------------------------------------------------

@pytest.fixture
def api():
    repository = FakeRepository()
    container.customer_debt_history_use_case.override(
        providers.Object(CustomerDebtHistoryUseCase(repository))
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": "staff-id", "role": "staff"}
    try:
        yield TestClient(app), repository, app
    finally:
        container.customer_debt_history_use_case.reset_override()


def test_history_contract(api):
    client, _, _ = api
    response = client.get(
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-history",
        params={"date_from": "2026-09-01", "date_to": "2026-11-19", "grain": "month"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["customer"]["customer_name"] == "Anh An"
    assert isinstance(body["summary"]["closing_balance"], str)  # exact decimal, never a float
    assert Decimal(body["summary"]["closing_balance"]) == D(90)
    assert body["summary"]["status"] == "in_debt"
    assert [b["bucket"] for b in body["aging"]] == ["le_3m", "3m_6m", "6m_1y", "1y_2y", "2y_3y", "over_3y"]
    assert body["series"][0]["period_start"] == "2026-09-01"
    assert body["grain"] == "month" and body["date_to"] == "2026-11-19"


def test_history_defaults_to_yesterday_and_validates_input(api):
    client, repository, _ = api
    assert client.get(f"/api/v1/analytics/customers/{CUSTOMER}/debt-history").status_code == 200
    reversed_range = client.get(
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-history",
        params={"date_from": "2026-02-01", "date_to": "2026-01-01"},
    )
    assert reversed_range.status_code == 422
    too_many = client.get(
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-history",
        params={"date_from": "2020-01-01", "date_to": "2026-01-01", "grain": "day"},
    )
    assert too_many.status_code == 422
    assert client.get("/api/v1/analytics/customers/not-a-uuid/debt-history").status_code == 422


def test_unknown_customer_is_404(api):
    client, repository, _ = api
    repository.exists = False
    for path in ("debt-history", "debt-history/entries", "debt-revisions"):
        response = client.get(f"/api/v1/analytics/customers/{CUSTOMER}/{path}")
        assert response.status_code == 404, path
        assert response.json()["detail"] == "Customer not found"


def test_entries_contract_and_cursor(api):
    client, repository, _ = api
    response = client.get(
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-history/entries",
        params=[("date_from", "2026-01-01"), ("source_type", "sale"), ("source_type", "receipt"),
                ("source_type", "sale"), ("limit", "1")],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is True and body["next_cursor"]
    item = body["items"][0]
    assert item["voucher_number"] == "XB0002" and item["invoice_id"] == "inv-2"
    assert item["revised"] is True
    _, filters, cursor, limit = repository.calls[-1]
    assert filters.source_types == ("sale", "receipt") and cursor is None and limit == 1

    follow = client.get(
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-history/entries",
        params={"cursor": body["next_cursor"]},
    )
    assert follow.status_code == 200
    assert repository.calls[-1][2] == DebtHistoryEntryCursor(datetime(2026, 11, 1, 8), 1, "S2")

    assert client.get(
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-history/entries", params={"cursor": "garbage"}
    ).status_code == 422
    assert client.get(
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-history/entries", params={"source_type": "bogus"}
    ).status_code == 422


def test_revision_contracts(api):
    client, repository, _ = api
    customer = client.get(f"/api/v1/analytics/customers/{CUSTOMER}/debt-revisions")
    assert customer.status_code == 200
    item = customer.json()["items"][0]
    assert item["changes"][0]["voucher_number"] == "XB0001"
    assert item["entrypoint"] == "etl_job" and customer.json()["next_cursor"] is None

    everything = client.get("/api/v1/analytics/debt-revisions", params={"ward": "Xã A"})
    assert everything.status_code == 200
    body = everything.json()
    assert body["latest_run"]["revised_customers"] == 1
    assert body["items"][0]["customer_name"] == "Anh An" and body["has_more"] is True
    assert decode_run_cursor(body["next_cursor"], with_customer=True).customer_id == CUSTOMER
    assert repository.calls[-1][1].ward_names == ("Xã A",)


def test_debt_history_routes_reject_guests(api):
    client, _, app = api
    app.dependency_overrides[get_current_user] = lambda: {"id": "guest-id", "role": "guest"}
    for path in (
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-history",
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-history/entries",
        f"/api/v1/analytics/customers/{CUSTOMER}/debt-revisions",
        "/api/v1/analytics/debt-revisions",
    ):
        assert client.get(path).status_code == 403, path
