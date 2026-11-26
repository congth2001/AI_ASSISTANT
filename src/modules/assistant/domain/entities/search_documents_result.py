from dataclasses import dataclass

from src.modules.assistant.domain.entities.analyzed_query import AnalyzedQuery
from src.modules.assistant.domain.entities.search_result import SearchResult


@dataclass
class SearchDocumentsResult:
    results        : list[SearchResult]
    analyzed_query : AnalyzedQuery
    used_fallback  : bool
    # Mã lỗi hạ tầng (vd. 'vector_store_query') khi kho vector lỗi; None nếu tìm kiếm chạy bình thường.
    # Phân biệt "không có tài liệu phù hợp" (results rỗng, error_code None) với "không tìm được".
    error_code     : str | None = None
