"""Run the small Text-to-SQL benchmark against an isolated PostgreSQL fixture."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from evals.execution_eval import (  # noqa: E402
    QueryResult,
    canonical_result,
    expected_query_result,
    load_jsonl,
    results_equal,
    summary_metrics,
    validate_case_set,
)
from src.application.services.sql_service import SQLService  # noqa: E402

DEFAULT_DATASET = BACKEND_DIR / "evals" / "datasets" / "business_sql_small.jsonl"
DEFAULT_FIXTURE = BACKEND_DIR / "evals" / "fixtures" / "business_sql_small.sql"


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Đo execution result accuracy cho SQL do agent sinh."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--predictions",
        type=Path,
        help="JSONL gồm case_id và sql. Bỏ qua khi dùng --use-reference.",
    )
    parser.add_argument(
        "--use-reference",
        action="store_true",
        help="Dùng SQL tham chiếu làm prediction để kiểm chứng benchmark.",
    )
    parser.add_argument(
        "--dsn",
        default=os.getenv("AI_QC_BENCHMARK_DSN"),
        help="PostgreSQL DSN; mặc định đọc AI_QC_BENCHMARK_DSN.",
    )
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--compare-columns",
        action="store_true",
        help="Yêu cầu alias cột của prediction khớp ground truth.",
    )
    return parser.parse_args()


def load_predictions(args: argparse.Namespace, cases: list[dict[str, Any]]) -> dict[str, str]:
    if args.use_reference:
        return {case["id"]: case["reference_sql"] for case in cases}
    if not args.predictions:
        raise ValueError("Cần --predictions hoặc --use-reference")
    records = load_jsonl(args.predictions)
    predictions: dict[str, str] = {}
    for record in records:
        case_id = record.get("case_id") or record.get("id")
        sql = record.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError(f"Prediction {case_id} thiếu trường sql")
        predictions[case_id] = sql
    unknown = sorted(set(predictions) - {case["id"] for case in cases})
    if unknown:
        raise ValueError(f"Prediction chứa case_id không tồn tại: {unknown}")
    return predictions


def execute_read_only(
    connection,
    sql: str,
    timeout_ms: int,
) -> tuple[QueryResult, float]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", (str(timeout_ms),))
            started = time.perf_counter()
            cursor.execute(sql)
            rows = tuple(tuple(row) for row in cursor.fetchall())
            columns = tuple(item.name for item in cursor.description)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return QueryResult(columns=columns, rows=rows), elapsed_ms
    finally:
        connection.rollback()


def initialize_fixture(connection, fixture_path: Path) -> None:
    sql = fixture_path.read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        cursor.execute(sql)
    connection.commit()


def verify_ground_truth(connection, cases: list[dict[str, Any]], timeout_ms: int) -> None:
    failures: list[str] = []
    for case in cases:
        actual, _ = execute_read_only(connection, case["reference_sql"], timeout_ms)
        declared = expected_query_result(case)
        if not results_equal(actual, declared, ordered=case["ordered"], compare_columns=True):
            failures.append(
                f"{case['id']}: declared={canonical_result(declared, ordered=case['ordered'], compare_columns=True)} "
                f"actual={canonical_result(actual, ordered=case['ordered'], compare_columns=True)}"
            )
    if failures:
        raise RuntimeError("Ground truth không khớp fixture:\n" + "\n".join(failures))


def evaluate(
    connection,
    cases: list[dict[str, Any]],
    predictions: dict[str, str],
    *,
    timeout_ms: int,
    compare_columns: bool,
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    validator = SQLService(None)
    for case in cases:
        case_id = case["id"]
        sql = predictions.get(case_id)
        if sql is None:
            details.append({"case_id": case_id, "status": "missing_prediction"})
            continue

        try:
            safe_sql = validator.validate(sql)
        except Exception as exc:
            details.append(
                {"case_id": case_id, "status": "validation_error", "error": str(exc)}
            )
            continue

        try:
            predicted, latency_ms = execute_read_only(connection, safe_sql, timeout_ms)
        except Exception as exc:
            details.append(
                {"case_id": case_id, "status": "execution_error", "error": str(exc)}
            )
            continue

        reference, _ = execute_read_only(connection, case["reference_sql"], timeout_ms)
        correct = results_equal(
            predicted,
            reference,
            ordered=case["ordered"],
            compare_columns=compare_columns,
        )
        detail: dict[str, Any] = {
            "case_id": case_id,
            "status": "correct" if correct else "wrong_result",
            "latency_ms": latency_ms,
        }
        if not correct:
            detail["expected"] = canonical_result(
                reference,
                ordered=case["ordered"],
                compare_columns=compare_columns,
            )
            detail["actual"] = canonical_result(
                predicted,
                ordered=case["ordered"],
                compare_columns=compare_columns,
            )
        details.append(detail)
    return details


def print_summary(metrics: dict[str, Any], details: list[dict[str, Any]]) -> None:
    print("\nText-to-SQL execution benchmark")
    print(f"Cases:                     {metrics['total_cases']}")
    print(f"Prediction coverage:       {metrics['coverage']:.2%}")
    print(f"Execution success rate:    {metrics['execution_success_rate']:.2%}")
    print(f"Execution result accuracy: {metrics['execution_result_accuracy']:.2%}")
    print("\nCase results")
    for detail in details:
        suffix = f" ({detail['latency_ms']} ms)" if "latency_ms" in detail else ""
        print(f"- {detail['case_id']}: {detail['status']}{suffix}")


def main() -> int:
    configure_utf8_console()
    args = parse_args()
    if not args.dsn:
        print("Thiếu PostgreSQL DSN. Dùng --dsn hoặc AI_QC_BENCHMARK_DSN.", file=sys.stderr)
        return 2
    if args.timeout_ms <= 0:
        print("--timeout-ms phải lớn hơn 0.", file=sys.stderr)
        return 2

    try:
        cases = load_jsonl(args.dataset)
        validate_case_set(cases)
        predictions = load_predictions(args, cases)
        with psycopg2.connect(args.dsn) as connection:
            initialize_fixture(connection, args.fixture)
            verify_ground_truth(connection, cases, args.timeout_ms)
            details = evaluate(
                connection,
                cases,
                predictions,
                timeout_ms=args.timeout_ms,
                compare_columns=args.compare_columns,
            )
    except Exception as exc:
        print(f"Benchmark thất bại: {exc}", file=sys.stderr)
        return 2

    metrics = summary_metrics(details, len(cases))
    print_summary(metrics, details)
    report = {
        "benchmark": args.dataset.stem,
        "ground_truth_verified": True,
        "metrics": metrics,
        "details": details,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nReport: {args.report.resolve()}")
    return 0 if metrics["execution_result_accuracy"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
