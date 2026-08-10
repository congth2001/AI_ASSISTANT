"""Execution-based scorer for Text-to-SQL benchmark cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL không hợp lệ tại {path}:{line_number}: {exc}") from exc
            record_id = record.get("id") or record.get("case_id")
            if not record_id:
                raise ValueError(f"Thiếu id/case_id tại {path}:{line_number}")
            if record_id in seen:
                raise ValueError(f"Trùng id '{record_id}' tại {path}:{line_number}")
            seen.add(record_id)
            records.append(record)
    return records


def canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (Decimal, int, float)):
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        if not decimal_value.is_finite():
            return {"$number": str(decimal_value)}
        rendered = format(decimal_value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return {"$number": rendered or "0"}
    if isinstance(value, (datetime, date)):
        return {"$datetime": value.isoformat()}
    if isinstance(value, bytes):
        return {"$bytes": value.hex()}
    return value


def canonical_result(
    result: QueryResult,
    *,
    ordered: bool,
    compare_columns: bool = False,
) -> dict[str, Any]:
    rows = [[canonical_value(cell) for cell in row] for row in result.rows]
    if not ordered:
        rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    normalized: dict[str, Any] = {"rows": rows}
    if compare_columns:
        normalized["columns"] = [column.lower() for column in result.columns]
    return normalized


def expected_query_result(case: dict[str, Any]) -> QueryResult:
    expected = case["expected_result"]
    return QueryResult(
        columns=tuple(expected.get("columns", [])),
        rows=tuple(tuple(row) for row in expected["rows"]),
    )


def results_equal(
    actual: QueryResult,
    expected: QueryResult,
    *,
    ordered: bool,
    compare_columns: bool = False,
) -> bool:
    return canonical_result(
        actual,
        ordered=ordered,
        compare_columns=compare_columns,
    ) == canonical_result(
        expected,
        ordered=ordered,
        compare_columns=compare_columns,
    )


def validate_case_set(cases: Iterable[dict[str, Any]]) -> None:
    required = {"id", "question", "reference_sql", "expected_result", "ordered"}
    for case in cases:
        missing = required - case.keys()
        if missing:
            raise ValueError(f"Case {case.get('id', '<unknown>')} thiếu: {sorted(missing)}")
        if not isinstance(case["expected_result"].get("rows"), list):
            raise ValueError(f"Case {case['id']} có expected_result.rows không hợp lệ")


def summary_metrics(details: list[dict[str, Any]], total_cases: int) -> dict[str, Any]:
    covered = sum(item["status"] != "missing_prediction" for item in details)
    executed = sum(item["status"] in {"correct", "wrong_result"} for item in details)
    correct = sum(item["status"] == "correct" for item in details)
    denominator = total_cases or 1
    return {
        "total_cases": total_cases,
        "predictions_covered": covered,
        "queries_executed_successfully": executed,
        "correct_results": correct,
        "coverage": round(covered / denominator, 4),
        "execution_success_rate": round(executed / denominator, 4),
        "execution_result_accuracy": round(correct / denominator, 4),
    }
