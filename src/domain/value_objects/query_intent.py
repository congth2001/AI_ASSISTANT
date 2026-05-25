from enum import Enum
from typing import Optional


class QueryIntent(Enum):
    """Enumeration of possible query intents"""
    REVENUE    = "revenue"     # doanh thu, bán được bao nhiêu
    PROFIT     = "profit"      # lợi nhuận, lãi
    CUSTOMER   = "customer"    # thông tin, lịch sử KH
    DEBT       = "debt"        # công nợ, còn nợ bao nhiêu
    PRODUCT    = "product"     # mặt hàng, giá cả
    CATEGORY   = "category"    # danh mục, loại hàng
    RANKING    = "ranking"     # top, bán chạy nhất, nhiều nhất
    COMPARISON = "comparison"  # so sánh kỳ này vs kỳ trước
    INVOICE    = "invoice"     # tra cứu phiếu xuất cụ thể
    UNKNOWN    = "unknown"      # không xác định được intent, cần fallback LLM
