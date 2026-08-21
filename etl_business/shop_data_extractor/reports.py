from __future__ import annotations

from pathlib import Path
from datetime import datetime
import pandas as pd

EXCEL_MAX_ROWS = 1_048_576

def autosize_worksheet(ws, max_width: int = 45):
    for column_cells in ws.columns:
        values = [str(c.value) if c.value is not None else "" for c in column_cells[:200]]
        width = min(max((len(v) for v in values), default=8) + 2, max_width)
        ws.column_dimensions[column_cells[0].column_letter].width = max(10, width)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

def export_excel(
    datasets: dict[str, pd.DataFrame],
    manifest: list[dict],
    output_dir: str,
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "ishopman_extract.xlsx"

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(manifest).to_excel(writer, sheet_name="_manifest", index=False)

        for name, df in datasets.items():
            safe_name = name[:31]
            if len(df) <= EXCEL_MAX_ROWS - 1:
                df.to_excel(writer, sheet_name=safe_name, index=False)
            else:
                # Excel giới hạn ~1.048M rows/sheet; chia sheet khi cần.
                chunk_size = EXCEL_MAX_ROWS - 1
                for i, start in enumerate(range(0, len(df), chunk_size), start=1):
                    chunk = df.iloc[start:start + chunk_size]
                    chunk.to_excel(
                        writer,
                        sheet_name=f"{safe_name[:25]}_{i}"[:31],
                        index=False
                    )

        for ws in writer.book.worksheets:
            autosize_worksheet(ws)

    return path

def export_manifest_csv(manifest: list[dict], output_dir: str) -> Path:
    path = Path(output_dir) / "extract_manifest.csv"
    pd.DataFrame(manifest).to_csv(path, index=False, encoding="utf-8-sig")
    return path
