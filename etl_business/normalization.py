from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


def normalize_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    return text or None


def split_customer_address(value: Any) -> tuple[str | None, str | None]:
    """Port the functional address rule from normalize_customer.ipynb."""
    address = normalize_text(value)
    if not address:
        return None, None
    parts = [normalize_text(part) for part in address.split("-")]
    return parts[0] if parts else None, parts[1] if len(parts) > 1 else None


def normalize_product_name(value: Any) -> str | None:
    """Port normalize_whitespace from normalize_good.ipynb."""
    text = normalize_text(value)
    if not text:
        return None
    return re.sub(r"\s+", " ", text.replace(".", " ")).strip().lower()


def load_product_aliases(mapping_path: str | Path) -> dict[str, str]:
    """Load the curated, versioned alias map used by the production ETL."""
    path = Path(mapping_path)
    if not path.exists():
        raise FileNotFoundError(f"Product alias mapping not found: {path}")
    aliases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(aliases, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in aliases.items()
    ):
        raise ValueError("Product alias mapping must be a JSON string-to-string object")
    return aliases


def normalize_canonical_datasets(
    datasets: Mapping[str, pd.DataFrame],
    product_aliases: Mapping[str, str],
) -> dict[str, pd.DataFrame]:
    normalized = {name: frame.copy() for name, frame in datasets.items()}
    customers = normalized.get("customers")
    if customers is not None:
        for column in ("customer_name", "address_detail", "village_name", "ward_name"):
            if column in customers:
                customers[column] = customers[column].map(normalize_text)
        if "address_detail" in customers:
            derived = customers["address_detail"].map(split_customer_address)
            villages = pd.Series((item[0] for item in derived), index=customers.index)
            wards = pd.Series((item[1] for item in derived), index=customers.index)
            if "village_name" not in customers:
                customers["village_name"] = villages
            else:
                customers["village_name"] = customers["village_name"].fillna(villages)
            if "ward_name" not in customers:
                customers["ward_name"] = wards
            else:
                customers["ward_name"] = customers["ward_name"].fillna(wards)

    products = normalized.get("products")
    if products is not None and "product_name" in products:
        cleaned = products["product_name"].map(normalize_product_name)
        products["product_name"] = cleaned.map(
            lambda value: product_aliases.get(value, value) if value else value
        )
        if products["product_name"].isna().any():
            raise ValueError("Products contains an empty name after normalization")

        categories = normalized.get("product_categories")
        if categories is not None and "category_id" in products:
            if categories["category_id"].duplicated().any():
                raise ValueError("Product categories contains duplicate category_id")
            normalized["products"] = products.merge(
                categories[["category_id", "product_category_name"]],
                on="category_id",
                how="left",
                validate="many_to_one",
            )

    sale_items = normalized.get("sale_items")
    if sale_items is not None and "line_amount" not in sale_items:
        missing = {"quantity", "unit_price"} - set(sale_items.columns)
        if missing:
            raise ValueError(
                "Cannot derive line_amount; sale_items is missing: "
                + ", ".join(sorted(missing))
            )
        quantity = pd.to_numeric(sale_items["quantity"], errors="raise")
        unit_price = pd.to_numeric(sale_items["unit_price"], errors="raise")
        sale_items["line_amount"] = quantity * unit_price
    return normalized
