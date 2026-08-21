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
    order_by: str | None = None,
) -> pd.DataFrame:
    source_columns = list(columns.values()) if columns else []
    select_sql = (
        ", ".join(quote_ident(c) for c in source_columns)
        if source_columns else "*"
    )

    sql = f"SELECT {select_sql} FROM {quote_ident(table)}"
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"

    df = pd.read_sql(sql, conn)
    df = normalize_dataframe(df)
    df = apply_column_mapping(df, columns or {})
    return df

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
                order_by=spec.get("order_by"),
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
