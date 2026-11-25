"""Prompt layout that keeps OpenAI's automatic prefix cache hitting.

The cache reuses the longest identical prefix of a request. Anything that changes per
turn (today's date, filters, question) must come after the static rules; one dynamic
character near the top turns the ~7k-token SQL prompt from ~94% cached to uncached.
"""
from datetime import date
from unittest.mock import patch

import pytest

from src.modules.assistant.application.prompts.sql_prompts import SQLPrompt
from src.modules.assistant.application.services import sql_service
from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.application.services.schema_linker import SchemaLinker
from src.modules.assistant.application.services.sql_service import SQLService
from src.modules.assistant.infrastructure.llm.openai_adapter import OpenAIAdapter


def _generation_prompt(question: str, today: date) -> str:
    analyzed = QueryAnalyzer().analyze(question)
    with patch.object(sql_service, "now_vietnam") as now:
        now.return_value.date.return_value = today
        return SQLService._build_generation_prompt(analyzed, SchemaLinker().link(analyzed))


def _common_prefix(a: str, b: str) -> int:
    for index, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return index
    return min(len(a), len(b))


def test_generation_prompt_starts_with_the_static_rules():
    prompt = _generation_prompt("Doanh thu tháng 3 năm 2025", date(2026, 11, 25))
    assert prompt.startswith(SQLPrompt.GENERATION_RULES.rstrip())


def test_date_and_question_do_not_change_the_static_prefix():
    first = _generation_prompt("Doanh thu tháng 3 năm 2025 là bao nhiêu?", date(2026, 11, 25))
    second = _generation_prompt("Top 5 khách hàng còn nợ nhiều nhất", date(2027, 1, 2))
    assert _common_prefix(first, second) >= len(SQLPrompt.GENERATION_RULES.rstrip())


def test_static_rules_contain_no_runtime_values():
    rules = SQLPrompt.GENERATION_RULES
    assert date.today().isoformat() not in rules
    assert "{" not in rules.replace('{"', "").replace("{{", "")  # no unformatted placeholders


@pytest.mark.parametrize("today", [date(2026, 11, 25), date(2027, 6, 1)])
def test_sql_generation_calls_share_one_prompt_cache_key(today):
    adapter = OpenAIAdapter(api_key="test", client=object())
    keys = {
        adapter._prompt_cache_key(adapter._build_messages(_generation_prompt(question, today), None))
        for question in ("Doanh thu tháng 3 năm 2025", "Lịch sử công nợ của Công ty An Phát")
    }
    assert len(keys) == 1


def test_different_static_prefixes_get_different_keys_and_no_prompt_text():
    adapter = OpenAIAdapter(api_key="test", client=object())
    sql_key = adapter._prompt_cache_key(adapter._build_messages(SQLPrompt.GENERATION_RULES, None))
    other_key = adapter._prompt_cache_key(adapter._build_messages("Xin chào", None))
    assert sql_key != other_key
    assert sql_key.startswith("ai-assistant-") and len(sql_key) == len("ai-assistant-") + 16
