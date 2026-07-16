"""
SQL Service — gộp Step 5 (Generation) + Step 6 (Validation).
LLM sinh list[SQLQueryPlan], sau đó validate an toàn trước khi execute.
"""
from __future__ import annotations
import re
import json
from dataclasses import dataclass
from src.domain.interfaces.i_llm_service import ILLMService
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.constants.prompt import SQLPrompt 
from src.application.services.schema_linker import LinkedSchema


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class SQLQueryPlan:
    """Một SQL query đơn lẻ trong kế hoạch trả lời câu hỏi."""
    intent: str   # nhãn ngắn mô tả mục tiêu (vd: "ngay_cao_nhat")
    sql: str      # câu PostgreSQL SELECT đã validate


# ── Constants ──────────────────────────────────────────────────────────────────

_BLOCKED = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|REPLACE|EXEC|CALL|COPY|GRANT|REVOKE|PRAGMA|ATTACH|VACUUM|ANALYZE)\b",
    re.IGNORECASE,
)
_COMMENTS = re.compile(r"(--|/\*|\*/)")
_SYSTEM_OBJECTS = re.compile(r"\b(pg_catalog|information_schema|pg_[a-z0-9_]+)\b", re.IGNORECASE)
_LOCKING = re.compile(r"\b(FOR\s+(UPDATE|SHARE)|SELECT\s+.+?\s+INTO\s+)\b", re.IGNORECASE | re.DOTALL)
_MAX_ROWS = 1000


# ── Exception ──────────────────────────────────────────────────────────────────

class SQLValidationError(Exception):
    pass


# ── Combined service ───────────────────────────────────────────────────────────

class SQLService:
    """
    Gộp Generation (Step 5) + Validation (Step 6).

    Luồng chính:
        plans = await service.generate_and_validate(analyzed, linked)
    Hoặc gọi riêng từng bước:
        plans = await service.generate(analyzed, linked)
        plans = service.validate_all(plans)
    """

    def __init__(self, llm_service: ILLMService):
        self.llm_service = llm_service

    # ── Generation ─────────────────────────────────────────────────────────────

    async def generate(
        self, analyzed: AnalyzedQuery, linked: LinkedSchema
    ) -> list[SQLQueryPlan]:
        filter_desc = (
            ", ".join(f"{k}={v}" for k, v in linked.filter_hints.items()) or "none"
        )

        prompt = (
            f"Question: {analyzed.original_query}\n"
            f"FILTERS (đã extract): {filter_desc}\n"
            f"{SQLPrompt.BRIEF_PROMPT}\n"
        )

        raw = await self.llm_service.generate_response(prompt)
        return self._parse(raw)

    async def generate_and_validate(
        self, analyzed: AnalyzedQuery, linked: LinkedSchema
    ) -> list[SQLQueryPlan]:
        """Sinh SQL rồi validate ngay — đây là entry point thông thường."""
        plans = await self.generate(analyzed, linked)
        return self.validate_all(plans)

    async def repair(self, plan: SQLQueryPlan, error: str) -> SQLQueryPlan:
        """Gửi SQL lỗi kèm thông báo lỗi về LLM để tự sửa. Raise SQLValidationError nếu không sửa được."""
        prompt = SQLPrompt.repair_prompt(plan.sql, error)
        raw = await self.llm_service.generate_response(prompt)
        plans = self._parse(raw)
        if not plans:
            raise SQLValidationError("LLM không thể tạo SQL sửa lỗi.")
        repaired = plans[0]
        repaired.intent = plan.intent
        repaired.sql = self.validate(repaired.sql)
        return repaired

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate_all(self, plans: list[SQLQueryPlan]) -> list[SQLQueryPlan]:
        """Validate từng SQLQueryPlan. Raise SQLValidationError on first failure."""
        for plan in plans:
            plan.sql = self.validate(plan.sql)
        return plans

    def validate(self, sql: str) -> str:
        """
        Trả về SQL đã clean nếu hợp lệ.
        Raise SQLValidationError nếu không an toàn hoặc sai cú pháp.
        """
        sql = sql.strip().rstrip(";").strip()

        if not sql:
            raise SQLValidationError("SQL rỗng — LLM không sinh được query.")

        if ";" in sql:
            raise SQLValidationError("Chỉ cho phép một câu SQL.")

        if _COMMENTS.search(sql):
            raise SQLValidationError("SQL comment không được phép.")

        if not re.match(r"^(SELECT|WITH)\b", sql, re.IGNORECASE):
            raise SQLValidationError(
                f"Chỉ cho phép SELECT hoặc CTE. Câu SQL bắt đầu bằng: '{sql[:30]}'"
            )

        if _BLOCKED.search(sql):
            blocked = _BLOCKED.search(sql).group(0).upper()
            raise SQLValidationError(f"SQL chứa từ khóa bị cấm: {blocked}")

        if _SYSTEM_OBJECTS.search(sql):
            raise SQLValidationError("Không cho phép truy cập metadata hệ thống.")

        if _LOCKING.search(sql):
            raise SQLValidationError("Không cho phép khóa hoặc ghi dữ liệu từ SELECT.")

        # Bound result size for both generated SELECT and CTE queries.
        limit_match = re.search(r"\bLIMIT\s+(\d+)\b", sql, re.IGNORECASE)
        if limit_match and int(limit_match.group(1)) > _MAX_ROWS:
            sql = sql[:limit_match.start(1)] + str(_MAX_ROWS) + sql[limit_match.end(1):]
        elif not limit_match:
            sql = f"{sql}\nLIMIT {_MAX_ROWS}"

        return sql

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse(raw: str) -> list[SQLQueryPlan]:
        """Parse JSON array từ LLM. Fallback trích SQL thuần nếu parse thất bại."""
        raw = raw.strip()
        raw = re.sub(r"^```(?:json|sql)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw.strip())
        bracket = raw.find("[")
        if bracket > 0:
            raw = raw[bracket:]

        try:
            items = json.loads(raw)
            if isinstance(items, dict):
                items = [items]
            return [
                SQLQueryPlan(
                    intent=item.get("intent", f"query_{i}"),
                    sql=item["sql"].strip().rstrip(";"),
                )
                for i, item in enumerate(items)
                if "sql" in item
            ]
        except (json.JSONDecodeError, KeyError):
            sql_match = re.search(r"(SELECT\s.+?)(?:;|$)", raw, re.DOTALL | re.IGNORECASE)
            if sql_match:
                return [SQLQueryPlan(intent="query", sql=sql_match.group(1).strip())]
            return []
