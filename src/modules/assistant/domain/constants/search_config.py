# Số lượng kết quả trả về theo intent — RANKING cần nhiều hơn để so sánh
from src.modules.assistant.domain.constants.query_intent import QueryIntent

class SearchConfig:
    """Configuration for search behavior based on query intent"""
    TOP_K_BY_INTENT: dict[QueryIntent, int] = {
        QueryIntent.REVENUE    : 10,
        QueryIntent.CUSTOMER   : 6,
        QueryIntent.DEBT       : 6,
        QueryIntent.PRODUCT    : 10,
        QueryIntent.CATEGORY   : 10,
        QueryIntent.RANKING    : 20,   # cần nhiều để LLM xếp hạng
        QueryIntent.COMPARISON : 16,    # cần docs nhiều kỳ để so sánh
        QueryIntent.INVOICE    : 5,    # tra cứu 1 phiếu cụ thể
        QueryIntent.UNKNOWN    : 10,    # fallback cho các query không xác định
    }

    # ef (search quality param của HNSW) — cao hơn = chính xác hơn nhưng chậm hơn
    EF_BY_INTENT: dict[QueryIntent, int] = {
        QueryIntent.RANKING    : 200,  # cần độ chính xác cao
        QueryIntent.COMPARISON : 150,
        QueryIntent.INVOICE    : 50,   # filter chặt → ít cần ef cao
    }
    DEFAULT_EF = 100

    HISTORY_WINDOW = 5  # số lượng turn gần nhất để contextualize query
    # Câu trả lời dựa trên dữ liệu (SQL/RAG/hybrid) đã có số liệu mới và câu hỏi đã được
    # làm rõ, nên mỗi tin lịch sử chỉ cần ý chính; tin dài (bảng Markdown) bị cắt.
    DATA_HISTORY_MESSAGE_CHARS = 500