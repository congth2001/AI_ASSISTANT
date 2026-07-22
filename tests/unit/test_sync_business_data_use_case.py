from decimal import Decimal

import pandas as pd
import pytest

from src.application.use_cases.sync_business_data_use_case import (
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


class FakeSalesInvoiceRepository:
    def __init__(self):
        self.rows = {}

    async def upsert_many(self, rows):
        for row in rows:
            number = row["invoice_number"]
            invoice_id = self.rows.get(number, {}).get(
                "invoice_id", f"invoice-{len(self.rows) + 1}"
            )
            self.rows[number] = {**row, "invoice_id": invoice_id}
        return {number: row["invoice_id"] for number, row in self.rows.items()}

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
                "Ngày": "2025-01-01 08:00:00",
                "Số phiếu": "PX-001",
                "Khách hàng": " Anh Tiệc ",
                "Địa chỉ": "Nhà 1",
                "Xóm": " Xóm 3 ",
                "Xã": "Thụy Hưng",
                "Tổng tiền": 120_000,
                "Ghi nợ": 20_000,
            },
            {
                "Ngày": "2025-01-02 09:00:00",
                "Số phiếu": "PX-002",
                "Khách hàng": "ANH  TIỆC",
                "Địa chỉ": "Nhà 1 mới",
                "Xóm": "Xóm 3",
                "Xã": "Thụy Hưng",
                "Tổng tiền": 80_000,
                "Ghi nợ": 0,
            },
        ]
    )


def line_snapshot():
    return pd.DataFrame(
        [
            {
                "Số phiếu": "PX-001",
                "Tên hàng chuẩn hóa": "xi măng",
                "Loại mặt hàng": "Xi măng",
                "ĐVT": " Bao ",
                "Đơn giá": 60_000,
                "Số lượng": 1,
                "Thành tiền": 60_000,
            },
            {
                "Số phiếu": "PX-001",
                "Tên hàng chuẩn hóa": "xi măng",
                "Loại mặt hàng": "Xi măng",
                "ĐVT": "Bao",
                "Đơn giá": 60_000,
                "Số lượng": 1,
                "Thành tiền": 60_000,
            },
            {
                "Số phiếu": "PX-002",
                "Tên hàng chuẩn hóa": "gạch",
                "Loại mặt hàng": "Gạch",
                "ĐVT": "M2",
                "Đơn giá": 80_000,
                "Số lượng": 1,
                "Thành tiền": 80_000,
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
    goods.loc[0, "Số phiếu"] = "PX-UNKNOWN"

    with pytest.raises(ValueError, match="do not exist"):
        await use_case.sync_all(customer_snapshot(), goods)


@pytest.mark.asyncio
async def test_sync_rejects_duplicate_invoice_numbers():
    use_case, _, _, _ = build_use_case()
    customers = customer_snapshot()
    customers.loc[1, "Số phiếu"] = "PX-001"

    with pytest.raises(ValueError, match="duplicate invoice numbers"):
        await use_case.sync_all(customers, line_snapshot())
