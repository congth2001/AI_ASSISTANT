import pandas as pd
import pytest

from etl_business.pipeline import build_business_snapshots


def canonical_datasets():
    return {
        "customers": pd.DataFrame(
            [{"customer_id": "c1", "customer_name": "Anh An"}]
        ),
        "sales": pd.DataFrame(
            [
                {
                    "invoice_id": "i1",
                    "invoice_number": "PX-1",
                    "customer_id": "c1",
                    "issued_at": "2026-01-01",
                    "invoice_total_amount": 100,
                }
            ]
        ),
        "sale_items": pd.DataFrame(
            [
                {
                    "invoice_id": "i1",
                    "product_id": "p1",
                    "quantity": 2,
                    "unit_price": 50,
                    "line_amount": 100,
                }
            ]
        ),
        "products": pd.DataFrame(
            [
                {
                    "product_id": "p1",
                    "product_name": "Gạch",
                    "unit_name": "Viên",
                }
            ]
        ),
    }


def test_build_business_snapshots_matches_sync_contract():
    snapshots = build_business_snapshots(canonical_datasets())

    assert snapshots.customers.columns.tolist() == [
        "Ngày",
        "Số phiếu",
        "Khách hàng",
        "Địa chỉ",
        "Xóm",
        "Xã",
        "Tổng tiền",
        "Ghi nợ",
    ]
    assert snapshots.goods.columns.tolist() == [
        "Số phiếu",
        "Tên hàng chuẩn hóa",
        "Loại mặt hàng",
        "ĐVT",
        "Đơn giá",
        "Số lượng",
        "Thành tiền",
    ]
    assert snapshots.customers.loc[0, "Khách hàng"] == "Anh An"
    assert snapshots.goods.loc[0, "Tên hàng chuẩn hóa"] == "gạch"


def test_build_business_snapshots_rejects_broken_foreign_keys():
    datasets = canonical_datasets()
    datasets["sale_items"].loc[0, "product_id"] = "missing"

    with pytest.raises(ValueError, match="unknown invoice or product"):
        build_business_snapshots(datasets)
