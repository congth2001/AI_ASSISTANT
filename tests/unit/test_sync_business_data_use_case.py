from decimal import Decimal

from contextlib import asynccontextmanager

import pandas as pd
import pytest

from src.common.errors import ConfigurationError, ValidationError
from src.modules.sales.domain.errors import (
    DuplicateSalesReturnNumbersError,
    EmptySnapshotError,
    InvalidDatetimeValueError,
    InvalidDebtSourceTypeError,
    InvalidDecimalValueError,
    MissingSnapshotColumnsError,
    SnapshotShrinkError,
)
from src.modules.sales.application.use_cases.sync_business_data_use_case import (
    SyncBusinessDataUseCase,
)


class FakeCustomerRepository:
    def __init__(self):
        self.rows = {}

    async def upsert_many(self, rows):
        for row in rows:
            key = row["customer_identity_key"]
            customer_id = self.rows.get(key, {}).get(
                "customer_id", f"customer-{len(self.rows) + 1}"
            )
            self.rows[key] = {**row, "customer_id": customer_id}
        return {key: row["customer_id"] for key, row in self.rows.items()}

    async def soft_delete_unreferenced(self):
        return 0


class FakeSalesInvoiceRepository:
    def __init__(self):
        self.rows = {}

    async def upsert_many(self, rows):
        synced_numbers = []
        for row in rows:
            number = row["invoice_number"]
            synced_numbers.append(number)
            invoice_id = self.rows.get(number, {}).get(
                "invoice_id", f"invoice-{len(self.rows) + 1}"
            )
            self.rows[number] = {**row, "invoice_id": invoice_id}
        return {
            number: self.rows[number]["invoice_id"] for number in synced_numbers
        }

    async def soft_delete_missing(self, invoice_numbers):
        expected = set(invoice_numbers)
        missing = set(self.rows) - expected
        for number in missing:
            del self.rows[number]
        return len(missing)

    async def count_active(self):
        return len(self.rows)

    async def get_id_map_by_invoice_numbers(self, invoice_numbers):
        return {
            number: self.rows[number]["invoice_id"]
            for number in invoice_numbers
            if number in self.rows
        }


class FakeSalesInvoiceLineRepository:
    def __init__(self):
        self.rows = {}
        self.target_invoice_ids = []

    async def upsert_snapshot(self, rows, invoice_ids):
        self.target_invoice_ids = invoice_ids
        target_ids = set(invoice_ids)
        self.rows = {
            key: row for key, row in self.rows.items() if key[0] not in target_ids
        }
        for row in rows:
            self.rows[(row["invoice_id"], row["line_number"])] = row
        return len(rows)


class FakeDebtTransactionRepository:
    def __init__(self):
        self.rows = []

    async def sync_snapshot(self, rows):
        self.rows = rows
        return {"synced": len(rows), "deleted": 0}

    async def count_active(self):
        return len(self.rows)


class FakeSalesReturnRepository:
    def __init__(self):
        self.returns = []
        self.lines = []

    async def sync_snapshot(self, returns, lines):
        self.returns = returns
        self.lines = lines
        return {"returns": len(returns), "lines": len(lines)}

    async def count_active(self):
        return len(self.returns)


def build_use_case():
    customers = FakeCustomerRepository()
    invoices = FakeSalesInvoiceRepository()
    lines = FakeSalesInvoiceLineRepository()
    use_case = SyncBusinessDataUseCase(customers, invoices, lines)
    return use_case, customers, invoices, lines


def customer_snapshot():
    return pd.DataFrame(
        [
            {
                "issued_at": "2025-01-01 08:00:00",
                "invoice_number": "PX-001",
                "customer_name": " Anh Tiệc ",
                "address_detail": "Nhà 1",
                "village_name": " Xóm 3 ",
                "ward_name": "Thụy Hưng",
                "invoice_total_amount": 120_000,
                "debt_delta_amount": 20_000,
            },
            {
                "issued_at": "2025-01-02 09:00:00",
                "invoice_number": "PX-002",
                "customer_name": "ANH  TIỆC",
                "address_detail": "Nhà 1 mới",
                "village_name": "Xóm 3",
                "ward_name": "Thụy Hưng",
                "invoice_total_amount": 80_000,
                "debt_delta_amount": 0,
            },
        ]
    )


def line_snapshot():
    return pd.DataFrame(
        [
            {
                "invoice_number": "PX-001",
                "product_name": "xi măng",
                "product_category_name": "Xi măng",
                "unit_name": " Bao ",
                "unit_price": 60_000,
                "quantity": 1,
                "line_amount": 60_000,
            },
            {
                "invoice_number": "PX-001",
                "product_name": "xi măng",
                "product_category_name": "Xi măng",
                "unit_name": "Bao",
                "unit_price": 60_000,
                "quantity": 1,
                "line_amount": 60_000,
            },
            {
                "invoice_number": "PX-002",
                "product_name": "gạch",
                "product_category_name": "Gạch",
                "unit_name": "M2",
                "unit_price": 80_000,
                "quantity": 1,
                "line_amount": 80_000,
            },
        ]
    )


@pytest.mark.asyncio
async def test_sync_all_is_idempotent_and_assigns_line_numbers():
    use_case, customers, invoices, lines = build_use_case()

    first = await use_case.sync_all(customer_snapshot(), line_snapshot())
    second = await use_case.sync_all(customer_snapshot(), line_snapshot())

    assert first == {
        "customers": 1,
        "invoices": 2,
        "invoices_deleted": 0,
        "lines": 3,
        "line_invoices": 2,
    }
    assert second == first
    assert len(customers.rows) == 1
    assert len(invoices.rows) == 2
    assert len(lines.rows) == 3

    invoice_one_id = invoices.rows["PX-001"]["invoice_id"]
    invoice_one_lines = [
        row
        for (invoice_id, _), row in lines.rows.items()
        if invoice_id == invoice_one_id
    ]
    assert [row["line_number"] for row in invoice_one_lines] == [1, 2]
    assert invoice_one_lines[0]["unit_name"] == "Bao"
    assert invoice_one_lines[0]["unit_price"] == Decimal("60000")


@pytest.mark.asyncio
async def test_sync_soft_deletes_invoice_missing_from_source_snapshot():
    use_case, _, invoices, _ = build_use_case()
    await use_case.sync_all(customer_snapshot(), line_snapshot())

    reduced_customers = customer_snapshot().iloc[[0]].copy()
    all_lines = line_snapshot()
    reduced_lines = all_lines.loc[all_lines.iloc[:, 0] == "PX-001"].copy()
    result = await use_case.sync_all(reduced_customers, reduced_lines, allow_shrink=True)

    assert result["invoices_deleted"] == 1
    assert set(invoices.rows) == {"PX-001"}


@pytest.mark.asyncio
async def test_customer_master_uses_latest_invoice_snapshot():
    use_case, customers, _, _ = build_use_case()

    await use_case.sync_all(customer_snapshot(), line_snapshot())

    customer = next(iter(customers.rows.values()))
    assert customer["customer_name"] == "ANH TIỆC"
    assert customer["address_detail"] == "Nhà 1 mới"


@pytest.mark.asyncio
async def test_sync_rejects_goods_for_unknown_invoice():
    use_case, _, _, _ = build_use_case()
    goods = line_snapshot().copy()
    goods.loc[0, "invoice_number"] = "PX-UNKNOWN"

    with pytest.raises(ValueError, match="do not exist"):
        await use_case.sync_all(customer_snapshot(), goods)


@pytest.mark.asyncio
async def test_sync_rejects_duplicate_invoice_numbers():
    use_case, _, _, _ = build_use_case()
    customers = customer_snapshot()
    customers.loc[1, "invoice_number"] = "PX-001"

    with pytest.raises(ValueError, match="duplicate invoice numbers"):
        await use_case.sync_all(customers, line_snapshot())


@pytest.mark.asyncio
async def test_sync_persists_signed_debt_ledger():
    customers = FakeCustomerRepository()
    invoices = FakeSalesInvoiceRepository()
    lines = FakeSalesInvoiceLineRepository()
    debts = FakeDebtTransactionRepository()
    use_case = SyncBusinessDataUseCase(customers, invoices, lines, debts)
    debt_snapshot = pd.DataFrame(
        [
            {
                "source_type": "sale",
                "source_id": "1",
                "occurred_at": "2025-01-01",
                "customer_name": "Anh Tiệc",
                "address_detail": "Nhà 1",
                "village_name": "Xóm 3",
                "ward_name": "Thụy Hưng",
                "amount": 100,
            },
            {
                "source_type": "receipt",
                "source_id": "2",
                "occurred_at": "2025-01-02",
                "customer_name": "Anh Tiệc",
                "address_detail": "Nhà 1",
                "village_name": "Xóm 3",
                "ward_name": "Thụy Hưng",
                "amount": -40,
            },
        ]
    )

    result = await use_case.sync_all(
        customer_snapshot(), line_snapshot(), debt_snapshot
    )

    assert result["debt_transactions"] == {"synced": 2, "deleted": 0}
    assert result["customers_deleted"] == 0
    assert [row["amount"] for row in debts.rows] == [Decimal("100"), Decimal("-40")]
    assert debts.rows[0]["customer_id"] == debts.rows[1]["customer_id"]


@pytest.mark.asyncio
async def test_sync_persists_sales_return_headers_and_product_lines():
    customers = FakeCustomerRepository()
    returns = FakeSalesReturnRepository()
    use_case = SyncBusinessDataUseCase(
        customers,
        FakeSalesInvoiceRepository(),
        FakeSalesInvoiceLineRepository(),
        sales_return_repository=returns,
    )
    return_snapshot = pd.DataFrame([
        {
            "source_id": "8", "return_number": "NT8-0919",
            "occurred_at": "2025-03-10", "return_total_amount": 150,
            "customer_name": "Anh Tiệc", "address_detail": "Nhà 1",
            "village_name": "Xóm 3", "ward_name": "Thụy Hưng",
        }
    ])
    return_lines = pd.DataFrame([
        {
            "source_id": "8",
            "source_line_id": "5", "product_name": "gạch",
            "product_category_name": "Gạch", "unit_name": "viên",
            "unit_price": 15, "quantity": 10, "line_amount": 150,
        }
    ])

    result = await use_case.sync_all(
        customer_snapshot(), line_snapshot(), returns_df=return_snapshot,
        return_lines_df=return_lines,
    )

    assert result["sales_returns"] == {"returns": 1, "lines": 1}
    assert returns.returns[0]["return_number"] == "NT8-0919"
    assert returns.lines[0]["quantity"] == Decimal("10")
    assert returns.lines[0]["line_amount"] == Decimal("150")


# ---------------------------------------------------------------------------
# Snapshot guard
# ---------------------------------------------------------------------------


def many_invoices(count):
    return pd.DataFrame(
        [
            {
                "issued_at": "2025-01-01 08:00:00",
                "invoice_number": f"PX-{i:03d}",
                "customer_name": "Anh An",
                "address_detail": None,
                "village_name": None,
                "ward_name": None,
                "invoice_total_amount": 10,
                "debt_delta_amount": 0,
            }
            for i in range(count)
        ],
        columns=[
            "issued_at", "invoice_number", "customer_name", "address_detail",
            "village_name", "ward_name", "invoice_total_amount", "debt_delta_amount",
        ],
    )


def many_lines(count):
    return pd.DataFrame(
        [
            {
                "invoice_number": f"PX-{i:03d}",
                "product_name": "gạch",
                "product_category_name": "Gạch",
                "unit_name": "Viên",
                "unit_price": 10,
                "quantity": 1,
                "line_amount": 10,
            }
            for i in range(count)
        ],
        columns=[
            "invoice_number", "product_name", "product_category_name", "unit_name",
            "unit_price", "quantity", "line_amount",
        ],
    )


@pytest.mark.asyncio
async def test_sync_refuses_empty_invoice_snapshot_when_data_is_active():
    use_case, _, invoices, _ = build_use_case()
    await use_case.sync_all(many_invoices(5), many_lines(5))

    with pytest.raises(EmptySnapshotError, match="empty"):
        await use_case.sync_all(many_invoices(0), many_lines(0))

    assert len(invoices.rows) == 5


@pytest.mark.asyncio
async def test_sync_refuses_snapshot_that_shrinks_beyond_threshold():
    use_case, _, invoices, _ = build_use_case()
    await use_case.sync_all(many_invoices(10), many_lines(10))

    with pytest.raises(SnapshotShrinkError, match="10 active"):
        await use_case.sync_all(many_invoices(6), many_lines(6))  # -40%

    assert len(invoices.rows) == 10


@pytest.mark.asyncio
async def test_sync_accepts_snapshot_within_shrink_threshold():
    use_case, _, invoices, _ = build_use_case()
    await use_case.sync_all(many_invoices(10), many_lines(10))

    result = await use_case.sync_all(many_invoices(8), many_lines(8))  # -20%

    assert result["invoices_deleted"] == 2
    assert len(invoices.rows) == 8


@pytest.mark.asyncio
async def test_allow_shrink_overrides_the_guard():
    use_case, _, invoices, _ = build_use_case()
    await use_case.sync_all(many_invoices(10), many_lines(10))

    result = await use_case.sync_all(many_invoices(0), many_lines(0), allow_shrink=True)

    assert result["invoices_deleted"] == 10
    assert invoices.rows == {}


@pytest.mark.asyncio
async def test_empty_snapshot_is_fine_when_nothing_is_active():
    use_case, _, _, _ = build_use_case()

    result = await use_case.sync_all(many_invoices(0), many_lines(0))

    assert result["invoices"] == 0


@pytest.mark.asyncio
async def test_guard_also_covers_debt_and_return_snapshots():
    debts = FakeDebtTransactionRepository()
    returns = FakeSalesReturnRepository()
    use_case = SyncBusinessDataUseCase(
        FakeCustomerRepository(),
        FakeSalesInvoiceRepository(),
        FakeSalesInvoiceLineRepository(),
        debts,
        returns,
    )
    debt_columns = ["source_type", "source_id", "occurred_at", "customer_name", "amount"]
    debt_rows = pd.DataFrame(
        [["sale", str(i), "2025-01-01", "Anh An", 1] for i in range(4)],
        columns=debt_columns,
    )
    return_rows = pd.DataFrame(
        [
            {
                "source_id": str(i), "return_number": f"NT-{i}",
                "occurred_at": "2025-01-01", "return_total_amount": 1,
                "customer_name": "Anh An",
            }
            for i in range(4)
        ]
    )
    return_lines = pd.DataFrame(
        columns=[
            "source_id", "source_line_id", "product_name", "unit_name",
            "unit_price", "quantity", "line_amount",
        ]
    )
    await use_case.sync_all(many_invoices(2), many_lines(2), debt_rows, return_rows, return_lines)

    with pytest.raises(EmptySnapshotError, match="debt transactions"):
        await use_case.sync_all(
            many_invoices(2), many_lines(2), debt_rows.iloc[0:0], return_rows, return_lines
        )
    with pytest.raises(SnapshotShrinkError, match="sales returns"):
        await use_case.sync_all(
            many_invoices(2), many_lines(2), debt_rows, return_rows.iloc[:2], return_lines
        )
    assert len(debts.rows) == 4 and len(returns.returns) == 4


# ---------------------------------------------------------------------------
# Atomicity: validate everything first, write inside one transaction
# ---------------------------------------------------------------------------


class RecordingUnitOfWork:
    def __init__(self):
        self.events = []

    @asynccontextmanager
    async def transaction(self):
        self.events.append("begin")
        try:
            yield
        except BaseException:
            self.events.append("rollback")
            raise
        self.events.append("commit")


@pytest.mark.asyncio
async def test_sync_all_runs_all_writes_in_one_transaction():
    uow = RecordingUnitOfWork()
    use_case = SyncBusinessDataUseCase(
        FakeCustomerRepository(),
        FakeSalesInvoiceRepository(),
        FakeSalesInvoiceLineRepository(),
        unit_of_work=uow,
    )

    await use_case.sync_all(customer_snapshot(), line_snapshot())

    assert uow.events == ["begin", "commit"]


@pytest.mark.asyncio
async def test_failed_write_rolls_back_the_unit_of_work():
    class ExplodingLines(FakeSalesInvoiceLineRepository):
        async def upsert_snapshot(self, rows, invoice_ids):
            raise RuntimeError("database unavailable")

    uow = RecordingUnitOfWork()
    use_case = SyncBusinessDataUseCase(
        FakeCustomerRepository(),
        FakeSalesInvoiceRepository(),
        ExplodingLines(),
        unit_of_work=uow,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await use_case.sync_all(customer_snapshot(), line_snapshot())

    assert uow.events == ["begin", "rollback"]


@pytest.mark.asyncio
async def test_invalid_later_snapshot_is_rejected_before_any_write():
    customers = FakeCustomerRepository()
    invoices = FakeSalesInvoiceRepository()
    uow = RecordingUnitOfWork()
    use_case = SyncBusinessDataUseCase(
        customers,
        invoices,
        FakeSalesInvoiceLineRepository(),
        FakeDebtTransactionRepository(),
        unit_of_work=uow,
    )
    bad_debt = pd.DataFrame(
        [{"source_type": "sale", "source_id": "1", "occurred_at": "2025-01-01",
          "customer_name": "Anh An", "amount": float("inf")}]
    )

    with pytest.raises(InvalidDecimalValueError):
        await use_case.sync_all(customer_snapshot(), line_snapshot(), bad_debt)

    assert uow.events == []
    assert customers.rows == {} and invoices.rows == {}


@pytest.mark.asyncio
async def test_missing_repository_is_reported_before_any_write():
    use_case, customers, invoices, _ = build_use_case()
    debt = pd.DataFrame(columns=["source_type", "source_id", "occurred_at", "customer_name", "amount"])

    with pytest.raises(ConfigurationError, match="debt transaction repository"):
        await use_case.sync_all(customer_snapshot(), line_snapshot(), debt)

    assert invoices.rows == {} and customers.rows == {}


# ---------------------------------------------------------------------------
# Value conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), "abc", "1e40"])
def test_decimal_rejects_non_finite_or_out_of_range_values(bad):
    with pytest.raises(InvalidDecimalValueError):
        SyncBusinessDataUseCase._decimal(bad, "amount")


@pytest.mark.parametrize(
    ("value", "scale", "expected"),
    [
        (0.1, 2, Decimal("0.10")),
        (0.1 + 0.2, 2, Decimal("0.30")),  # binary float artifact
        ("2.005", 2, Decimal("2.01")),  # ROUND_HALF_UP, not banker's rounding
        (2.675, 2, Decimal("2.68")),
        (-2.005, 2, Decimal("-2.01")),
        (1.2345, 3, Decimal("1.235")),
        (7, 3, Decimal("7.000")),
    ],
)
def test_decimal_quantizes_to_column_scale_half_up(value, scale, expected):
    result = SyncBusinessDataUseCase._decimal(value, "amount", scale)
    assert result == expected
    assert result.as_tuple().exponent == -scale


def test_decimal_rejects_missing_value():
    with pytest.raises(ValidationError):
        SyncBusinessDataUseCase._decimal(float("nan"), "amount")


@pytest.mark.asyncio
async def test_sync_rejects_invalid_issue_date():
    use_case, _, invoices, _ = build_use_case()
    customers = customer_snapshot()
    customers.loc[0, "issued_at"] = "not a date"

    with pytest.raises(InvalidDatetimeValueError):
        await use_case.sync_all(customers, line_snapshot())
    assert invoices.rows == {}


@pytest.mark.asyncio
async def test_sync_persists_money_rounded_to_cents():
    use_case, _, invoices, _ = build_use_case()
    customers = customer_snapshot()
    customers["invoice_total_amount"] = [100.005, 80.1 + 0.2]

    await use_case.sync_all(customers, line_snapshot())

    assert invoices.rows["PX-001"]["invoice_total_amount"] == Decimal("100.01")
    assert invoices.rows["PX-002"]["invoice_total_amount"] == Decimal("80.30")


# ---------------------------------------------------------------------------
# Snapshot shape: required/optional columns
# ---------------------------------------------------------------------------


def return_use_case():
    returns = FakeSalesReturnRepository()
    use_case = SyncBusinessDataUseCase(
        FakeCustomerRepository(),
        FakeSalesInvoiceRepository(),
        FakeSalesInvoiceLineRepository(),
        sales_return_repository=returns,
    )
    return use_case, returns


def minimal_return_headers():
    return pd.DataFrame(
        [{
            "source_id": "8", "return_number": "NT8-0919",
            "occurred_at": "2025-03-10", "return_total_amount": 150,
            "customer_name": "Anh Tiệc",
        }]
    )


def return_line_frame():
    return pd.DataFrame(
        [{
            "source_id": "8", "source_line_id": "5", "product_name": "gạch",
            "unit_name": "viên", "unit_price": 15, "quantity": 10, "line_amount": 150,
        }]
    )


@pytest.mark.asyncio
async def test_return_headers_without_address_columns_do_not_raise_key_error():
    use_case, returns = return_use_case()

    result = await use_case.sync_all(
        customer_snapshot(), line_snapshot(),
        returns_df=minimal_return_headers(), return_lines_df=return_line_frame(),
    )

    assert result["sales_returns"] == {"returns": 1, "lines": 1}
    assert returns.returns[0]["customer_address_detail_snapshot"] is None
    assert returns.returns[0]["customer_ward_name_snapshot"] is None


@pytest.mark.asyncio
async def test_return_headers_missing_required_column_is_a_domain_error():
    use_case, _ = return_use_case()
    headers = minimal_return_headers().drop(columns=["return_total_amount"])

    with pytest.raises(MissingSnapshotColumnsError, match="return_total_amount"):
        await use_case.sync_all(
            customer_snapshot(), line_snapshot(),
            returns_df=headers, return_lines_df=return_line_frame(),
        )


@pytest.mark.asyncio
async def test_return_headers_reject_duplicate_return_numbers():
    use_case, _ = return_use_case()
    headers = pd.concat(
        [minimal_return_headers(), minimal_return_headers().assign(source_id="9")],
        ignore_index=True,
    )

    with pytest.raises(DuplicateSalesReturnNumbersError, match="NT8-0919"):
        await use_case.sync_all(
            customer_snapshot(), line_snapshot(),
            returns_df=headers, return_lines_df=return_line_frame(),
        )


@pytest.mark.asyncio
async def test_debt_rejects_unknown_source_type():
    debts = FakeDebtTransactionRepository()
    use_case = SyncBusinessDataUseCase(
        FakeCustomerRepository(), FakeSalesInvoiceRepository(),
        FakeSalesInvoiceLineRepository(), debts,
    )
    frame = pd.DataFrame(
        [{"source_type": "refund", "source_id": "1", "occurred_at": "2025-01-01",
          "customer_name": "Anh An", "amount": 1}]
    )

    with pytest.raises(InvalidDebtSourceTypeError):
        await use_case.sync_all(customer_snapshot(), line_snapshot(), frame)


@pytest.mark.asyncio
async def test_legacy_vietnamese_headers_are_not_accepted_by_the_use_case():
    use_case, _, _, _ = build_use_case()
    legacy = customer_snapshot().rename(columns={"invoice_number": "Số phiếu"})

    with pytest.raises(MissingSnapshotColumnsError, match="invoice_number"):
        await use_case.sync_all(legacy, line_snapshot())


# ---------------------------------------------------------------------------
# Customer profile precedence
# ---------------------------------------------------------------------------


def debt_frame(address, occurred_at="2030-01-01"):
    return pd.DataFrame(
        [{
            "source_type": "sale", "source_id": "1", "occurred_at": occurred_at,
            "customer_name": "ANH TIỆC", "address_detail": address,
            "village_name": "Xóm 3", "ward_name": "Thụy Hưng", "amount": 5,
        }]
    )


@pytest.mark.asyncio
async def test_invoices_decide_customer_profile_over_later_debt_rows():
    customers = FakeCustomerRepository()
    use_case = SyncBusinessDataUseCase(
        customers, FakeSalesInvoiceRepository(), FakeSalesInvoiceLineRepository(),
        FakeDebtTransactionRepository(),
    )

    await use_case.sync_all(customer_snapshot(), line_snapshot(), debt_frame("Địa chỉ ledger"))

    customer = next(iter(customers.rows.values()))
    assert customer["address_detail"] == "Nhà 1 mới"  # newest invoice, not newer ledger row


@pytest.mark.asyncio
async def test_debt_only_customer_uses_latest_ledger_profile_regardless_of_row_order():
    customers = FakeCustomerRepository()
    use_case = SyncBusinessDataUseCase(
        customers, FakeSalesInvoiceRepository(), FakeSalesInvoiceLineRepository(),
        FakeDebtTransactionRepository(),
    )
    ledger = pd.DataFrame(
        [
            {"source_type": "receipt", "source_id": "2", "occurred_at": "2025-06-01",
             "customer_name": "Chị Lan", "address_detail": "Mới", "village_name": "Xóm 1",
             "ward_name": "Xã A", "amount": -1},
            {"source_type": "sale", "source_id": "1", "occurred_at": "2025-01-01",
             "customer_name": "Chị Lan", "address_detail": "Cũ", "village_name": "Xóm 1",
             "ward_name": "Xã A", "amount": 1},
        ]
    )

    await use_case.sync_all(customer_snapshot(), line_snapshot(), ledger)

    lan = customers.rows["chị lan|xã a|xóm 1"]
    assert lan["address_detail"] == "Mới"
