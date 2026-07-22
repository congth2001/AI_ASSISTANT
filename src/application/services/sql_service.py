"""Generate and validate read-only PostgreSQL query plans."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.application.services.schema_linker import LinkedSchema
from src.domain.constants.prompt import SQLPrompt
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.interfaces.i_llm_service import ILLMService


@dataclass
class SQLQueryPlan:
    intent: str
    sql: str


_BLOCKED = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|REPLACE|EXEC|CALL|"
    r"COPY|GRANT|REVOKE|PRAGMA|ATTACH|VACUUM|ANALYZE)\b",
    re.IGNORECASE,
)
_COMMENTS = re.compile(r"(--|/\*|\*/)")
_SYSTEM_OBJECTS = re.compile(
    r"\b(pg_catalog|information_schema|pg_[a-z0-9_]+)\b",
    re.IGNORECASE,
)
_LOCKING = re.compile(
    r"\b(FOR\s+(UPDATE|SHARE)|SELECT\s+.+?\s+INTO\s+)\b",
    re.IGNORECASE | re.DOTALL,
)
_LEGACY_TABLES = re.compile(
    r"\b(invoice_customers|invoice_goods)\b",
    re.IGNORECASE,
)
_SELECT_STAR = re.compile(
    r"\bSELECT\s+(?:[a-z_][a-z0-9_]*\.)?\*",
    re.IGNORECASE,
)
_MAX_ROWS = 1000
_MAX_PLANS = 5


class SQLValidationError(Exception):
    pass


class SQLService:
    def __init__(self, llm_service: ILLMService):
        self.llm_service = llm_service

    async def generate(
        self,
        analyzed: AnalyzedQuery,
        linked: LinkedSchema,
    ) -> list[SQLQueryPlan]:
        prompt = self._build_generation_prompt(analyzed, linked)
        raw = await self.llm_service.generate_response(prompt)
        return self._parse(raw)

    async def generate_and_validate(
        self,
        analyzed: AnalyzedQuery,
        linked: LinkedSchema,
    ) -> list[SQLQueryPlan]:
        return self.validate_all(await self.generate(analyzed, linked))

    async def repair(
        self,
        plan: SQLQueryPlan,
        error: str,
        schema_context: str = "",
    ) -> SQLQueryPlan:
        raw = await self.llm_service.generate_response(
            SQLPrompt.repair_prompt(
                plan.sql,
                error,
                schema_context,
            )
        )
        plans = self._parse(raw)
        if not plans:
            raise SQLValidationError("LLM không thể tạo SQL sửa lỗi.")

        repaired = plans[0]
        repaired.intent = plan.intent
        repaired.sql = self.validate(repaired.sql)
        return repaired

    def validate_all(self, plans: list[SQLQueryPlan]) -> list[SQLQueryPlan]:
        if len(plans) > _MAX_PLANS:
            raise SQLValidationError(f"Chỉ cho phép tối đa {_MAX_PLANS} query plans.")
        for plan in plans:
            plan.sql = self.validate(plan.sql)
        return plans

    def validate(self, sql: str) -> str:
        sql = sql.strip().rstrip(";").strip()

        if not sql:
            raise SQLValidationError("SQL rỗng — LLM không sinh được query.")
        if ";" in sql:
            raise SQLValidationError("Chỉ cho phép một câu SQL.")
        if _COMMENTS.search(sql):
            raise SQLValidationError("SQL comment không được phép.")
        if not re.match(r"^(SELECT|WITH)\b", sql, re.IGNORECASE):
            raise SQLValidationError(
                "Chỉ cho phép SELECT hoặc CTE. " f"Câu SQL bắt đầu bằng: '{sql[:30]}'"
            )
        if _BLOCKED.search(sql):
            blocked = _BLOCKED.search(sql).group(0).upper()
            raise SQLValidationError(f"SQL chứa từ khóa bị cấm: {blocked}")
        if _SYSTEM_OBJECTS.search(sql):
            raise SQLValidationError("Không cho phép truy cập metadata hệ thống.")
        if _LOCKING.search(sql):
            raise SQLValidationError("Không cho phép khóa hoặc ghi dữ liệu từ SELECT.")
        if _LEGACY_TABLES.search(sql):
            legacy = _LEGACY_TABLES.search(sql).group(0)
            raise SQLValidationError(
                f"SQL sử dụng bảng legacy không còn tồn tại: {legacy}"
            )
        if _SELECT_STAR.search(sql):
            raise SQLValidationError(
                "Không cho phép SELECT *; phải liệt kê cột tường minh."
            )
        if "????" in sql:
            raise SQLValidationError("SQL còn chứa placeholder chưa resolve.")

        limit_match = re.search(r"\bLIMIT\s+(\d+)\b", sql, re.IGNORECASE)
        if limit_match and int(limit_match.group(1)) > _MAX_ROWS:
            sql = (
                sql[: limit_match.start(1)] + str(_MAX_ROWS) + sql[limit_match.end(1) :]
            )
        elif not limit_match:
            sql = f"{sql}\nLIMIT {_MAX_ROWS}"

        return sql

    @staticmethod
    def _build_generation_prompt(
        analyzed: AnalyzedQuery,
        linked: LinkedSchema,
    ) -> str:
        filters = json.dumps(
            linked.filter_hints,
            ensure_ascii=False,
            sort_keys=True,
        )
        sections = (
            SQLPrompt.GENERATION_RULES.rstrip(),
            f"LƯỢC ĐỒ CƠ SỞ DỮ LIỆU:\n{linked.schema_context.rstrip()}",
            "NGỮ CẢNH ĐÃ PHÂN TÍCH:\n"
            f"- bảng chính gợi ý: {linked.primary_table}\n"
            f"- thực thể: {linked.entity_summary}\n"
            f"- gợi ý bộ lọc: {filters}",
            f"CÂU HỎI NGƯỜI DÙNG:\n{analyzed.original_query}",
        )
        return "\n\n".join(sections)

    @staticmethod
    def _parse(raw: str) -> list[SQLQueryPlan]:
        """Parse the JSON contract, with a narrow SQL fallback for resilience."""
        raw = raw.strip()
        if not raw:
            return []

        items = SQLService._decode_json_payload(raw)
        if items is not None:
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                return []

            plans: list[SQLQueryPlan] = []
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                sql = item.get("sql")
                if not isinstance(sql, str) or not sql.strip():
                    continue
                intent = item.get("intent") or f"query_{index}"
                plans.append(
                    SQLQueryPlan(
                        intent=str(intent),
                        sql=sql.strip().rstrip(";").strip(),
                    )
                )
            return plans

        fenced = re.search(
            r"```(?:sql)?\s*(.*?)```",
            raw,
            re.IGNORECASE | re.DOTALL,
        )
        candidate = fenced.group(1).strip() if fenced else raw
        start = re.search(r"\b(?:WITH|SELECT)\b", candidate, re.IGNORECASE)
        if not start:
            return []

        sql = candidate[start.start() :].strip()
        if ";" in sql:
            sql = sql.split(";", 1)[0].strip()
        return [SQLQueryPlan(intent="query", sql=sql)]

    @staticmethod
    def _decode_json_payload(raw: str) -> Any | None:
        decoder = json.JSONDecoder()
        starts = sorted(
            position for token in ("[", "{") if (position := raw.find(token)) >= 0
        )
        for start in starts:
            try:
                payload, _ = decoder.raw_decode(raw[start:])
                return payload
            except json.JSONDecodeError:
                continue
        return None
