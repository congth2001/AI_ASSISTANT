"""
Text-to-SQL pipeline — steps 4-7 của LLM-to-SQL pipeline.
  4. Schema Linking  — map entity → tên bảng/cột thực
  5. SQL Generation  — LLM sinh list[SQLQueryPlan], tự quyết bao nhiêu query
  6. SQL Validation  — safety layer, validate từng plan
  7. Execute & Format — chạy từng query trên PostgreSQL, gộp kết quả thành ngôn ngữ tự nhiên
"""

import asyncio
import logging
import re
import uuid
from typing import List, Tuple

from src.common.errors import ExternalServiceError
from src.modules.assistant.application.services.data_block import (
    DATA_BEGIN,
    DATA_END,
    MAX_CELL_CHARS,
    format_cell,
    format_number,
    neutralize_delimiters,
)
from src.modules.assistant.application.services.schema_linker import LinkedSchema, SchemaLinker
from src.modules.assistant.application.services.sql_service import (
    MAX_SQL_PLANS,
    SQLQueryPlan,
    SQLService,
)
from src.modules.assistant.domain.entities.analyzed_query import AnalyzedQuery
from src.modules.assistant.domain.errors import (
    SQLExecutionFailedError,
    SQLGenerationFailedError,
    SQLPlanValidationFailedError,
    SQLValidationError,
)
from src.modules.assistant.domain.ports.i_sql_executor import ISQLExecutor

logger = logging.getLogger(__name__)

_SQL_MAX_RETRIES = 2

# Limits for what is shown to the answering LLM (the executor may return up to 1000 rows).
_MAX_PROMPT_ROWS_PER_PLAN = 50
_MAX_PROMPT_CHARS = 24_000
_MAX_REPAIR_ERROR_CHARS = 500

# Shared with the Overview report data block (see services/data_block.py).
_DATA_BEGIN = DATA_BEGIN
_DATA_END = DATA_END
_MAX_CELL_CHARS = MAX_CELL_CHARS
_neutralize_delimiters = neutralize_delimiters
_fmt_number = format_number
_fmt_cell = format_cell
_REPORT_CONTEXT_MARKER = "\nNgữ cảnh báo cáo đang xem:"
_UUID_TEXT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
# Column names such as ten_khach_hang, customer_name, product_name.
_NAME_COLUMN = re.compile(r"(?:^|_)(?:ten|name)(?:_|$)")
_ID_REQUEST = re.compile(r"\b(?:mã|id|uuid)\b", re.IGNORECASE)


class TextToSQLUseCase:
    def __init__(
        self,
        sql_executor: ISQLExecutor,
        schema_linker: SchemaLinker,
        sql_service: SQLService,
    ):
        self.sql_executor = sql_executor
        self.schema_linker = schema_linker
        self.sql_service = sql_service

    async def execute(
        self, analyzed: AnalyzedQuery
    ) -> Tuple[List[str], str, bool, bool, str | None]:
        # ── Step 4: Schema Linking ────────────────────────────────────────
        linked = self.schema_linker.link(analyzed)

        # ── Step 5: SQL Generation — LLM quyết định số lượng query ───────
        try:
            plans = await self.sql_service.generate(analyzed, linked)
        except ExternalServiceError:
            logger.warning("SQL generation failed: LLM service error", exc_info=True)
            plans = []
        if not plans:
            return (
                [],
                SQLGenerationFailedError().message,
                False,
                False,
                SQLGenerationFailedError.code,
            )

        # ── Step 6: Validation — mỗi plan được kiểm tra độc lập ──────────
        plans, rejected = await self._validate_plans(plans, linked)
        if not plans:
            return (
                [],
                SQLPlanValidationFailedError().message,
                False,
                False,
                SQLPlanValidationFailedError.code,
            )

        # ── Step 7: Execute & Format ──────────────────────────────────────
        content, has_data, execution_ok = await self._execute_and_format(
            plans,
            analyzed,
            linked,
            rejected_intents=rejected,
        )
        return (
            [plan.sql for plan in plans],
            content,
            execution_ok,
            has_data,
            None if execution_ok else SQLExecutionFailedError.code,
        )

    # ─────────────────────────────
    # Private helpers
    # ─────────────────────────────

    async def _validate_plans(
        self,
        plans: list[SQLQueryPlan],
        linked: LinkedSchema,
    ) -> tuple[list[SQLQueryPlan], list[str]]:
        """Keep valid plans; repair each rejected plan with the validator's message."""
        if len(plans) > MAX_SQL_PLANS:
            logger.warning(
                "LLM returned %d SQL plans; keeping the first %d", len(plans), MAX_SQL_PLANS
            )
            plans = plans[:MAX_SQL_PLANS]

        # Repairs are LLM round-trips; run them concurrently so several rejected
        # plans do not add up to the agent node's time budget.
        outcomes = await asyncio.gather(*(self._validate_or_repair(plan, linked) for plan in plans))
        valid = [checked for checked in outcomes if checked is not None]
        rejected = [plan.intent for plan, checked in zip(plans, outcomes) if checked is None]
        return valid, rejected

    async def _validate_or_repair(
        self,
        plan: SQLQueryPlan,
        linked: LinkedSchema,
    ) -> SQLQueryPlan | None:
        try:
            return self.sql_service.validate_all([plan])[0]
        except SQLValidationError as exc:
            reason = exc.message
            logger.warning("SQL plan %r rejected by validator: %s", plan.intent, reason)
            logger.debug("Rejected SQL for %r: %s", plan.intent, plan.sql)
        # A plan the validator rejected never ran, so it gets the same number of
        # repair rounds as a plan the database rejected.
        return await self._repair(plan, reason, linked, attempts=_SQL_MAX_RETRIES)

    async def _repair(
        self,
        plan: SQLQueryPlan,
        reason: str,
        linked: LinkedSchema,
        attempts: int = 1,
    ) -> SQLQueryPlan | None:
        """Ask the LLM for a fixed plan; ``None`` when it cannot be repaired.

        When the validator rejects a repaired SQL, the next round sees that SQL and
        the new reason, not the original query again.
        """
        failed = SQLQueryPlan(intent=plan.intent, sql=plan.sql)
        for _ in range(attempts):
            try:
                draft = await self.sql_service.draft_repair(
                    failed, _clean_error(reason), linked.schema_context
                )
            except SQLValidationError as exc:
                logger.warning("SQL repair for %r rejected: %s", plan.intent, exc.message)
                return None
            except ExternalServiceError:
                logger.warning("SQL repair for %r failed: LLM service error", plan.intent, exc_info=True)
                return None
            except Exception:
                logger.exception("SQL repair for %r failed unexpectedly", plan.intent)
                return None
            try:
                plan.sql = self.sql_service.validate(draft.sql)
            except SQLValidationError as exc:
                logger.warning("SQL repair for %r rejected: %s", plan.intent, exc.message)
                logger.debug("Rejected repaired SQL for %r: %s", plan.intent, draft.sql)
                failed, reason = draft, exc.message
                continue
            return plan
        return None

    async def _execute_and_format(
        self,
        plans: list[SQLQueryPlan],
        analyzed: AnalyzedQuery,
        linked: LinkedSchema,
        rejected_intents: list[str] | None = None,
    ) -> tuple[str, bool, bool]:
        results: list[tuple[str, list, list[str]]] = []
        has_data = False
        successful_queries = 0
        # Each plan uses its own connection and repair loop; running them concurrently
        # keeps a multi-plan business analysis within the agent node's timeout.
        outcomes = await asyncio.gather(*(self._run_plan(plan, linked) for plan in plans))
        for plan, outcome in zip(plans, outcomes):
            if outcome is None:
                results.append((plan.intent, [], [SQLExecutionFailedError().message]))
                continue
            rows, cols = outcome
            results.append((plan.intent, rows, cols))
            successful_queries += 1
            has_data = has_data or bool(rows)
        for intent in rejected_intents or []:
            results.append((intent, [], [SQLPlanValidationFailedError().message]))

        return self._format_results(results, analyzed), has_data, successful_queries > 0

    async def _run_plan(
        self,
        plan: SQLQueryPlan,
        linked: LinkedSchema,
    ) -> tuple[list, list[str]] | None:
        """Run one plan; repair and retry only when the database rejected the SQL itself."""
        for attempt in range(_SQL_MAX_RETRIES + 1):
            try:
                return await self.sql_executor.execute_sql(plan.sql)
            except SQLValidationError as exc:
                # The executor reports defects of the query itself with a sanitized message.
                logger.warning(
                    "SQL plan %r failed (attempt %d): %s", plan.intent, attempt + 1, exc.message
                )
                if attempt >= _SQL_MAX_RETRIES:
                    return None
                repaired = await self._repair(plan, exc.message, linked)
                if repaired is None:
                    return None
            except Exception:
                # Timeouts, lost connections and unknown errors: retrying or sending the
                # raw exception text to the LLM would not help and may leak internals.
                logger.exception("SQL plan %r failed with a non-SQL error", plan.intent)
                return None
        return None

    @staticmethod
    def _format_results(
        results: list[tuple[str, list, list[str]]],
        analyzed: AnalyzedQuery,
    ) -> str:
        question = analyzed.original_query.partition(_REPORT_CONTEXT_MARKER)[0]
        # Asked for a code/ID explicitly: show identifier columns as returned.
        keep_ids = bool(_ID_REQUEST.search(question))
        failure_messages = {
            SQLExecutionFailedError().message,
            SQLPlanValidationFailedError().message,
        }
        sections: list[str] = [
            f"Câu hỏi: {_neutralize_delimiters(question)}",
            "",
            _DATA_BEGIN,
        ]
        budget = _MAX_PROMPT_CHARS

        for index, (intent, rows, cols) in enumerate(results, start=1):
            sections.append(f"[sql:{index}] [{_neutralize_delimiters(intent)}]")

            if not rows and len(cols) == 1 and cols[0] in failure_messages:
                sections.append(f"  {cols[0]}")
                sections.append("")
                continue

            if not rows:
                sections.append("  Không có dữ liệu.")
                sections.append("")
                continue

            # Compact rows: no column padding or separator line, and UUID columns are
            # dropped when a name column already identifies every row. Both only cost
            # tokens (a 50-row customer table shrank from ~2.5k to ~0.8k tokens) and the
            # answering LLM tended to copy raw UUIDs into the reply.
            visible = _visible_columns(rows, cols, keep_ids=keep_ids)
            cols = [cols[i] for i in visible]
            rows = [tuple(row[i] for i in visible) for row in rows]
            header = " | ".join(cols)
            sections.append(header)
            budget -= len(header) + 1

            displayed = 0
            for row in rows[:_MAX_PROMPT_ROWS_PER_PLAN]:
                line = " | ".join(_fmt_cell(value) for value in row)
                if budget - len(line) < 0:
                    break
                sections.append(line)
                budget -= len(line) + 1
                displayed += 1
            if displayed < len(rows):
                sections.append(
                    f"  (đã cắt {len(rows) - displayed} dòng; chỉ hiển thị {displayed}/{len(rows)} dòng đầu)"
                )

            # Prefer the business value metric over count/quantity columns. The extremes
            # come from every returned row, not just the displayed ones.
            revenue_col = next(
                (c for c in cols if "doanh_thu" in c),
                None,
            ) or next(
                (c for c in cols if "cong_no" in c or "tong_no" in c),
                None,
            )
            if revenue_col and len(rows) > 2:
                idx = cols.index(revenue_col)
                try:
                    max_row = max(
                        rows, key=lambda r: r[idx] if r[idx] is not None else 0
                    )
                    min_row = min(
                        rows, key=lambda r: r[idx] if r[idx] is not None else 0
                    )
                    sections.append(f"  → Cao nhất: {_fmt_row(cols, max_row)}")
                    sections.append(f"  → Thấp nhất: {_fmt_row(cols, min_row)}")
                except (TypeError, ValueError):
                    pass

            sections.append("")

        while sections and sections[-1] == "":
            sections.pop()
        sections.append(_DATA_END)
        return "\n".join(sections)


def _is_uuid(value) -> bool:
    return isinstance(value, uuid.UUID) or (isinstance(value, str) and bool(_UUID_TEXT.match(value)))


def _visible_columns(rows: list, cols: list[str], *, keep_ids: bool) -> list[int]:
    """Indexes of the columns shown to the answering LLM.

    A UUID column is hidden only when a name column is present and no name maps to
    two different UUIDs in this result; otherwise the UUID is what tells rows apart.
    """
    every_column = list(range(len(cols)))
    if keep_ids:
        return every_column
    uuid_columns = {
        index for index in every_column
        if any(row[index] is not None for row in rows)
        and all(row[index] is None or _is_uuid(row[index]) for row in rows)
    }
    name_columns = [
        index for index in every_column
        if index not in uuid_columns and _NAME_COLUMN.search(cols[index].lower())
    ]
    if not uuid_columns or not name_columns:
        return every_column
    ids_by_name: dict[tuple, set[tuple]] = {}
    for row in rows:
        name = tuple(row[index] for index in name_columns)
        ids = tuple(str(row[index]) for index in sorted(uuid_columns))
        ids_by_name.setdefault(name, set()).add(ids)
        if len(ids_by_name[name]) > 1:
            return every_column
    return [index for index in every_column if index not in uuid_columns]


def _clean_error(message: str) -> str:
    """Collapse and bound an error message before it is shown to the repair LLM."""
    return " ".join(message.split())[:_MAX_REPAIR_ERROR_CHARS]


def _fmt_row(cols: list[str], row) -> dict[str, str]:
    return {col: _fmt_cell(row[i]) for i, col in enumerate(cols)}
