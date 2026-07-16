import re
from typing import Literal

from src.domain.constants.intent_extractor import IntentExtractor
from src.domain.constants.query_intent import QueryIntent
from src.domain.interfaces.i_llm_service import ILLMService

Route = Literal["text_to_sql", "rag", "hybrid"]


class IntentClassifier:
    """Layer-1 routing classifier.

    Primary path  : LLM call with structured JSON output (accurate, handles edge cases).
    Fallback path : lightweight rule-based matching (used when LLM call fails).
    """

    def __init__(self, llm_service: ILLMService):
        self._llm = llm_service

    async def classify(self, query: str) -> Route:
        try:
            route = await self._llm.classify_route(query)
            if route not in {"text_to_sql", "rag", "hybrid"}:
                raise ValueError(f"Unsupported agent route: {route!r}")
            return route
        except Exception:
            return self._classify_rule_based(query.lower().strip())

    # ─────────────────────────────
    # Rule-based fallback
    # ─────────────────────────────

    _ANALYTICS_INTENTS = frozenset({
        QueryIntent.REVENUE,
        QueryIntent.RANKING,
        QueryIntent.COMPARISON,
    })
    _ENTITY_RAG_INTENTS = frozenset({
        QueryIntent.CUSTOMER,
        QueryIntent.DEBT,
        QueryIntent.INVOICE,
    })
    _AGGREGATION_KEYWORDS = (
        "ngày có doanh thu", "ngày có doanh số", "ngày có lợi nhuận",
        "cao nhất", "thấp nhất", "lớn nhất", "nhỏ nhất",
        "so sánh", "so với", "tăng trưởng", "biến động",
        "tổng", "trung bình", "tỷ lệ", "phần trăm", "chiếm",
        "doanh thu", "doanh số", "lợi nhuận", "lợi nhuận gộp", "lợi nhuận ròng", "biên lợi nhuận", "biên lãi", "biên lãi gộp", "biên lãi ròng",
        "tăng", "giảm", "tăng trưởng", "biến động", "xu hướng", "trend", "so sánh", "so với",
        "top", "hạng", "xếp hạng", "thứ hạng", "vị trí", "đứng đầu", "đứng cuối", "cao nhất", "thấp nhất", "lớn nhất", "nhỏ nhất", "tốt nhất",
    )
    _TIME_SIGNALS = (
        "tháng", "năm", "quý", "tuần", "ngày",
        "hôm nay", "hôm qua", "hôm nào", "tháng nào", "gần đây",
        "trong tháng", "trong năm", "trong quý", "trong tuần", "trong ngày",
        "từ tháng", "từ năm", "từ quý", "từ tuần", "từ ngày",
        "đến tháng", "đến năm", "đến quý", "đến tuần", "đến ngày", 
        "trước", "sau", "kể từ", "tính đến", "tính từ", "tính trong", "tính đến nay",
    )

    def _classify_rule_based(self, text: str) -> Route:
        needs_analytics = self._needs_analytics(text)
        needs_entity_rag = self._needs_entity_rag(text)
        if needs_analytics and needs_entity_rag:
            return "hybrid"
        if needs_analytics:
            return "text_to_sql"
        return "rag"

    def _needs_analytics(self, text: str) -> bool:
        if any(kw in text for kw in self._AGGREGATION_KEYWORDS):
            return True
        if re.search(r"\btop\s+\d+", text):
            return True
        for intent, (_rank, keywords) in IntentExtractor.INTENT_PATTERNS.items():
            if intent not in self._ANALYTICS_INTENTS:
                continue
            if any(kw in text for kw in keywords):
                if any(ts in text for ts in self._TIME_SIGNALS):
                    return True
        return False

    def _needs_entity_rag(self, text: str) -> bool:
        for intent, (_rank, keywords) in IntentExtractor.INTENT_PATTERNS.items():
            if intent not in self._ENTITY_RAG_INTENTS:
                continue
            if any(kw in text for kw in keywords):
                return True
        return False
