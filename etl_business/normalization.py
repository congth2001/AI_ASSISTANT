from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


def normalize_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    return text or None


def _matching_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def load_customer_ward_aliases(mapping_path: str | Path) -> dict[str, str]:
    path = Path(mapping_path)
    if not path.exists():
        raise FileNotFoundError(f"Customer ward alias mapping not found: {path}")
    grouped = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(grouped, dict):
        raise ValueError("Customer ward mapping must be a JSON object")

    aliases: dict[str, str] = {}
    for canonical, variants in grouped.items():
        if not isinstance(canonical, str) or not isinstance(variants, list):
            raise ValueError("Customer ward mapping must contain string-to-list entries")
        for variant in {canonical, *variants}:
            if not isinstance(variant, str):
                raise ValueError("Customer ward aliases must be strings")
            key = _matching_key(normalize_text(variant) or "")
            previous = aliases.get(key)
            if previous is not None and previous != canonical:
                raise ValueError(f"Customer ward alias {variant!r} maps to multiple values")
            aliases[key] = canonical
    return aliases


def normalize_customer_ward(
    value: Any, aliases: Mapping[str, str]
) -> str | None:
    text = normalize_text(value)
    if not text:
        return None
    return aliases.get(_matching_key(text), "Khác")


def infer_customer_location(
    value: Any, aliases: Mapping[str, str]
) -> tuple[str | None, str | None]:
    """Infer village and canonical ward from the complete source address text."""
    address = normalize_text(value)
    if not address:
        return None, None
    address_key = _matching_key(address)
    matched_alias = next(
        (
            alias
            for alias in sorted(aliases, key=len, reverse=True)
            if alias and alias in address_key
        ),
        None,
    )
    if matched_alias is None:
        return address, "Khác"

    canonical_ward = aliases[matched_alias]
    village = re.sub(
        re.escape(matched_alias), " ", address, count=1, flags=re.IGNORECASE
    )
    village = re.sub(r"^[\s_\-,;]+|[\s_\-,;]+$", "", village)
    village = normalize_text(village)
    return village, canonical_ward


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
    customer_ward_aliases: Mapping[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    normalized = {name: frame.copy() for name, frame in datasets.items()}
    customers = normalized.get("customers")
    if customers is not None:
        for column in ("customer_name", "address_detail", "village_name", "ward_name"):
            if column in customers:
                customers[column] = customers[column].map(normalize_text)
        if "address_detail" in customers:
            if customer_ward_aliases is not None:
                derived = customers["address_detail"].map(
                    lambda value: infer_customer_location(
                        value, customer_ward_aliases
                    )
                )
            else:
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
        if "ward_name" in customers and customer_ward_aliases is not None:
            customers["ward_name"] = customers["ward_name"].map(
                lambda value: normalize_customer_ward(value, customer_ward_aliases)
            )

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

    for dataset_name in ("sale_items", "sales_return_items"):
        sale_items = normalized.get(dataset_name)
        if sale_items is None or "line_amount" in sale_items:
            continue
        missing = {"quantity", "unit_price"} - set(sale_items.columns)
        if missing:
            raise ValueError(
                f"Cannot derive line_amount; {dataset_name} is missing: "
                + ", ".join(sorted(missing))
            )
        quantity = pd.to_numeric(sale_items["quantity"], errors="raise")
        unit_price = pd.to_numeric(sale_items["unit_price"], errors="raise")
        sale_items["line_amount"] = quantity * unit_price
    return normalized
