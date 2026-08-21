from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

from .access import list_tables, get_columns, row_count, sample_rows

def build_profile(conn, output_dir: str) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    tables = list_tables(conn)
    table_rows = []
    column_rows = []
    sample_rows_all = []

    profile = {"tables": []}

    for table in tables:
        count = row_count(conn, table)
        columns = get_columns(conn, table)
        try:
            samples = sample_rows(conn, table, 3)
        except Exception as exc:
            samples = [{"__error__": str(exc)}]

        table_rows.append({
            "table": table,
            "row_count": count,
            "column_count": len(columns),
        })

        for c in columns:
            column_rows.append({"table": table, **c})

        for idx, sample in enumerate(samples, start=1):
            sample_rows_all.append({
                "table": table,
                "sample_no": idx,
                "data_json": json.dumps(sample, ensure_ascii=False, default=str),
            })

        profile["tables"].append({
            "name": table,
            "row_count": count,
            "columns": columns,
            "samples": samples,
        })

    (out / "schema_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8"
    )

    with pd.ExcelWriter(out / "schema_profile.xlsx", engine="openpyxl") as writer:
        pd.DataFrame(table_rows).to_excel(writer, sheet_name="Tables", index=False)
        pd.DataFrame(column_rows).to_excel(writer, sheet_name="Columns", index=False)
        pd.DataFrame(sample_rows_all).to_excel(writer, sheet_name="Samples", index=False)

    return profile
