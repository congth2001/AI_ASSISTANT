"""Read-boundary mapping between Excel snapshot headers and the use-case contract.

The five snapshot files keep their historical headers (Vietnamese for invoices
and goods, English for debt and returns) so existing Excel exports stay
readable. ``SyncBusinessDataUseCase`` only speaks the canonical English names
defined here.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

INVOICE_COLUMN_MAP = {
    "Ngày": "issued_at",
    "Số phiếu": "invoice_number",
    "Khách hàng": "customer_name",
    "Địa chỉ": "address_detail",
    "Xóm": "village_name",
    "Xã": "ward_name",
    "Tổng tiền": "invoice_total_amount",
    "Ghi nợ": "debt_delta_amount",
}
GOODS_COLUMN_MAP = {
    "Số phiếu": "invoice_number",
    "Tên hàng chuẩn hóa": "product_name",
    "Loại mặt hàng": "product_category_name",
    "ĐVT": "unit_name",
    "Đơn giá": "unit_price",
    "Số lượng": "quantity",
    "Thành tiền": "line_amount",
}

SNAPSHOT_FILES = {
    "customer_df": "Khach_hang.xlsx",
    "goods_df": "Hang_hoa.xlsx",
    "debt_df": "Cong_no.xlsx",
    "returns_df": "Tra_hang.xlsx",
    "return_lines_df": "Chi_tiet_tra_hang.xlsx",
}


def canonical_invoices(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename Vietnamese invoice headers; canonical names pass through."""
    return frame.rename(columns=INVOICE_COLUMN_MAP)


def canonical_goods(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename Vietnamese goods headers; canonical names pass through."""
    return frame.rename(columns=GOODS_COLUMN_MAP)


def sync_arguments(
    customers: pd.DataFrame,
    goods: pd.DataFrame,
    debt_transactions: pd.DataFrame,
    sales_returns: pd.DataFrame,
    sales_return_lines: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Keyword arguments for ``SyncBusinessDataUseCase.sync_all``."""
    return {
        "customer_df": canonical_invoices(customers),
        "goods_df": canonical_goods(goods),
        "debt_df": debt_transactions,
        "returns_df": sales_returns,
        "return_lines_df": sales_return_lines,
    }


def read_snapshot_directory(directory: str | Path) -> dict[str, pd.DataFrame]:
    """Read the five Excel snapshots and map them to the canonical contract."""
    base = Path(directory)
    frames = {
        argument: pd.read_excel(base / filename)
        for argument, filename in SNAPSHOT_FILES.items()
    }
    return sync_arguments(
        frames["customer_df"],
        frames["goods_df"],
        frames["debt_df"],
        frames["returns_df"],
        frames["return_lines_df"],
    )
