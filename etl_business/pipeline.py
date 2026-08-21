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
    debt_transactions: pd.DataFrame
    sales_returns: pd.DataFrame
    sales_return_lines: pd.DataFrame

    def write_excel(self, output_dir: str | Path) -> tuple[Path, Path, Path, Path, Path]:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        customers_path = destination / "Khach_hang.xlsx"
        goods_path = destination / "Hang_hoa.xlsx"
        debt_path = destination / "Cong_no.xlsx"
        returns_path = destination / "Tra_hang.xlsx"
        return_lines_path = destination / "Chi_tiet_tra_hang.xlsx"
        self.customers.to_excel(customers_path, index=False)
        self.goods.to_excel(goods_path, index=False)
        self.debt_transactions.to_excel(debt_path, index=False)
        self.sales_returns.to_excel(returns_path, index=False)
        self.sales_return_lines.to_excel(return_lines_path, index=False)
        return customers_path, goods_path, debt_path, returns_path, return_lines_path


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
    customer_ward_aliases: Mapping[str, str] | None = None,
    opening_balance_date: str = "2019-01-01",
) -> BusinessSnapshots:
    """Join canonical MDB extracts into the application's two import snapshots.

    The extraction YAML owns source-to-canonical column mapping. This function
    deliberately accepts only canonical names so schema mistakes fail early.
    """

    datasets = normalize_canonical_datasets(
        datasets, product_aliases or {}, customer_ward_aliases
    )
    required_datasets = {
        "customers", "sales", "sale_items", "products",
        "sales_returns", "sales_return_items",
    }
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
    sales_returns = datasets["sales_returns"].copy()
    return_items = datasets["sales_return_items"].copy()

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
    _require_columns(
        sales_returns,
        {"source_id", "return_number", "customer_id", "occurred_at", "return_total_amount", "amount"},
        "sales_returns",
    )
    _require_columns(
        return_items,
        {"source_line_id", "source_id", "product_id", "quantity", "unit_price", "line_amount"},
        "sales_return_items",
    )

    for frame, key, name in (
        (customers, "customer_id", "customers"),
        (sales, "invoice_id", "sales"),
        (products, "product_id", "products"),
        (sales_returns, "source_id", "sales_returns"),
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

    customer_lookup = customers[
        [
            "customer_id",
            "customer_name",
            "address_detail",
            "village_name",
            "ward_name",
        ]
    ]

    return_headers = sales_returns.merge(
        customer_lookup,
        on="customer_id",
        how="left",
        validate="many_to_one",
    )[
        [
            "source_id", "return_number", "occurred_at", "return_total_amount",
            "customer_name", "address_detail", "village_name", "ward_name",
        ]
    ]
    if return_headers["customer_name"].isna().any():
        raise ValueError("Sales returns reference an unknown customer")

    return_lines = return_items.merge(
        sales_returns[
            ["source_id"]
        ],
        on="source_id",
        how="inner",
        validate="many_to_one",
    ).merge(
        products[
            ["product_id", "product_name", "product_category_name", "unit_name"]
        ],
        on="product_id",
        how="left",
        validate="many_to_one",
    )
    if return_lines[["product_name", "unit_name"]].isna().any().any():
        raise ValueError("Sales return items reference an unknown product")
    return_lines = return_lines[
        [
            "source_id", "source_line_id", "product_name", "product_category_name", "unit_name",
            "unit_price", "quantity", "line_amount",
        ]
    ]

    debt_parts: list[pd.DataFrame] = []

    def attach_customer(events: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
        joined = events.merge(
            customer_lookup, on="customer_id", how="left", validate="many_to_one"
        )
        if joined["customer_name"].isna().any():
            raise ValueError(f"{dataset_name} references customer_id absent from customers")
        return joined
    if "opening_receivable" in customers:
        opening = customers.loc[
            customers["opening_receivable"].fillna(0) != 0,
            [
                "customer_id",
                "customer_name",
                "address_detail",
                "village_name",
                "ward_name",
                "opening_receivable",
            ],
        ].copy()
        opening["source_type"] = "opening"
        opening["source_id"] = opening["customer_id"].astype(str)
        opening["occurred_at"] = pd.Timestamp(opening_balance_date)
        opening["amount"] = opening.pop("opening_receivable")
        debt_parts.append(opening)

    sale_debt = sales.loc[
        sales["debt_delta_amount"].fillna(0) != 0,
        ["invoice_id", "customer_id", "issued_at", "debt_delta_amount"],
    ].copy()
    sale_debt["source_type"] = "sale"
    sale_debt["source_id"] = sale_debt.pop("invoice_id").astype(str)
    sale_debt["occurred_at"] = sale_debt.pop("issued_at")
    sale_debt["amount"] = sale_debt.pop("debt_delta_amount")
    debt_parts.append(attach_customer(sale_debt, "sales"))

    for dataset_name, source_type in (
        ("debt_receipts", "receipt"),
        ("sales_returns", "sales_return"),
    ):
        if dataset_name not in datasets:
            raise ValueError(f"Cannot build debt ledger; missing dataset: {dataset_name}")
        events = datasets[dataset_name].copy()
        events = events.loc[events["amount"].fillna(0) != 0]
        events["source_type"] = source_type
        events["source_id"] = events["source_id"].astype(str)
        events["amount"] = -pd.to_numeric(events["amount"], errors="raise")
        debt_parts.append(attach_customer(events, dataset_name))

    debt_transactions = pd.concat(debt_parts, ignore_index=True)[
        [
            "source_type",
            "source_id",
            "occurred_at",
            "customer_name",
            "address_detail",
            "village_name",
            "ward_name",
            "amount",
        ]
    ]

    return BusinessSnapshots(
        customers=customer_snapshot,
        goods=goods_snapshot,
        debt_transactions=debt_transactions,
        sales_returns=return_headers,
        sales_return_lines=return_lines,
    )
