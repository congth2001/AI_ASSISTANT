from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd

from .normalization import normalize_canonical_datasets


@dataclass(frozen=True)
class BusinessSnapshots:
    """DataFrames in the exact contract expected by SyncBusinessDataUseCase."""

    customers: pd.DataFrame
    goods: pd.DataFrame

    def write_excel(self, output_dir: str | Path) -> tuple[Path, Path]:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        customers_path = destination / "Khach_hang.xlsx"
        goods_path = destination / "Hang_hoa.xlsx"
        self.customers.to_excel(customers_path, index=False)
        self.goods.to_excel(goods_path, index=False)
        return customers_path, goods_path


def _require_columns(frame: pd.DataFrame, required: set[str], dataset: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            f"Canonical dataset {dataset!r} is missing columns: {', '.join(missing)}"
        )


def _unique(frame: pd.DataFrame, key: str, dataset: str) -> None:
    duplicated = frame[key].notna() & frame[key].duplicated(keep=False)
    if duplicated.any():
        values = frame.loc[duplicated, key].astype(str).drop_duplicates().head(5)
        raise ValueError(
            f"Canonical dataset {dataset!r} has duplicate {key!r}: "
            + ", ".join(values)
        )


def _optional_columns(frame: pd.DataFrame, defaults: Mapping[str, object]) -> pd.DataFrame:
    result = frame.copy()
    for column, default in defaults.items():
        if column not in result:
            result[column] = default
    return result


def build_business_snapshots(
    datasets: Mapping[str, pd.DataFrame],
    product_aliases: Mapping[str, str] | None = None,
) -> BusinessSnapshots:
    """Join canonical MDB extracts into the application's two import snapshots.

    The extraction YAML owns source-to-canonical column mapping. This function
    deliberately accepts only canonical names so schema mistakes fail early.
    """

    datasets = normalize_canonical_datasets(datasets, product_aliases or {})
    required_datasets = {"customers", "sales", "sale_items", "products"}
    missing_datasets = sorted(required_datasets - set(datasets))
    if missing_datasets:
        raise ValueError(
            "Cannot build business snapshots; missing datasets: "
            + ", ".join(missing_datasets)
        )

    customers = _optional_columns(
        datasets["customers"],
        {"address_detail": None, "village_name": None, "ward_name": None},
    )
    sales = _optional_columns(datasets["sales"], {"debt_delta_amount": None})
    items = datasets["sale_items"].copy()
    products = _optional_columns(
        datasets["products"], {"product_category_name": None}
    )

    _require_columns(customers, {"customer_id", "customer_name"}, "customers")
    _require_columns(
        sales,
        {
            "invoice_id",
            "invoice_number",
            "customer_id",
            "issued_at",
            "invoice_total_amount",
        },
        "sales",
    )
    _require_columns(
        items,
        {"invoice_id", "product_id", "quantity", "unit_price", "line_amount"},
        "sale_items",
    )
    _require_columns(products, {"product_id", "product_name", "unit_name"}, "products")

    for frame, key, name in (
        (customers, "customer_id", "customers"),
        (sales, "invoice_id", "sales"),
        (products, "product_id", "products"),
    ):
        _unique(frame, key, name)

    customer_snapshot = sales.merge(
        customers[
            [
                "customer_id",
                "customer_name",
                "address_detail",
                "village_name",
                "ward_name",
            ]
        ],
        on="customer_id",
        how="left",
        validate="many_to_one",
    )
    if customer_snapshot["customer_name"].isna().any():
        raise ValueError("Sales contains customer_id values absent from customers")

    customer_snapshot = customer_snapshot.rename(
        columns={
            "issued_at": "Ngày",
            "invoice_number": "Số phiếu",
            "customer_name": "Khách hàng",
            "address_detail": "Địa chỉ",
            "village_name": "Xóm",
            "ward_name": "Xã",
            "invoice_total_amount": "Tổng tiền",
            "debt_delta_amount": "Ghi nợ",
        }
    )[
        ["Ngày", "Số phiếu", "Khách hàng", "Địa chỉ", "Xóm", "Xã", "Tổng tiền", "Ghi nợ"]
    ]

    goods_snapshot = items.merge(
        sales[["invoice_id", "invoice_number"]],
        on="invoice_id",
        how="left",
        validate="many_to_one",
    ).merge(
        products[
            ["product_id", "product_name", "product_category_name", "unit_name"]
        ],
        on="product_id",
        how="left",
        validate="many_to_one",
    )
    if (
        goods_snapshot[["invoice_number", "product_name", "unit_name"]]
        .isna()
        .any()
        .any()
    ):
        raise ValueError("Sale items reference an unknown invoice or product")

    goods_snapshot = goods_snapshot.rename(
        columns={
            "invoice_number": "Số phiếu",
            "product_name": "Tên hàng chuẩn hóa",
            "product_category_name": "Loại mặt hàng",
            "unit_name": "ĐVT",
            "unit_price": "Đơn giá",
            "quantity": "Số lượng",
            "line_amount": "Thành tiền",
        }
    )[
        ["Số phiếu", "Tên hàng chuẩn hóa", "Loại mặt hàng", "ĐVT", "Đơn giá", "Số lượng", "Thành tiền"]
    ]

    return BusinessSnapshots(customers=customer_snapshot, goods=goods_snapshot)
