import pandas as pd

from etl_business.normalization import (
    load_product_aliases,
    normalize_canonical_datasets,
    normalize_product_name,
    split_customer_address,
)


def test_customer_address_rule_matches_notebook():
    assert split_customer_address(" Xóm 3 - Thụy Hưng ") == (
        "Xóm 3",
        "Thụy Hưng",
    )
    assert split_customer_address(None) == (None, None)


def test_product_text_rule_matches_notebook():
    assert normalize_product_name("  T140.   TP ") == "t140 tp"


def test_loads_versioned_product_aliases():
    aliases = load_product_aliases("etl_business/stats/product_aliases.json")

    assert aliases["t140 tp"] == "t 140 tp"
    assert len(aliases) > 100


def test_normalize_datasets_derives_address_and_applies_product_alias():
    datasets = {
        "customers": pd.DataFrame(
            [{"customer_name": " Anh  An ", "address_detail": "Xóm 3 - Xã A"}]
        ),
        "products": pd.DataFrame([{"product_name": "T140. TP"}]),
    }

    result = normalize_canonical_datasets(datasets, {"t140 tp": "t 140 tp"})

    assert result["customers"].loc[0, "customer_name"] == "Anh An"
    assert result["customers"].loc[0, "village_name"] == "Xóm 3"
    assert result["customers"].loc[0, "ward_name"] == "Xã A"
    assert result["products"].loc[0, "product_name"] == "t 140 tp"


def test_normalize_datasets_joins_category_and_derives_line_amount():
    datasets = {
        "products": pd.DataFrame(
            [{"product_id": 1, "category_id": 7, "product_name": "Ống", "unit_name": "cây"}]
        ),
        "product_categories": pd.DataFrame(
            [{"category_id": 7, "product_category_name": "ĐỒ NƯỚC"}]
        ),
        "sale_items": pd.DataFrame(
            [{"invoice_id": 3, "product_id": 1, "quantity": 2, "unit_price": 15}]
        ),
    }

    result = normalize_canonical_datasets(datasets, {})

    assert result["products"].loc[0, "product_category_name"] == "ĐỒ NƯỚC"
    assert result["sale_items"].loc[0, "line_amount"] == 30
