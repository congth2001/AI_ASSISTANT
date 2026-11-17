"""Generate and validate read-only PostgreSQL query plans."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.common.domain.time import now_vietnam
from src.modules.assistant.application.services.schema_linker import LinkedSchema
from src.modules.assistant.application.prompts.sql_prompts import SQLPrompt
from src.modules.assistant.domain.entities.analyzed_query import AnalyzedQuery
from src.modules.assistant.domain.ports.i_llm_service import ILLMService
from src.modules.assistant.domain.errors import (
    EmptySQLQueryError,
    MultipleSQLStatementsError,
    SQLCommentsForbiddenError,
    SQLKeywordForbiddenError,
    SQLLegacyTableError,
    SQLMetadataForbiddenError,
    SQLPlaceholderError,
    SQLPlanLimitError,
    SQLReadOnlyRequiredError,
    SQLRepairFailedError,
    SQLSelectStarForbiddenError,
    SQLTableNotAllowedError,
    SQLValidationError,
    SQLWriteOrLockForbiddenError,
)


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
_MAX_ROWS = 1000  # keep in sync with PostgresSQLExecutor.MAX_ROWS
_MAX_PLANS = 5
MAX_SQL_PLANS = _MAX_PLANS

# Generated SQL runs with the application's database role, so the validator is
# the boundary that keeps it inside sales data (no users, tokens or chat logs).
ALLOWED_SQL_TABLES = frozenset({
    "customers",
    "sales_invoices",
    "sales_invoice_lines",
    "sales_returns",
    "sales_return_lines",
    "customer_debt_transactions",
})
# Non-sales tables of this database. Their names are rejected anywhere in the
# query, so a CTE cannot shadow them (inside its own body the name still
# resolves to the real table). Every ORM table must be in exactly one of the two
# sets; tests enforce this when a model is added.
RESTRICTED_SQL_TABLES = frozenset({
    "users",
    "refresh_tokens",
    "conversations",
    "messages",
    "alembic_version",
})
_ALLOWED_SCHEMA = "public"
_ALLOWED_TABLE_FUNCTIONS = frozenset({"generate_series", "unnest"})
# Every call `name(...)` must use a function from this allowlist. Functions that take
# SQL text or a table name as a string (query_to_xml, table_to_xml, cursor_to_xml,
# dblink, ...) or reach outside the query (pg_*, lo_*, set_config, current_setting)
# are denied simply by not being listed; they cannot be reached with a quoted or
# schema-qualified spelling either, because the name is compared after normalization.
_ALLOWED_FUNCTIONS = frozenset({
    # aggregates
    "sum", "count", "avg", "min", "max", "stddev", "stddev_pop", "stddev_samp",
    "variance", "var_pop", "var_samp", "string_agg", "array_agg", "bool_and",
    "bool_or", "percentile_cont", "percentile_disc", "mode",
    # window
    "row_number", "rank", "dense_rank", "ntile", "lag", "lead", "first_value",
    "last_value", "nth_value", "percent_rank", "cume_dist",
    # conditional
    "coalesce", "nullif", "greatest", "least", "cast",
    # numeric
    "abs", "round", "ceil", "ceiling", "floor", "trunc", "mod", "div", "power",
    "sqrt", "sign", "exp", "ln", "log", "log10",
    # date/time
    "date_trunc", "date_part", "extract", "age", "make_date", "make_interval",
    "to_char", "to_date", "now", "timezone",
    # text
    "lower", "upper", "length", "char_length", "trim", "ltrim", "rtrim", "btrim",
    "substring", "substr", "concat", "concat_ws", "left", "right", "position",
    "strpos", "split_part", "initcap", "lpad", "rpad", "overlay",
    # row sources already used by generated queries
    *_ALLOWED_TABLE_FUNCTIONS,
})
# Type names that take modifiers, e.g. x::numeric(12, 2); also valid as conversion calls.
_TYPE_NAMES_WITH_MODIFIERS = frozenset({
    "numeric", "decimal", "varchar", "char", "character", "timestamp",
    "timestamptz", "time", "timetz", "interval", "date",
})
# Words that may be directly followed by "(" without being a function call.
_KEYWORDS_BEFORE_PAREN = frozenset({
    "select", "from", "where", "and", "or", "not", "in", "on", "as", "join",
    "exists", "any", "all", "some", "case", "when", "then", "else", "end", "by",
    "having", "union", "intersect", "except", "distinct", "values", "over",
    "filter", "within", "group", "using", "limit", "offset", "fetch", "between",
    "like", "ilike", "similar", "is", "lateral", "with", "recursive",
    "materialized", "array", "partition", "order", "rows", "range", "groups",
    "to", "escape", "only", "row",
})
# Session/role information is available without parentheses.
_FORBIDDEN_BARE_IDENTIFIERS = frozenset({
    "current_user", "session_user", "current_role", "current_catalog", "current_schema",
})
# FROM is also part of these expressions and is not a table reference there.
_FROM_EXPRESSION_FUNCTIONS = frozenset({"extract", "substring", "trim", "overlay", "position"})
_TOKEN = re.compile(
    r"""
    (?P<string>'(?:[^']|'')*')
    | (?P<dollar>\$[a-z_0-9]*\$)
    | (?P<ident>"(?:[^"]|"")+"(?:\s*\.\s*"(?:[^"]|"")+"|\s*\.\s*[a-z_][a-z0-9_$]*)*
               |[a-z_][a-z0-9_$]*(?:\s*\.\s*(?:"(?:[^"]|"")+"|[a-z_][a-z0-9_$]*))*)
    | (?P<punct>[(),])
    """,
    re.IGNORECASE | re.VERBOSE,
)
_CTE_NAME = re.compile(
    r"(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)([a-z_][a-z0-9_]*)\s*(?:\([^()]*\)\s*)?AS\s+(?:NOT\s+)?(?:MATERIALIZED\s+)?\(",
    re.IGNORECASE,
)
_FROM_ITEM_PREFIXES = frozenset({"lateral", "only"})
_LIMIT_SCAN = re.compile(
    r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|[()]|[A-Za-z_][A-Za-z0-9_$]*|\d+|\S"""
)
_ALIAS_STOP_WORDS = frozenset({
    "where", "group", "order", "limit", "offset", "having", "window", "union",
    "intersect", "except", "join", "inner", "left", "right", "full", "cross",
    "natural", "on", "using", "fetch", "for", "lateral",
})


def _normalize_identifier(identifier: str) -> list[str]:
    parts = re.split(r'\s*\.\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', identifier.strip())
    return [
        part[1:-1].replace('""', '"').lower() if part.startswith('"') else part.lower()
        for part in parts
    ]


def _tokenize(sql: str) -> list[tuple[str, str]]:
    # E'..' strings treat backslash as an escape, so their end differs between this
    # scanner and PostgreSQL; text after a backslash-quote could be hidden from every check.
    if re.search(r"(?<![\w$])e\s*'", sql, re.IGNORECASE):
        raise SQLKeywordForbiddenError(blocked="E'...'")
    tokens: list[tuple[str, str]] = []
    position = 0
    for match in _TOKEN.finditer(sql):
        # A quote that no string/identifier pattern consumed means the quoting is
        # malformed or ambiguous, so the text around it cannot be trusted.
        skipped = sql[position : match.start()]
        if "'" in skipped or '"' in skipped:
            raise SQLKeywordForbiddenError(blocked="quote")
        position = match.end()
        kind = match.lastgroup
        if kind == "dollar":
            # Dollar quoting can hide arbitrary text from the checks below.
            raise SQLTableNotAllowedError(table=match.group())
        if kind != "string":
            tokens.append((kind, match.group()))
    rest = sql[position:]
    if "'" in rest or '"' in rest:
        raise SQLKeywordForbiddenError(blocked="quote")
    return tokens


def _matching_paren(tokens: list[tuple[str, str]], start: int) -> int:
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index][1] == "(":
            depth += 1
        elif tokens[index][1] == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(tokens) - 1


def _check_table_reference(identifier: str, cte_names: set[str]) -> None:
    parts = _normalize_identifier(identifier)
    if len(parts) == 2 and parts[0] == _ALLOWED_SCHEMA:
        parts = parts[1:]
    if len(parts) != 1:
        raise SQLTableNotAllowedError(table=identifier)
    name = parts[0]
    if name not in ALLOWED_SQL_TABLES and name not in cte_names:
        raise SQLTableNotAllowedError(table=identifier)


def _check_from_items(
    tokens: list[tuple[str, str]],
    index: int,
    cte_names: set[str],
    alias_lists: set[int],
) -> None:
    """Validate the comma-separated FROM/JOIN items that start at ``index``.

    ``alias_lists`` collects the token index of every alias that carries a column
    list (``AS d(ngay)``), which looks like a call but is not one.
    """
    while index < len(tokens):
        kind, value = tokens[index]
        if kind == "ident" and value.lower() in _FROM_ITEM_PREFIXES:
            index += 1
            continue
        if value == "(":
            # Subquery: its own FROM clauses are visited by the outer scan.
            index = _matching_paren(tokens, index) + 1
        elif kind == "ident":
            next_value = tokens[index + 1][1] if index + 1 < len(tokens) else ""
            if next_value == "(":
                if value.lower() not in _ALLOWED_TABLE_FUNCTIONS:
                    raise SQLTableNotAllowedError(table=value)
                index = _matching_paren(tokens, index + 1) + 1
            else:
                _check_table_reference(value, cte_names)
                index += 1
        else:
            return
        # Optional alias, written with or without AS.
        if index < len(tokens) and tokens[index][1].lower() == "as":
            index += 1
        if (
            index < len(tokens)
            and tokens[index][0] == "ident"
            and tokens[index][1].lower() not in _ALIAS_STOP_WORDS
        ):
            index += 1
            if index < len(tokens) and tokens[index][1] == "(":
                alias_lists.add(index - 1)
                index = _matching_paren(tokens, index) + 1  # column alias list
        if index < len(tokens) and tokens[index][1] == ",":
            index += 1
            continue
        return


def _is_cte_definition(tokens: list[tuple[str, str]], index: int) -> bool:
    """``name(col, ...) AS [NOT] [MATERIALIZED] (`` right after WITH/RECURSIVE/','."""
    if index == 0 or tokens[index - 1][1].lower() not in {"with", "recursive", ","}:
        return False
    cursor = _matching_paren(tokens, index + 1) + 1
    if cursor >= len(tokens) or tokens[cursor][1].lower() != "as":
        return False
    cursor += 1
    while cursor < len(tokens) and tokens[cursor][1].lower() in {"not", "materialized"}:
        cursor += 1
    return cursor < len(tokens) and tokens[cursor][1] == "("


def _check_function_calls(tokens: list[tuple[str, str]], alias_lists: set[int]) -> None:
    """Reject any ``name(`` call whose name is not in the function allowlist."""
    for index, (kind, value) in enumerate(tokens):
        if kind != "ident":
            continue
        parts = _normalize_identifier(value)
        name = parts[0] if len(parts) == 1 else ""
        if name in _FORBIDDEN_BARE_IDENTIFIERS:
            raise SQLKeywordForbiddenError(blocked=name.upper())
        if index + 1 >= len(tokens) or tokens[index + 1][1] != "(":
            continue
        if (
            value.lower() in _KEYWORDS_BEFORE_PAREN  # unquoted: IN (...), EXISTS (...)
            or name in _ALLOWED_FUNCTIONS
            or name in _TYPE_NAMES_WITH_MODIFIERS
            or index in alias_lists
            or _is_cte_definition(tokens, index)
        ):
            continue
        # `AS name(` is a column alias list, never a call.
        if index > 0 and tokens[index - 1][1].lower() == "as" and not value.startswith('"'):
            continue
        raise SQLKeywordForbiddenError(blocked=f"{value}()")


def check_allowed_tables(sql: str) -> None:
    """Reject table references outside ALLOWED_SQL_TABLES/CTEs and non-allowlisted calls."""
    tokens = _tokenize(sql)
    sql_without_strings = re.sub(r"'(?:[^']|'')*'", "''", sql)
    cte_names = {name.lower() for name in _CTE_NAME.findall(sql_without_strings)}
    alias_lists: set[int] = set()
    paren_functions: list[str] = []
    previous = ""
    for index, (kind, value) in enumerate(tokens):
        lowered = value.lower()
        if kind == "ident" and RESTRICTED_SQL_TABLES.intersection(_normalize_identifier(value)):
            raise SQLTableNotAllowedError(table=value)
        if value == "(":
            paren_functions.append(previous)
        elif value == ")":
            if paren_functions:
                paren_functions.pop()
        elif kind == "ident" and lowered == "table":
            # Bare "TABLE name" is shorthand for SELECT * FROM name.
            raise SQLTableNotAllowedError(table=value)
        elif kind == "ident" and lowered in {"from", "join"}:
            in_expression = paren_functions and paren_functions[-1] in _FROM_EXPRESSION_FUNCTIONS
            if not (lowered == "from" and (in_expression or previous == "distinct")):
                _check_from_items(tokens, index + 1, cte_names, alias_lists)
        previous = lowered if kind == "ident" else value
    _check_function_calls(tokens, alias_lists)


def _apply_row_limit(sql: str) -> str:
    """Bound the rows of the outermost query, whatever limits its subqueries carry."""
    outer: list[tuple[str, int, int]] = []
    depth = 0
    for match in _LIMIT_SCAN.finditer(sql):
        text = match.group()
        if text == "(":
            depth += 1
        elif text == ")":
            depth -= 1
        elif depth == 0:
            outer.append((text.upper(), match.start(), match.end()))
    words = [text for text, _, _ in outer]
    limits = [i for i, word in enumerate(words) if word == "LIMIT"]
    if not limits and "FETCH" not in words:
        return f"{sql}\nLIMIT {_MAX_ROWS}"
    if len(limits) == 1 and "FETCH" not in words:
        i = limits[0]
        simple = (
            i + 1 < len(words)
            and words[i + 1].isdigit()
            and (i + 2 == len(words) or words[i + 2] == "OFFSET")
        )
        if simple:
            if int(words[i + 1]) > _MAX_ROWS:
                _, start, end = outer[i + 1]
                return sql[:start] + str(_MAX_ROWS) + sql[end:]
            return sql
    # LIMIT ALL/NULL/expressions, FETCH FIRST or a repeated LIMIT are not rewritten in
    # place; cap the result of the whole statement instead.
    return f"SELECT * FROM (\n{sql}\n) AS q\nLIMIT {_MAX_ROWS}"

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
            raise SQLRepairFailedError()

        repaired = plans[0]
        repaired.intent = plan.intent
        repaired.sql = self.validate(repaired.sql)
        return repaired

    def validate_all(self, plans: list[SQLQueryPlan]) -> list[SQLQueryPlan]:
        if len(plans) > _MAX_PLANS:
            raise SQLPlanLimitError(max_plans=_MAX_PLANS)
        for plan in plans:
            plan.sql = self.validate(plan.sql)
        return plans

    def validate(self, sql: str) -> str:
        sql = sql.strip().rstrip(";").strip()

        if not sql:
            raise EmptySQLQueryError()
        if ";" in sql:
            raise MultipleSQLStatementsError()
        if _COMMENTS.search(sql):
            raise SQLCommentsForbiddenError()
        if not re.match(r"^(SELECT|WITH)\b", sql, re.IGNORECASE):
            raise SQLReadOnlyRequiredError(query_prefix=sql[:30])
        if _BLOCKED.search(sql):
            blocked = _BLOCKED.search(sql).group(0).upper()
            raise SQLKeywordForbiddenError(blocked=blocked)
        if _SYSTEM_OBJECTS.search(sql):
            raise SQLMetadataForbiddenError()
        if _LOCKING.search(sql):
            raise SQLWriteOrLockForbiddenError()
        if _LEGACY_TABLES.search(sql):
            legacy = _LEGACY_TABLES.search(sql).group(0)
            raise SQLLegacyTableError(legacy=legacy)
        check_allowed_tables(sql)
        if _SELECT_STAR.search(sql):
            raise SQLSelectStarForbiddenError()
        if "????" in sql:
            raise SQLPlaceholderError()

        return _apply_row_limit(sql)

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
            f"- ngày hiện tại tại Việt Nam: {now_vietnam().date().isoformat()}\n"
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

        # Malformed/truncated JSON is not a raw SQL response. Extracting SELECT
        # out of its quoted string can execute an incomplete fragment of a plan.
        if raw.startswith(("[", "{")) or re.match(r"```json\b", raw, re.IGNORECASE):
            return []

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
