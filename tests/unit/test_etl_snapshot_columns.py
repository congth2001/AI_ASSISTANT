"""Read-boundary mapping keeps historical Excel snapshots readable."""
import pandas as pd
import pytest

from etl_business.pipeline import build_business_snapshots
from etl_business.snapshot_columns import (
    canonical_goods,
    canonical_invoices,
    read_snapshot_directory,
)
from src.modules.sales.application.use_cases.sync_business_data_use_case import (
    SyncBusinessDataUseCase,
)
from tests.unit.test_etl_business_pipeline import canonical_datasets


def test_vietnamese_invoice_and_goods_headers_map_to_canonical_names():
    invoices = pd.DataFrame(
        columns=["Ngày", "Số phiếu", "Khách hàng", "Địa chỉ", "Xóm", "Xã", "Tổng tiền", "Ghi nợ"]
    )
    goods = pd.DataFrame(
        columns=["Số phiếu", "Tên hàng chuẩn hóa", "Loại mặt hàng", "ĐVT", "Đơn giá", "Số lượng", "Thành tiền"]
    )

    assert set(canonical_invoices(invoices).columns) == SyncBusinessDataUseCase.INVOICE_COLUMNS | {
        "address_detail", "village_name", "ward_name",
    }
    assert set(canonical_goods(goods).columns) == SyncBusinessDataUseCase.LINE_COLUMNS


def test_canonical_headers_pass_through_unchanged():
    frame = pd.DataFrame(columns=["issued_at", "invoice_number"])

    assert canonical_invoices(frame).columns.tolist() == ["issued_at", "invoice_number"]


def test_pipeline_snapshots_feed_the_use_case_contract():
    snapshots = build_business_snapshots(canonical_datasets())

    arguments = snapshots.sync_arguments()

    assert set(arguments) == {"customer_df", "goods_df", "debt_df", "returns_df", "return_lines_df"}
    assert SyncBusinessDataUseCase.INVOICE_COLUMNS <= set(arguments["customer_df"].columns)
    assert SyncBusinessDataUseCase.LINE_COLUMNS <= set(arguments["goods_df"].columns)
    # Excel-facing frames keep their historical headers.
    assert "Số phiếu" in snapshots.customers.columns


def test_excel_snapshots_written_by_the_pipeline_round_trip_into_canonical_frames(tmp_path):
    snapshots = build_business_snapshots(canonical_datasets())
    snapshots.write_excel(tmp_path)

    arguments = read_snapshot_directory(tmp_path)

    assert SyncBusinessDataUseCase.INVOICE_COLUMNS <= set(arguments["customer_df"].columns)
    assert SyncBusinessDataUseCase.LINE_COLUMNS <= set(arguments["goods_df"].columns)
    assert arguments["customer_df"].loc[0, "customer_name"] == "Anh An"
    assert arguments["goods_df"].loc[0, "product_name"] == "gạch"


def test_missing_snapshot_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_snapshot_directory(tmp_path)
