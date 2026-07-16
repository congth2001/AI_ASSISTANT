import os
import sys
import time
import json
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import re
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.entities.time_filter import TimeFilter
from src.domain.constants.doc_type import DocType
from src.domain.constants.query_intent import QueryIntent
from src.domain.constants.intent_extractor import IntentExtractor
from src.domain.repositories.i_invoice_customer_repository import IInvoiceCustomerRepository
from src.domain.repositories.i_invoice_good_repository import IInvoiceGoodRepository
from rapidfuzz import fuzz, process


class QueryAnalyzer:
    """
    Phân tích câu hỏi tiếng Việt → AnalyzedQuery.

    Không phụ thuộc vào bất kỳ external service nào.
    Toàn bộ rule-based + fuzzy matching.
    """

    TTL_SECONDS = 60 * 60  # refresh entity lists every 1 hour

    def __init__(
        self,
        customer_repo: IInvoiceCustomerRepository | None = None,
        good_repo: IInvoiceGoodRepository | None = None,
        customer_names: list[str] | None = None,
        category_names: list[str] | None = None,
        fuzzy_threshold: int = 75,
    ):
        self.fuzzy_threshold  = fuzzy_threshold
        self._customer_repo   = customer_repo
        self._good_repo       = good_repo
        self._loaded_at: float | None = None
        self._set_entity_lists(customer_names or [], category_names or [])

    async def ensure_fresh(self) -> None:
        """Reload entity lists from DB if TTL has expired."""
        if self._customer_repo is None or self._good_repo is None:
            return
        now = time.monotonic()
        if self._loaded_at is not None and now - self._loaded_at < self.TTL_SECONDS:
            return
        customers = await self._customer_repo.list(limit=50000)
        customer_names = list({c["name"] for c in customers if c.get("name")})
        category_names = await self._good_repo.list_categories()
        self._set_entity_lists(customer_names, category_names)
        self._loaded_at = time.monotonic()

    def load_entities(
        self,
        customer_names: list[str],
        category_names: list[str],
    ) -> None:
        self._set_entity_lists(customer_names, category_names)
        self._loaded_at = time.monotonic()

    def _set_entity_lists(
        self,
        customer_names: list[str],
        category_names: list[str],
    ) -> None:
        self.customer_names   = customer_names
        self._norm_customers  = [self._normalize_name(n) for n in customer_names]
        self.category_names   = category_names
        self._norm_categories = [n.lower().strip() for n in category_names]

    # ─────────────────────────────
    # Public API
    # ─────────────────────────────

    def analyze(self, query: str) -> AnalyzedQuery:
        normalized = query.lower().strip()

        result = AnalyzedQuery(
            original_query = query,
            normalized     = normalized,
            intents        = [],
            primary_intent = QueryIntent.UNKNOWN,
        )

        self._extract_intents(result)
        # self._extract_customer_name(result)
        self._extract_time(result)
        self._extract_invoice_id(result)
        self._resolve_doc_types(result)
        self._build_milvus_filter(result)

        return result

    # ─────────────────────────────
    # Step 1: Intent classification
    # ─────────────────────────────

    def _extract_intents(self, result: AnalyzedQuery) -> None:
        text = result.normalized
        matched: list[tuple[QueryIntent, int]] = []

        for intent, (rank, keywords) in IntentExtractor.INTENT_PATTERNS.items():
            rank_score = 0
            for kw in keywords:
                if not kw in text:
                    continue
                rank_score += rank
            if rank_score > 0:
                matched.append((intent, rank_score))

        if not matched:
            result.intents        = [QueryIntent.UNKNOWN]
            result.primary_intent = QueryIntent.UNKNOWN
            return

        # Sắp xếp theo score giảm dần
        matched.sort(key=lambda x: x[1], reverse=True)
        result.intents        = [m[0] for m in matched]
        result.primary_intent = matched[0][0]

    # ─────────────────────────────
    # Step 2: Time extraction
    # ─────────────────────────────

    def _extract_time(self, result: AnalyzedQuery) -> None:
        text = result.normalized
        tf   = TimeFilter()

        # Relative time trước
        for phrase, (day, month, year) in IntentExtractor.RELATIVE_TIME.items():
            if phrase in text:
                tf.day = day
                tf.month = month
                tf.year  = year
                if "quý này" in phrase:
                    tf.quarter = (IntentExtractor.NOW.month - 1) // 3 + 1
                    tf.month   = None
                elif "quý trước" in phrase:
                    q = (IntentExtractor.NOW.month - 1) // 3 + 1
                    tf.quarter = q - 1 if q > 1 else 4
                    tf.year    = IntentExtractor.NOW.year if q > 1 else IntentExtractor.NOW.year - 1
                    tf.month   = None
                result.time_filter = tf
                return

        # Quý: "quý 1", "q1", "quý i"
        q_match = re.search(
            r"qu[yỳ]\s*([1-4]|[iI]{1,3}[vV]?|[vV])",
            text,
        )
        if q_match:
            raw = q_match.group(1)
            quarter_map = {"i": 1, "ii": 2, "iii": 3, "iv": 4,
                            "v": 5, "1": 1, "2": 2, "3": 3, "4": 4}
            tf.quarter = quarter_map.get(raw.lower(), 0) or int(raw)

        # Năm: "năm 2024", "2024", "/24"
        y_match = re.search(r"(?:năm\s*)?(?:20(\d{2})|/(\d{2}))\b", text)
        if y_match:
            suffix = y_match.group(1) or y_match.group(2)
            tf.year = 2000 + int(suffix)

        # Tháng dạng số: "tháng 3", "t3", "tháng 3/2024"
        m_match = re.search(
            r"(?:tháng\s*|t)([1-9]|1[0-2])(?:/(\d{2,4}))?",
            text,
        )
        if m_match:
            tf.month = int(m_match.group(1))
            if m_match.group(2):
                yr = m_match.group(2)
                tf.year = 2000 + int(yr) if len(yr) == 2 else int(yr)

        # Tháng dạng chữ: "tháng ba", "tháng mười hai"
        if not tf.month:
            for word, num in IntentExtractor.MONTH_WORDS.items():
                if f"tháng {word}" in text:
                    tf.month = num
                    break

        result.time_filter = tf

    # ─────────────────────────────
    # Step 3: Invoice ID
    # ─────────────────────────────

    def _extract_invoice_id(self, result: AnalyzedQuery) -> None:
        # Pattern: XB24169-0125, PX-001, ...
        match = re.search(
            r"\b([Xx][Bb]\d{5}-\d{4}|[Pp][Xx][-\s]?\d+)\b",
            result.original_query,
        )
        if match:
            result.invoice_id     = match.group(1).upper()
            result.primary_intent = QueryIntent.INVOICE

    # ─────────────────────────────
    # Step 4: Resolve doc_types
    # ─────────────────────────────

    def _resolve_doc_types(self, result: AnalyzedQuery) -> None:
        base = IntentExtractor.INTENT_TO_DOC_TYPES.get(result.primary_intent, [])

        # Tinh chỉnh thêm dựa trên entity đã extract
        extra: list[DocType] = []

        if result.customer_name and DocType.CUSTOMER not in base:
            extra.append(DocType.CUSTOMER)

        if result.invoice_id and DocType.TRANSACTION not in base:
            extra.append(DocType.TRANSACTION)

        if result.category_name:
            if not result.time_filter.is_empty:
                # Có cả danh mục + thời gian → category_period
                if DocType.CATEGORY_PERIOD not in base:
                    extra.append(DocType.CATEGORY_PERIOD)
            else:
                if DocType.CATEGORY not in base:
                    extra.append(DocType.CATEGORY)

        result.doc_types = base + extra

    # ─────────────────────────────
    # Step 5: Build Milvus filter
    # ─────────────────────────────

    def _build_milvus_filter(self, result: AnalyzedQuery) -> None:
        parts: list[str] = []

        # doc_type filter — OR giữa các type cần search
        if result.doc_types:
            type_exprs = [f'doc_type == "{dt.value}"' for dt in result.doc_types]
            parts.append(f"({' || '.join(type_exprs)})")

        # Time filter
        time_expr = result.time_filter.to_milvus_expr()
        if time_expr:
            parts.append(time_expr)

        # Customer filter — sanitize bỏ ký tự đặc biệt trước khi đưa vào filter
        if result.customer_name:
            cid = result.customer_name.strip().lower()
            cid = re.sub(r"[^\w\s]", "", cid)
            cid = re.sub(r"\s+", "_", cid).strip("_")
            parts.append(f'customer_id == "{cid}"')

        # Debt filter — chỉ search KH đang nợ
        if result.primary_intent == QueryIntent.DEBT:
            parts.append("co_no == true")

        # Invoice filter
        if result.invoice_id:
            parts.append(f'so_phieu == "{result.invoice_id}"')

        result.milvus_filter = " && ".join(parts)

    # ─────────────────────────────
    # Helper
    # ─────────────────────────────

    @staticmethod
    def _normalize_name(text: str) -> str:
        """
        Normalize tên KH để tăng độ chính xác fuzzy match.
        Bỏ prefix (Anh, Chị...), chuẩn hóa "xóm N"→"xN" và "X N"→"XN", lowercase.
        """
        text = text.lower().strip()
        for prefix in IntentExtractor.CUSTOMER_PREFIXES:
            if text.startswith(prefix + " "):
                text = text[len(prefix):].strip()
        # "xóm N" → "xN"  (e.g. "xóm 3" → "x3", "xóm 10" → "x10")
        text = re.sub(r"\bxóm\s*(\d+)\b", r"x\1", text)
        # "letter space digit(s)" → "letterdigit"  (e.g. "x 3" → "x3", "c 12" → "c12")
        text = re.sub(r"\b([a-z])\s+(\d+)\b", r"\1\2", text)
        return re.sub(r"\s+", " ", text).strip()
    
    @staticmethod
    def _weighted_customer_score(query_norm: str, candidate_norm: str, **_) -> int:
        query_tokens = set(query_norm.split())
        cand_tokens  = set(candidate_norm.split())

        query_personal = query_tokens - IntentExtractor.LOCATION_TOKENS
        cand_personal  = cand_tokens  - IntentExtractor.LOCATION_TOKENS

        # Tầng 1: personal token gate
        if query_personal and cand_personal:
            if not (query_personal & cand_personal):
                return 0  # không có personal token chung → chắc chắn sai

        # Tầng 2: fuzzy score
        # token_sort_ratio: sort tokens rồi so ratio — phân biệt tốt hơn
        # token_set_ratio khi tên có nhiều location tokens giống nhau
        # token_set_ratio: xử lý tốt query ngắn ("viên x3" vs "viên khiêm x3")
        # Personal gate phía trên đã loại false positive nên an toàn dùng set_ratio
        return fuzz.token_set_ratio(query_norm, candidate_norm)

    def _extract_customer_name(self, result: AnalyzedQuery) -> None:
        """Fuzzy-match tên KH trong query → canonical name từ DB customer list."""
        if not self._norm_customers:
            return

        query_norm = self._normalize_name(result.normalized)

        match = process.extractOne(
            query_norm,
            self._norm_customers,
            scorer=self._weighted_customer_score,
            score_cutoff=self.fuzzy_threshold,
            processor=None,
        )

        if match:
            _, score, idx = match
            result.customer_name  = self.customer_names[idx]
            result.customer_score = int(score)


# ─────────────────────────────────────────────
# 6. Demo
# ─────────────────────────────────────────────
if __name__ == "__main__":
    analyzer = QueryAnalyzer(
        customer_names=["Tiệc X3", "Khiêm X3", "Anh Minh"],
        category_names=["Xi măng", "Gạch", "Sắt thép", "Sơn"],
    )

    TEST_QUERIES = [
        "Doanh thu tháng 3/2025 là bao nhiêu?",
        "Anh Tiệc X3 còn nợ bao nhiêu tiền?",
        "Tháng này xi măng bán được bao nhiêu tấn?",
        "So sánh doanh thu quý 1 và quý 2 năm 2024",
        "Top 5 khách hàng mua nhiều nhất năm nay",
        "Phiếu XB24169-0125 gồm những gì?",
        "Giá xi măng sông mã hiện tại bao nhiêu?",
        "Danh mục gạch bán được bao nhiêu tháng trước?",
        "Anh Khiêm trong quý 3 2025 có mua nhiều không?",        # fuzzy match
        "Bán chạy nhất tháng 6 là mặt hàng gì?",
        "Doanh thu ngày nào cao nhất trong tháng 5/2024?",
        "Doanh thu tháng nào cao nhất trong năm 2024?",
    ]

    print("=" * 68)
    for query in TEST_QUERIES:
        r = analyzer.analyze(query)
        print(f"\n📝 Query   : {r.original_query}")
        print(f"   Intent  : {r.primary_intent.value}"
                f"  {[i.value for i in r.intents[1:]] or ''}")
        tf = r.time_filter
        if not tf.is_empty:
            print(f"   Time    : tháng={tf.month} quý={tf.quarter} năm={tf.year}")
        if r.customer_name:
            print(f"   KH      : {r.customer_name}  (score={r.customer_score})")
        if r.category_name:
            print(f"   Danh mục: {r.category_name}  (score={r.category_score})")
        if r.invoice_id:
            print(f"   Phiếu   : {r.invoice_id}")
        print(f"   DocTypes: {[d.value for d in r.doc_types]}")
        print(f"   Filter  : {r.milvus_filter or '(none)'}")
        print(f"   Confidence: {r.routing_confidence:.2f}")
    print("\n" + "=" * 68)