# Số lượng kết quả trả về theo intent — RANKING cần nhiều hơn để so sánh
from src.domain.value_objects.query_intent import QueryIntent

class SearchConfig:
    """Configuration for search behavior based on query intent"""
    TOP_K_BY_INTENT: dict[QueryIntent, int] = {
        QueryIntent.REVENUE    : 5,
        QueryIntent.CUSTOMER   : 3,
        QueryIntent.DEBT       : 3,
        QueryIntent.PRODUCT    : 5,
        QueryIntent.CATEGORY   : 5,
        QueryIntent.RANKING    : 10,   # cần nhiều để LLM xếp hạng
        QueryIntent.COMPARISON : 8,    # cần docs nhiều kỳ để so sánh
        QueryIntent.INVOICE    : 1,    # tra cứu 1 phiếu cụ thể
        QueryIntent.UNKNOWN    : 5,
    }

    # ef (search quality param của HNSW) — cao hơn = chính xác hơn nhưng chậm hơn
    EF_BY_INTENT: dict[QueryIntent, int] = {
        QueryIntent.RANKING    : 200,  # cần độ chính xác cao
        QueryIntent.COMPARISON : 150,
        QueryIntent.INVOICE    : 50,   # filter chặt → ít cần ef cao
    }
    DEFAULT_EF = 100