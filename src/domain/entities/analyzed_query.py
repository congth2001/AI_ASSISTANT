from dataclasses import dataclass, field
from datetime import datetime

from typing import Optional

from src.domain.constants.doc_type import DocType
from src.domain.constants.query_intent import QueryIntent
from src.domain.entities.time_filter import TimeFilter
from src.domain.constants.aggregation_type import AggregationType
from src.domain.constants.query_strategy import QueryStrategy


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
    category_score : int = 0                   # fuzzy match score (0-100)
    invoice_id     : Optional[str] = None      # số phiếu cụ thể

    doc_types      : list[DocType] = field(default_factory=list)
    milvus_filter  : str = ""                  # filter expression cho Milvus

    # 0.0 (không chắc) → 1.0 (chắc chắn) — quality signal của rule-based analysis
    routing_confidence: float = 1.0

    aggregation_type : AggregationType = field(default_factory=lambda: AggregationType.NONE)
    query_strategy   : QueryStrategy = field(default_factory=lambda: QueryStrategy.SIMPLE)
    top_n            : int = 10                # số lượng kết quả cho TOP_N
