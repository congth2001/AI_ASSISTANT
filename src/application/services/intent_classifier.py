import re
from typing import Literal

from src.domain.constants.intent_extractor import IntentExtractor
from src.domain.constants.query_intent import QueryIntent
from src.domain.interfaces.i_llm_service import ILLMService

Route = Literal["text_to_sql", "rag", "hybrid", "conversation"]


class IntentClassifier:
    """Layer-1 routing classifier.

    Primary path  : LLM call with structured JSON output (accurate, handles edge cases).
    Fallback path : lightweight rule-based matching (used when LLM call fails).
    """

    def __init__(self, llm_service: ILLMService):
        self._llm = llm_service

    async def classify(self, query: str) -> Route:
        normalized = query.lower().strip()
        # Small talk rõ ràng không cần tốn một LLM call và tuyệt đối không được
        # chạy SQL/RAG chỉ vì không có dữ liệu nghiệp vụ.
        if self._is_conversation(normalized):
            return "conversation"
        deterministic_route = self._classify_rule_based(normalized)
        if deterministic_route != "conversation":
            return deterministic_route
        try:
            route = await self._llm.classify_route(query)
            if route not in {"text_to_sql", "rag", "hybrid", "conversation"}:
                raise ValueError(f"Unsupported agent route: {route!r}")
            return route
        except Exception:
            return self._classify_rule_based(normalized)

    # ─────────────────────────────
    # Rule-based fallback
    # ─────────────────────────────

    _ANALYTICS_INTENTS = frozenset({
        QueryIntent.REVENUE,
        QueryIntent.RANKING,
        QueryIntent.COMPARISON,
    })
    _ENTITY_DATA_INTENTS = frozenset({
        QueryIntent.CUSTOMER,
        QueryIntent.DEBT,
        QueryIntent.PRODUCT,
        QueryIntent.CATEGORY,
        QueryIntent.INVOICE,
    })
    _POLICY_KEYWORDS = (
        "luật", "quy định", "chính sách", "nghị định", "thông tư",
        "thuế", "vat", "hóa đơn điện tử", "pháp luật", "đổi trả",
        "bảo hành", "xử phạt", "mức phạt",
    )
    _CONVERSATION_PATTERNS = (
        r"(?:(?:xin\s+)?chào|hello|hi|alo)(?:\s+(?:bạn|buổi\s+sáng|buổi\s+trưa|buổi\s+tối))?(?:\s+(?:nhé|nha))?",
        r"(?:cảm|cám)\s+ơn(?:\s+bạn)?(?:\s+rất\s+nhiều|\s+nhiều|\s+nhé|\s+nha)?",
        r"(?:không\s+có\s+gì|rất\s+vui|tuyệt\s+vời|hay\s+quá)",
        r"(?:(?:mình|tôi)\s+)?(?:ok|okay|oke|ừ|uh|vâng|dạ|được|đồng\s+ý|đúng|hiểu)(?:\s+(?:rồi|nhé|nha))?",
        r"(?:tạm\s+biệt|hẹn\s+gặp\s+lại|bye|goodbye)",
        r"(?:bạn\s+)?(?:là\s+ai|tên\s+gì|khỏe\s+không)",
    )
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
        needs_entity_data = self._needs_entity_data(text)
        needs_policy = any(
            self._contains_keyword(text, keyword)
            for keyword in self._POLICY_KEYWORDS
        )
        needs_data = needs_analytics or needs_entity_data
        if needs_data and needs_policy:
            return "hybrid"
        if needs_data:
            return "text_to_sql"
        if needs_policy:
            return "rag"
        return "conversation"

    def _needs_analytics(self, text: str) -> bool:
        if any(self._contains_keyword(text, kw) for kw in self._AGGREGATION_KEYWORDS):
            return True
        if re.search(r"\btop\s+\d+", text):
            return True
        for intent, (_rank, keywords) in IntentExtractor.INTENT_PATTERNS.items():
            if intent not in self._ANALYTICS_INTENTS:
                continue
            if any(self._contains_keyword(text, kw) for kw in keywords):
                if any(ts in text for ts in self._TIME_SIGNALS):
                    return True
        return False

    def _needs_entity_data(self, text: str) -> bool:
        for intent, (_rank, keywords) in IntentExtractor.INTENT_PATTERNS.items():
            if intent not in self._ENTITY_DATA_INTENTS:
                continue
            if any(self._contains_keyword(text, kw) for kw in keywords):
                return True
        return False

    @classmethod
    def _is_conversation(cls, text: str) -> bool:
        normalized = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return any(
            re.fullmatch(pattern, normalized, flags=re.IGNORECASE)
            for pattern in cls._CONVERSATION_PATTERNS
        )

    @staticmethod
    def _contains_keyword(text: str, keyword: str) -> bool:
        """Match complete words/phrases, avoiding collisions such as 'anh' in 'doanh'."""
        return re.search(
            rf"(?<!\w){re.escape(keyword)}(?!\w)",
            text,
            flags=re.UNICODE,
        ) is not None
