from datetime import datetime, timedelta

from src.domain.constants.doc_type import DocType
from src.domain.constants.query_intent import QueryIntent


class IntentExtractor:
    # Intent keywords - mapping từ intent sang các pattern nhận diện trong câu
    INTENT_PATTERNS: dict[QueryIntent, tuple[int, list[str]]] = {
        QueryIntent.REVENUE: (2, [
            "doanh thu", "bán được", "bán ra", "thu được", "thu về",
            "doanh số", "tổng tiền", "bán hàng", "xuất bán",
        ]),
        QueryIntent.PROFIT: (2, [
            "lợi nhuận", "lãi", "lãi ròng", "lãi gộp",
            "thu lãi", "lãi được",
        ]),
        QueryIntent.CUSTOMER: (2, [
            "khách hàng", "khách", "anh", "chị", "cô", "bác", "chú",
            "hồ sơ", "lịch sử mua", "thông tin khách",
        ]),
        QueryIntent.DEBT: (2, [
            "công nợ", "còn nợ", "nợ lại", "ghi nợ", "chưa trả",
            "nợ bao nhiêu", "công", "đang nợ", "dư nợ",
        ]),
        QueryIntent.PRODUCT: (2, [
            "xi măng", "gạch", "sắt", "vôi", "sơn", "ống", "dây điện",
            "giá", "đơn giá", "bao nhiêu tiền", "mặt hàng", "hàng hóa",
            "sản phẩm", "tên hàng", "loại hàng",
        ]),
        QueryIntent.CATEGORY: (2, [
            "danh mục", "loại", "nhóm hàng", "ngành hàng",
        ]),
        QueryIntent.RANKING: (3, [
            "top", "nhiều nhất", "ít nhất", "bán chạy", "cao nhất",
            "thấp nhất", "đứng đầu", "xếp hạng", "hạng", "nhất", "xếp hạng",
        ]),
        QueryIntent.COMPARISON: (3, [
            "so sánh", "so với", "tăng", "giảm", "hơn", "kém",
            "tháng trước", "kỳ trước", "năm ngoái", "biến động",
            "tăng trưởng", "xu hướng", "sắp xếp", "tăng dần", "giảm dần",
        ]),
        QueryIntent.INVOICE: (1, [
            "số phiếu", "phiếu xuất", "hóa đơn", "đơn hàng",
            "xb", "px",
        ]),
    }

    # Tháng bằng chữ — tiếng Việt
    MONTH_WORDS = {
        "một": 1, "hai": 2, "ba": 3, "tư": 4, "bốn": 4,
        "năm": 5, "sáu": 6, "bảy": 7, "tám": 8,
        "chín": 9, "mười": 10, "mười một": 11, "mười hai": 12,
        "giêng": 1, "chạp": 12,
    }

    # Thời gian tương đối
    NOW = datetime.now()
    _YESTERDAY = NOW - timedelta(days=1)
    RELATIVE_TIME = {
        "hôm nay"     : (NOW.day, NOW.month, NOW.year),
        "hôm qua"     : (_YESTERDAY.day, _YESTERDAY.month, _YESTERDAY.year),
        "tháng này"   : (None, NOW.month, NOW.year),
        "tháng hiện tại": (None, NOW.month, NOW.year),
        "tháng trước" : (None, NOW.month - 1 if NOW.month > 1 else 12,
                            NOW.year if NOW.month > 1 else NOW.year - 1),
        "năm nay"     : (None, None, NOW.year),
        "năm ngoái"   : (None, None, NOW.year - 1),
        "năm trước"   : (None, None, NOW.year - 1),
        "quý này"     : (None, None, None),   # sẽ tính từ tháng hiện tại
        "quý trước"   : (None, None, None),
    }

    # Prefix tên khách — dùng để normalize trước khi fuzzy match
    CUSTOMER_PREFIXES = [
        "anh", "chị", "cô", "chú", "bác", "ông", "bà",
        "em", "con", "cháu", "thím", "cậu", "dì", "mợ",
    ]

    # Doc type mapping theo intent
    INTENT_TO_DOC_TYPES: dict[QueryIntent, list[DocType]] = {
        QueryIntent.REVENUE    : [DocType.PERIOD_SUMMARY, DocType.CATEGORY_PERIOD],
        QueryIntent.PROFIT     : [DocType.PERIOD_SUMMARY],
        QueryIntent.CUSTOMER   : [DocType.CUSTOMER],
        QueryIntent.DEBT       : [DocType.CUSTOMER],
        QueryIntent.PRODUCT    : [DocType.PRODUCT],
        QueryIntent.CATEGORY   : [DocType.CATEGORY, DocType.CATEGORY_PERIOD],
        QueryIntent.RANKING    : [DocType.PERIOD_SUMMARY, DocType.PRODUCT,
                                    DocType.CUSTOMER],
        QueryIntent.COMPARISON : [DocType.PERIOD_SUMMARY, DocType.CATEGORY_PERIOD],
        QueryIntent.INVOICE    : [DocType.TRANSACTION],
        QueryIntent.UNKNOWN    : [DocType.PERIOD_SUMMARY, DocType.PRODUCT,
                                    DocType.CUSTOMER],
    }

    # Stop words phổ biến trong câu hỏi để loại bỏ khi phân tích intent
    QUERY_STOP_WORDS: set[str] = {
        "mua", "gì", "gần", "đây", "bao", "nhiêu", "hỏi", "về",
        "còn", "nợ", "tiền", "có", "không", "làm", "được", "cho",
        "với", "ở", "tại", "của", "và", "hay", "thế", "nào",
        "nhiều", "ít", "thêm", "đã", "chưa", "rồi", "đang",
        "ngày", "hôm", "nay", "qua", "gần", "đây", "lần",
    }

    CUSTOMER_INTENTS: set[str] = {
        QueryIntent.CUSTOMER, QueryIntent.DEBT,
        QueryIntent.INVOICE,  QueryIntent.RANKING,
    }

    # Địa danh / xóm / từ chung xuất hiện ở nhiều tên KH
    # Những token này KHÔNG đủ để định danh 1 KH cụ thể
    LOCATION_TOKENS: set[str] = {
        # Xóm số
        "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10",
        "xóm 1", "xóm 2", "xóm 3", "xóm 4", "xóm 5", "xóm 6", "xóm 7", "xóm 8", "xóm 9", "xóm 10",
        # Địa danh thực tế trong data
        "cao", "trai", "đồng", "hòa", "dương", "thượng", "hạ", "tam", "lộng",
        "dân", "mới", "gọc", "vân", "hống", "me", "đoài", "đông", "tây", "nam", "bắc",
        "dương", "hà", "trường", "thụy", "hưng", "việt", "ninh", "chính",
    }