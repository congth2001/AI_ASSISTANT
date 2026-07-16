"""
Analytics pipeline — steps 4-7 của LLM-to-SQL pipeline.
  4. Schema Linking  — map entity → tên bảng/cột thực
  5. SQL Generation  — LLM sinh list[SQLQueryPlan], tự quyết bao nhiêu query
  6. SQL Validation  — safety layer, validate từng plan
  7. Execute & Format — chạy từng query trên PostgreSQL, gộp kết quả thành ngôn ngữ tự nhiên
"""
from typing import Tuple, List
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.application.services.schema_linker import SchemaLinker
from src.application.services.sql_service import SQLService, SQLQueryPlan, SQLValidationError
from src.infrastructure.repositories.analytics_repository import AnalyticsRepository

_SQL_MAX_RETRIES = 2


class AnalyticsUseCase:
    def __init__(
        self,
        analytics_repo: AnalyticsRepository,
        schema_linker  : SchemaLinker,
        sql_service    : SQLService,
    ):
        self.repo          = analytics_repo
        self.schema_linker = schema_linker
        self.sql_service   = sql_service

    async def execute(
        self, analyzed: AnalyzedQuery
    ) -> Tuple[List[str], str, bool, bool, str | None]:
        # ── Step 4: Schema Linking ────────────────────────────────────────
        linked = self.schema_linker.link(analyzed)

        # ── Step 5: SQL Generation — LLM quyết định số lượng query ───────
        plans = await self.sql_service.generate(analyzed, linked)
        if not plans:
            return [], "Không thể xác định câu query phù hợp cho câu hỏi này.", False, False, "sql_generation_failed"

        # ── Step 6: Validation — kiểm tra từng plan ───────────────────────
        try:
            plans = self.sql_service.validate_all(plans)
        except SQLValidationError as e:
            return [], "Không thể tạo truy vấn dữ liệu an toàn.", False, False, "sql_validation_failed"

        # ── Step 7: Execute & Format ──────────────────────────────────────
        content, has_data, execution_ok = await self._execute_and_format(plans, analyzed)
        return (
            [plan.sql for plan in plans],
            content,
            execution_ok,
            has_data,
            None if execution_ok else "sql_execution_failed",
        )

    # ─────────────────────────────
    # Private helpers
    # ─────────────────────────────

    async def _execute_and_format(
        self, plans: list[SQLQueryPlan], analyzed: AnalyzedQuery
    ) -> tuple[str, bool, bool]:
        results: list[tuple[str, list, list[str]]] = []
        has_data = False
        successful_queries = 0
        for plan in plans:
            last_error: str | None = None
            for attempt in range(_SQL_MAX_RETRIES + 1):
                try:
                    rows, cols = await self.repo.execute_sql(plan.sql)
                    results.append((plan.intent, rows, cols))
                    successful_queries += 1
                    has_data = has_data or bool(rows)
                    last_error = None
                    break
                except Exception as e:
                    last_error = str(e)
                    if attempt < _SQL_MAX_RETRIES:
                        try:
                            plan = await self.sql_service.repair(plan, last_error)
                        except Exception:
                            break
            if last_error is not None:
                results.append((plan.intent, [], [f"[Lỗi: {last_error}]"]))

        return self._format_results(results, analyzed), has_data, successful_queries > 0

    @staticmethod
    def _format_results(
        results: list[tuple[str, list, list[str]]],
        analyzed: AnalyzedQuery,
    ) -> str:
        sections: list[str] = [f"Câu hỏi: {analyzed.original_query}", ""]

        for intent, rows, cols in results:
            sections.append(f"[{intent}]")

            if not rows:
                sections.append("  Không có dữ liệu.")
                sections.append("")
                continue

            # Bỏ qua nếu cols là error message
            if len(cols) == 1 and cols[0].startswith("[Lỗi"):
                sections.append(f"  {cols[0]}")
                sections.append("")
                continue

            # Header + rows
            col_widths = [
                max(len(c), max((len(_fmt_cell(r[i])) for r in rows), default=0))
                for i, c in enumerate(cols)
            ]
            header = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(cols))
            sep    = "-+-".join("-" * w for w in col_widths)
            sections.append(f"  {header}")
            sections.append(f"  {sep}")
            for row in rows:
                cells = [_fmt_cell(row[i]).ljust(col_widths[i]) for i in range(len(cols))]
                sections.append("  " + " | ".join(cells))

            # Tóm tắt max/min nếu có nhiều dòng và cột doanh_thu
            revenue_col = next((c for c in cols if "doanh_thu" in c or "tong" in c), None)
            if revenue_col and len(rows) > 2:
                idx = cols.index(revenue_col)
                try:
                    max_row = max(rows, key=lambda r: float(r[idx]) if r[idx] is not None else 0)
                    min_row = min(rows, key=lambda r: float(r[idx]) if r[idx] is not None else 0)
                    sections.append(f"  → Cao nhất: {dict(zip(cols, max_row))}")
                    sections.append(f"  → Thấp nhất: {dict(zip(cols, min_row))}")
                except (TypeError, ValueError):
                    pass

            sections.append("")

        return "\n".join(sections).rstrip()


def _fmt_cell(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float):
        return f"{val:,.0f}"
    return str(val)
