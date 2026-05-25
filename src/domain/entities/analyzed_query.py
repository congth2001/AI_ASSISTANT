from dataclasses import dataclass, field
from datetime import datetime

from typing import Optional

from src.domain.value_objects.doc_type import DocType
from src.domain.value_objects.query_intent import QueryIntent
from src.domain.entities.time_filter import TimeFilter
from src.domain.value_objects.aggregation_type import AggregationType


@dataclass
class AnalyzedQuery:
    original_query : str
    normalized     : str                        # lowercase, strip

    intents        : list[QueryIntent]          # có thể có nhiều intent
    primary_intent : QueryIntent                # intent chính

    time_filter    : TimeFilter = field(default_factory=TimeFilter)
    customer_name  : Optional[str] = None      # tên KH đã match
    customer_score : int = 0                   # fuzzy match score (0-100)
    category_name  : Optional[str] = None      # danh mục hàng
    product_name   : Optional[str] = None      # sản phẩm cụ thể
    invoice_id     : Optional[str] = None      # số phiếu cụ thể

    doc_types      : list[DocType] = field(default_factory=list)
    milvus_filter  : str = ""                  # filter expression cho Milvus
    needs_llm_fallback: bool = False           # True nếu rule-based không đủ tự tin

    needs_analytics  : bool = False
    aggregation_type : AggregationType = field(default_factory=lambda: AggregationType.NONE)
    top_n            : int = 10                # số lượng kết quả cho TOP_CUSTOMERS
