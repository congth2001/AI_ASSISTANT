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


def accepted_query_results(case: dict[str, Any]) -> list[QueryResult]:
    """Other result shapes that answer the question equally well.

    Example: "doanh thu từng tháng" may return the month number (``EXTRACT``) or
    the first day of the month (``DATE_TRUNC``). Each alternative is declared in the
    dataset next to the reference answer.
    """
    return [
        QueryResult(
            columns=tuple(alternative.get("columns", [])),
            rows=tuple(tuple(row) for row in alternative["rows"]),
        )
        for alternative in case.get("accepted_results", [])
    ]


def _column_values(result: QueryResult, index: int, *, ordered: bool) -> list[str]:
    values = [
        json.dumps(canonical_value(row[index]), ensure_ascii=False, sort_keys=True)
        for row in result.rows
    ]
    return values if ordered else sorted(values)


def _project(result: QueryResult, indexes: tuple[int, ...]) -> QueryResult:
    return QueryResult(
        columns=tuple(result.columns[i] for i in indexes),
        rows=tuple(tuple(row[i] for i in indexes) for row in result.rows),
    )


def results_match(
    actual: QueryResult,
    expected: QueryResult,
    *,
    ordered: bool,
    compare_columns: bool = False,
    allow_extra_columns: bool = False,
) -> bool:
    """Compare results; optionally accept extra or reordered predicted columns.

    With ``allow_extra_columns`` the prediction is correct when some of its columns,
    taken in some order, reproduce the expected result exactly (same rows, same row
    order when ``ordered``). Agent SQL legitimately adds context columns such as
    ``ma_khach_hang`` or ``don_vi_tinh``; extra rows or wrong values still fail.
    """
    if results_equal(actual, expected, ordered=ordered, compare_columns=compare_columns):
        return True
    if not allow_extra_columns or len(actual.rows) != len(expected.rows):
        return False
    width = len(expected.columns) or (len(expected.rows[0]) if expected.rows else 0)
    if len(actual.columns) < width:
        return False
    candidates: list[list[int]] = []
    for j in range(width):
        wanted = _column_values(expected, j, ordered=ordered)
        matches = [
            i for i in range(len(actual.columns))
            if _column_values(actual, i, ordered=ordered) == wanted
            and (not compare_columns or actual.columns[i].lower() == expected.columns[j].lower())
        ]
        if not matches:
            return False
        candidates.append(matches)

    def search(j: int, chosen: tuple[int, ...]) -> bool:
        if j == width:
            return results_equal(
                _project(actual, chosen), expected,
                ordered=ordered, compare_columns=compare_columns,
            )
        return any(search(j + 1, chosen + (i,)) for i in candidates[j] if i not in chosen)

    return search(0, ())


def validate_case_set(cases: Iterable[dict[str, Any]]) -> None:
    required = {"id", "question", "reference_sql", "expected_result", "ordered"}
    for case in cases:
        missing = required - case.keys()
        if missing:
            raise ValueError(f"Case {case.get('id', '<unknown>')} thiếu: {sorted(missing)}")
        if not isinstance(case["expected_result"].get("rows"), list):
            raise ValueError(f"Case {case['id']} có expected_result.rows không hợp lệ")
        for alternative in case.get("accepted_results", []):
            if not isinstance(alternative.get("rows"), list):
                raise ValueError(f"Case {case['id']} có accepted_results.rows không hợp lệ")


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
