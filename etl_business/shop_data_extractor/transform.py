from __future__ import annotations

import math
from decimal import Decimal
from datetime import date, datetime
import pandas as pd

def clean_value(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, memoryview):
        return bytes(value)
    return value

def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Loại bỏ cột hoàn toàn rỗng; giữ nguyên tên cột nguồn để không làm mất semantics.
    df = df.dropna(axis=1, how="all")
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].map(clean_value)
    return df

def apply_column_mapping(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    if not mapping:
        return df

    missing = [source for source in mapping.values() if source not in df.columns]
    if missing:
        raise KeyError(f"Missing source columns: {missing}")

    selected = df[list(mapping.values())].copy()
    selected.columns = list(mapping.keys())
    return selected
