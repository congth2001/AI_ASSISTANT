from __future__ import annotations

from pathlib import Path
import pandas as pd

from .access import quote_ident, list_tables, detect_table
from .transform import normalize_dataframe, apply_column_mapping

def read_table(
    conn,
    table: str,
    columns: dict | None = None,
    where: str | None = None,
    sort_by: list[str] | None = None,
) -> pd.DataFrame:
    """Read one MDB table and map it to canonical column names.

    Sorting happens in pandas, never in SQL: the MDBTools ODBC driver used on
    Linux cannot parse ``ORDER BY`` ("Couldn't parse SQL") and returns rows in
    storage order. ``sort_by`` lists *source* column names that must be selected.
    """
    source_columns = list(columns.values()) if columns else []
    select_sql = (
        ", ".join(quote_ident(c) for c in source_columns)
        if source_columns else "*"
    )

    sql = f"SELECT {select_sql} FROM {quote_ident(table)}"
    if where:
        sql += f" WHERE {where}"

    df = pd.read_sql(sql, conn)
    df = normalize_dataframe(df)
    if sort_by:
        missing = [column for column in sort_by if column not in df.columns]
        if missing:
            raise KeyError(f"sort_by columns are not selected: {missing}")
        # Stable sort so ties keep a deterministic order across drivers.
        df = df.sort_values(list(sort_by), kind="mergesort", ignore_index=True)
    df = apply_column_mapping(df, columns or {})
    return df


def _sort_columns(spec: dict) -> list[str] | None:
    if spec.get("order_by"):
        raise ValueError(
            "'order_by' is no longer supported (MDBTools on Linux cannot parse ORDER BY); "
            "use 'sort_by' with a list of source column names instead"
        )
    sort_by = spec.get("sort_by")
    if sort_by is None:
        return None
    if isinstance(sort_by, str):
        return [sort_by]
    return [str(column) for column in sort_by]

def resolve_datasets(conn, config: dict) -> list[dict]:
    tables = list_tables(conn)
    resolved = []

    for dataset_name, spec in (config.get("datasets") or {}).items():
        if not spec.get("enabled", True):
            continue

        table = spec.get("table")
        if table and table not in tables:
            raise ValueError(
                f"Configured table '{table}' for dataset '{dataset_name}' "
                f"does not exist in MDB."
            )

        if not table:
            table = detect_table(tables, spec.get("candidate_tables") or [])

        if not table:
            # Không đoán bừa; dataset chưa resolve sẽ được ghi vào manifest.
            resolved.append({
                "dataset": dataset_name,
                "status": "SKIPPED",
                "reason": "No matching MDB table found",
                **spec,
                "table": None,
            })
            continue

        resolved.append({
            "dataset": dataset_name,
            "status": "READY",
            **spec,
            "table": table,
        })

    for table in config.get("extra_tables") or []:
        if table not in tables:
            raise ValueError(f"extra_tables contains missing table: {table}")
        resolved.append({
            "dataset": table,
            "filename": table,
            "table": table,
            "columns": {},
            "status": "READY",
        })

    return resolved

def extract_all(conn, config: dict, output_dir: str) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    out = Path(output_dir)
    csv_dir = out / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    datasets = {}
    manifest = []

    for spec in resolve_datasets(conn, config):
        if spec["status"] != "READY":
            manifest.append(spec)
            continue

        dataset = spec["dataset"]
        table = spec["table"]
        filename = spec.get("filename") or dataset

        try:
            df = read_table(
                conn,
                table=table,
                columns=spec.get("columns") or {},
                where=spec.get("where"),
                sort_by=_sort_columns(spec),
            )
            df.to_csv(
                csv_dir / f"{filename}.csv",
                index=False,
                encoding="utf-8-sig"
            )
            datasets[dataset] = df
            manifest.append({
                "dataset": dataset,
                "source_table": table,
                "filename": filename,
                "rows": len(df),
                "columns": len(df.columns),
                "status": "SUCCESS",
            })
        except Exception as exc:
            manifest.append({
                "dataset": dataset,
                "source_table": table,
                "filename": filename,
                "status": "FAILED",
                "error": str(exc),
            })

    return datasets, manifest
