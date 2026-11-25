"""Generate Text-to-SQL predictions for the benchmark with the real SQL pipeline.

Each case goes through the same steps as ``TextToSQLUseCase``: QueryAnalyzer ->
SchemaLinker -> SQLService.generate -> validation (up to two validator repairs per
rejected plan, each seeing the previous draft) -> execution with up to two repairs on
database errors. Execution runs on the
benchmark fixture (temporary tables), so the repair loop sees the same kind of
errors as production without touching business tables.

QueryAnalyzer gets its customer/category catalogue from the fixture, as production
gets it from the business tables; real customer names are never used, so fixture
names cannot be fuzzy matched to real customers. The first plan that executes is the
prediction.

Calls the configured LLM provider (cost: about one generation call per case and run).

    .\\env\\Scripts\\python.exe evals\\generate_predictions.py --runs 3 --out-dir evals\\predictions\\agent
    .\\env\\Scripts\\python.exe evals\\run_execution_eval.py --predictions evals\\predictions\\agent\\run1.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
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

from evals.execution_eval import load_jsonl  # noqa: E402
from evals.run_execution_eval import (  # noqa: E402
    DEFAULT_DATASET,
    DEFAULT_FIXTURE,
    configure_utf8_console,
    execute_read_only,
    initialize_fixture,
)

SQL_MAX_RETRIES = 2  # same budget as TextToSQLUseCase


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sinh prediction SQL bằng pipeline Text-to-SQL thật.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=1, help="Số lần chạy (LLM không tất định).")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--dsn", default=os.getenv("AI_QC_BENCHMARK_DSN"))
    parser.add_argument("--timeout-ms", type=int, default=5000)
    return parser.parse_args()


def _db_error_message(exc: Exception) -> str:
    """Mirror PostgresSQLExecutor: SQLSTATE and primary message only."""
    code = getattr(exc, "pgcode", None) or "?"
    diag = getattr(exc, "diag", None)
    primary = getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
    return f"Lỗi SQL ({code}): {primary}"


class FixtureExecutor:
    """Serialized read-only execution on the fixture connection."""

    def __init__(self, connection, timeout_ms: int):
        self._connection = connection
        self._timeout_ms = timeout_ms
        self._lock = asyncio.Lock()

    async def run(self, sql: str) -> str | None:
        """Return ``None`` on success or the sanitized database error."""
        async with self._lock:
            try:
                execute_read_only(self._connection, sql, self._timeout_ms)
                return None
            except psycopg2.Error as exc:
                return _db_error_message(exc)


def fixture_catalogue(connection, timeout_ms: int) -> dict[str, list[str]]:
    """Customer and category names of the fixture (what ensure_fresh loads in production)."""
    customers, _ = execute_read_only(
        connection, "SELECT customer_name FROM customers WHERE deleted_at IS NULL", timeout_ms
    )
    categories, _ = execute_read_only(
        connection,
        "SELECT DISTINCT product_category_name FROM sales_invoice_lines "
        "WHERE deleted_at IS NULL AND product_category_name IS NOT NULL",
        timeout_ms,
    )
    return {
        "customer_names": [row[0] for row in customers.rows],
        "category_names": [row[0] for row in categories.rows],
    }


async def _validate_or_repair(plan, sql_service, linked, stats) -> str | None:
    """Like TextToSQLUseCase: up to SQL_MAX_RETRIES validator repairs, each seeing the last draft."""
    from src.modules.assistant.application.services.sql_service import SQLQueryPlan
    from src.modules.assistant.domain.errors import SQLValidationError

    candidate = SQLQueryPlan(plan.intent, plan.sql)
    for attempt in range(SQL_MAX_RETRIES + 1):
        try:
            return sql_service.validate(candidate.sql)
        except SQLValidationError as exc:
            stats["validator_errors"].append(exc.code)
            if attempt >= SQL_MAX_RETRIES:
                return None
            stats["repairs"] += 1
            try:
                candidate = await sql_service.draft_repair(candidate, exc.message, linked.schema_context)
            except Exception:
                return None
    return None


async def predict(case, *, sql_service, analyzer, linker, executor, semaphore, stats) -> str | None:
    async with semaphore:
        analyzed = analyzer.analyze(case["question"])
        linked = linker.link(analyzed)
        try:
            plans = await sql_service.generate(analyzed, linked)
        except Exception:
            stats["generation_failures"] += 1
            return None
        stats["plans"].append(len(plans))
        for plan in plans:
            sql = await _validate_or_repair(plan, sql_service, linked, stats)
            if sql is None:
                stats["validator_rejected"] += 1
                continue
            for attempt in range(SQL_MAX_RETRIES + 1):
                error = await executor.run(sql)
                if error is None:
                    return sql
                if attempt >= SQL_MAX_RETRIES:
                    break
                stats["repairs"] += 1
                plan.sql = sql
                try:
                    sql = (await sql_service.repair(plan, error, linked.schema_context)).sql
                except Exception:
                    break
        return None


async def main_async(args: argparse.Namespace) -> int:
    from config.config_manager import get_settings
    from config.container import container
    from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
    from src.modules.assistant.application.services.schema_linker import SchemaLinker
    from src.modules.assistant.application.services.sql_service import SQLService

    container.config.from_dict(get_settings().to_container_config())
    sql_service = SQLService(container.llm_service())
    linker = SchemaLinker()
    cases = load_jsonl(args.dataset)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    with psycopg2.connect(args.dsn) as connection:
        initialize_fixture(connection, args.fixture)
        analyzer = QueryAnalyzer(**fixture_catalogue(connection, args.timeout_ms))
        executor = FixtureExecutor(connection, args.timeout_ms)
        semaphore = asyncio.Semaphore(args.concurrency)
        for run in range(1, args.runs + 1):
            stats: dict[str, Any] = {
                "plans": [], "repairs": 0, "generation_failures": 0,
                "validator_errors": [], "validator_rejected": 0,
            }
            started = time.perf_counter()
            sqls = await asyncio.gather(*(
                predict(case, sql_service=sql_service, analyzer=analyzer, linker=linker,
                        executor=executor, semaphore=semaphore, stats=stats)
                for case in cases
            ))
            path = args.out_dir / f"run{run}.jsonl"
            with path.open("w", encoding="utf-8") as stream:
                for case, sql in zip(cases, sqls):
                    if sql:
                        stream.write(json.dumps({"case_id": case["id"], "sql": sql}, ensure_ascii=False) + "\n")
            summary = {
                "run": run,
                "predictions": sum(sql is not None for sql in sqls),
                "cases": len(cases),
                "repairs": stats["repairs"],
                "generation_failures": stats["generation_failures"],
                # Validator rejections by error code, and plans dropped after all repairs.
                "validator_errors": {
                    code: stats["validator_errors"].count(code)
                    for code in sorted(set(stats["validator_errors"]))
                },
                "validator_rejected_plans": stats["validator_rejected"],
                "multi_plan_cases": sum(count > 1 for count in stats["plans"]),
                "seconds": round(time.perf_counter() - started, 1),
                "file": str(path),
            }
            print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    configure_utf8_console()
    args = parse_args()
    if not args.dsn:
        print("Thiếu PostgreSQL DSN. Dùng --dsn hoặc AI_QC_BENCHMARK_DSN.", file=sys.stderr)
        return 2
    if args.runs < 1 or args.concurrency < 1:
        print("--runs và --concurrency phải lớn hơn 0.", file=sys.stderr)
        return 2
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
