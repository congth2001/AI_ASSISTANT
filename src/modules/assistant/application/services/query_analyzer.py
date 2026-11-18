import asyncio
import logging
import re
import time
import unicodedata
from datetime import date, timedelta
from uuid import UUID
from src.common.domain.time import now_vietnam
from src.modules.assistant.domain.entities.analyzed_query import AnalyzedQuery
from src.modules.assistant.domain.entities.time_filter import TimeFilter
from src.modules.assistant.domain.constants.doc_type import DocType
from src.modules.assistant.domain.constants.query_intent import QueryIntent
from src.modules.assistant.domain.constants.query_analysis_rules import QueryAnalysisRules
from src.modules.sales.domain.repositories.i_customer_repository import ICustomerRepository
from src.modules.sales.domain.repositories.i_sales_invoice_line_repository import (
    ISalesInvoiceLineRepository,
)
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


class QueryAnalyzer:
    """
    Phân tích câu hỏi tiếng Việt → AnalyzedQuery.

    Không phụ thuộc vào bất kỳ external service nào.
    Toàn bộ rule-based + fuzzy matching.
    """

    TTL_SECONDS = 60 * 60  # refresh entity lists every 1 hour
    CUSTOMER_LOAD_LIMIT = 50000
    CUSTOMER_FUZZY_MIN_SCORE = 84
    CUSTOMER_FUZZY_MIN_MARGIN = 8

    _CUSTOMER_CUE_RE = re.compile(
        r"\b(?P<title>anh|chị|cô|chú|bác|ông|bà|em|thím|cậu|dì|mợ)\b"
        r"|\b(?P<customer>khách\s+hàng|khách)\b",
        re.IGNORECASE,
    )
    _GENERIC_CUSTOMER_NON_NAME_STARTS = {
        "ai",
        "ban",
        "bao",
        "cao",
        "co",
        "con",
        "cong",
        "dang",
        "doanh",
        "duoc",
        "gan",
        "it",
        "lon",
        "mua",
        "nao",
        "nhieu",
        "no",
        "o",
        "tai",
        "theo",
        "thap",
        "thu",
        "tot",
        "trong",
    }
    _BUSINESS_NAME_TOKENS = _GENERIC_CUSTOMER_NON_NAME_STARTS | {
        "gia",
        "giam",
        "hang",
        "hoa",
        "loi",
        "nam",
        "ngay",
        "phieu",
        "quy",
        "san",
        "so",
        "tang",
        "thang",
        "tien",
        "tong",
        "xuat",
    }
    _CATEGORY_GENERIC_TOKENS = {
        "bao", "cac", "chi", "co", "cu", "doanh", "duoc", "gom",
        "hang", "mat", "nao", "nhu", "nhung", "san", "the", "thu",
        "tiet", "tong", "trong", "tung",
    }

    def __init__(
        self,
        customer_repo: ICustomerRepository | None = None,
        good_repo: ISalesInvoiceLineRepository | None = None,
        customer_names: list[str] | None = None,
        category_names: list[str] | None = None,
        fuzzy_threshold: int = 75,
    ):
        self.fuzzy_threshold = fuzzy_threshold
        self._customer_repo = customer_repo
        self._good_repo = good_repo
        self._loaded_at: float | None = None
        self._reload_lock = asyncio.Lock()
        self._set_entity_lists(customer_names or [], category_names or [])

    def _is_fresh(self) -> bool:
        return (
            self._loaded_at is not None
            and time.monotonic() - self._loaded_at < self.TTL_SECONDS
        )

    async def ensure_fresh(self) -> None:
        """Reload entity lists from DB if TTL has expired."""
        if self._customer_repo is None or self._good_repo is None:
            return
        if self._is_fresh():
            return
        # One reload at a time: concurrent requests wait for it instead of each
        # loading up to CUSTOMER_LOAD_LIMIT rows again.
        async with self._reload_lock:
            if self._is_fresh():
                return
            customers = await self._customer_repo.list(limit=self.CUSTOMER_LOAD_LIMIT)
            if len(customers) >= self.CUSTOMER_LOAD_LIMIT:
                logger.warning(
                    "Customer list reached the load limit of %d; customers beyond it "
                    "are ignored by name matching",
                    self.CUSTOMER_LOAD_LIMIT,
                )
            # Giữ bản ghi trùng tên để extractor biết tên đó không định danh duy nhất.
            # Dùng set ở đây sẽ che mất sự mơ hồ giữa hai customer_id khác nhau.
            customer_names = [
                c["customer_name"] for c in customers if c.get("customer_name")
            ]
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
        self.customer_names = customer_names
        self._norm_customers = [self._normalize_name(n) for n in customer_names]
        self._customer_keys = [self._fold_text(n) for n in self._norm_customers]
        self.category_names = sorted(
            dict.fromkeys(category_names),
            key=lambda name: self._fold_text(self._normalize_query_text(name)),
        )
        self._norm_categories = [
            n.lower().strip() for n in self.category_names
        ]
        self._category_keys = [
            self._fold_text(self._normalize_query_text(name))
            for name in self.category_names
        ]

    # ─────────────────────────────
    # Public API
    # ─────────────────────────────

    def analyze(self, query: str) -> AnalyzedQuery:
        # Dashboard reference rows describe evidence, not requested entity filters.
        # Matching names from that evidence can silently narrow an all-customer report.
        question, _, report_context = query.partition("\nNgữ cảnh báo cáo đang xem:")
        normalized = question.lower().strip()

        result = AnalyzedQuery(
            original_query=query,
            normalized=normalized,
            intents=[],
            primary_intent=QueryIntent.UNKNOWN,
        )

        self._extract_intents(result)
        self._extract_customer_name(result)
        self._extract_category_name(result)
        self._extract_time(result)
        self._extract_top_n(result)
        self._extract_invoice_id(result)
        self._extract_report_filters(result, report_context)
        self._resolve_doc_types(result)
        self._build_milvus_filter(result)

        return result

    @staticmethod
    def _extract_report_filters(result: AnalyzedQuery, context: str) -> None:
        period = re.search(
            r"Kỳ hiện tại: từ (\d{4}-\d{2}-\d{2}) đến hết (\d{4}-\d{2}-\d{2})",
            context,
        )
        if period:
            try:
                start, end = (date.fromisoformat(value) for value in period.groups())
            except ValueError:
                return
            if start <= end:
                result.time_filter = TimeFilter(date_from=start, date_to=end + timedelta(days=1))
        filters = re.search(
            r"^Bộ lọc: khách hàng (.*?); phường/xã (.*?); thôn/xóm (.*?)\.$",
            context, re.MULTILINE,
        )
        if not filters:
            return
        customer, ward, village = filters.groups()
        customer_id = re.search(r"customer_id=([0-9a-fA-F-]{36})", customer)
        if customer_id:
            try:
                result.customer_id = str(UUID(customer_id.group(1)))
            except ValueError:
                pass
            else:
                result.customer_name = None  # UUID is authoritative, even for duplicate names.
        result.ward_name = ward if ward != "tất cả" else None
        result.village_name = village if village != "tất cả" else None

    # ─────────────────────────────
    # Step 1: Intent classification
    # ─────────────────────────────

    def _extract_intents(self, result: AnalyzedQuery) -> None:
        text = result.normalized
        matched: list[tuple[QueryIntent, int]] = []

        for intent, (rank, keywords) in QueryAnalysisRules.INTENT_PATTERNS.items():
            rank_score = 0
            for kw in keywords:
                if not kw in text:
                    continue
                rank_score += rank
            if rank_score > 0:
                matched.append((intent, rank_score))

        if not matched:
            result.intents = [QueryIntent.UNKNOWN]
            result.primary_intent = QueryIntent.UNKNOWN
            return

        # Sắp xếp theo score giảm dần
        matched.sort(key=lambda x: x[1], reverse=True)
        result.intents = [m[0] for m in matched]
        result.primary_intent = matched[0][0]

    # ─────────────────────────────
    # Step 2: Time extraction
    # ─────────────────────────────

    def _extract_time(self, result: AnalyzedQuery) -> None:
        text = result.normalized
        tf = TimeFilter()

        # Compute relative dates per request in Vietnam, not once at process startup.
        now = now_vietnam()
        yesterday = now - timedelta(days=1)
        relative_time = {
            "hôm nay": (now.day, now.month, now.year),
            "hôm qua": (yesterday.day, yesterday.month, yesterday.year),
            "tháng này": (None, now.month, now.year),
            "tháng hiện tại": (None, now.month, now.year),
            "tháng trước": (None, now.month - 1 if now.month > 1 else 12, now.year if now.month > 1 else now.year - 1),
            "năm nay": (None, None, now.year),
            "năm ngoái": (None, None, now.year - 1),
            "năm trước": (None, None, now.year - 1),
            "quý này": (None, None, now.year),
            "quý trước": (None, None, now.year),
        }
        for phrase, (day, month, year) in relative_time.items():
            if phrase in text:
                tf.day = day
                tf.month = month
                tf.year = year
                if "quý này" in phrase:
                    tf.quarter = (now.month - 1) // 3 + 1
                    tf.month = None
                elif "quý trước" in phrase:
                    q = (now.month - 1) // 3 + 1
                    tf.quarter = q - 1 if q > 1 else 4
                    tf.year = (
                        now.year
                        if q > 1
                        else now.year - 1
                    )
                    tf.month = None
                result.time_filter = tf
                return

        # Quý: "quý 1", "q1", "quý i"
        q_match = re.search(
            r"\bqu[ýyỳ]\s*(iv|iii|ii|i|[1-4])\b",
            text,
        )
        if q_match:
            raw = q_match.group(1)
            quarter_map = {
                "i": 1,
                "ii": 2,
                "iii": 3,
                "iv": 4,
                "v": 5,
                "1": 1,
                "2": 2,
                "3": 3,
                "4": 4,
            }
            tf.quarter = quarter_map[raw.lower()]

        # Năm: "năm 2024", "2024", "/24"
        y_match = re.search(r"(?:năm\s*)?(?:20(\d{2})|/(\d{2}))\b", text)
        if y_match:
            suffix = y_match.group(1) or y_match.group(2)
            tf.year = 2000 + int(suffix)

        # Tháng dạng số: "tháng 3", "t3", "tháng 3/2024"
        m_match = re.search(
            r"\b(?:tháng\s*|t)(1[0-2]|[1-9])(?:/(\d{4}|\d{2}))?\b",
            text,
        )
        if m_match:
            tf.month = int(m_match.group(1))
            if m_match.group(2):
                yr = m_match.group(2)
                tf.year = 2000 + int(yr) if len(yr) == 2 else int(yr)

        # Tháng dạng chữ: "tháng ba", "tháng mười hai"
        if not tf.month:
            for word, num in sorted(QueryAnalysisRules.MONTH_WORDS.items(), key=lambda item: len(item[0]), reverse=True):
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
            result.normalized,
        )
        if match:
            result.invoice_id = match.group(1).upper()
            result.primary_intent = QueryIntent.INVOICE

    def _extract_top_n(self, result: AnalyzedQuery) -> None:
        match = re.search(r"\btop\s*(\d{1,4})\b", result.normalized)
        if not match and QueryIntent.RANKING in result.intents:
            match = re.search(
                r"\b(\d{1,4})\s+(?:khách\s+hàng|mặt\s+hàng|sản\s+phẩm)\b",
                result.normalized,
            )
        if match:
            result.top_n = min(int(match.group(1)), 1000)

    # ─────────────────────────────
    # Step 4: Resolve doc_types
    # ─────────────────────────────

    def _resolve_doc_types(self, result: AnalyzedQuery) -> None:
        base = QueryAnalysisRules.INTENT_TO_DOC_TYPES.get(result.primary_intent, [])

        # Tinh chỉnh thêm dựa trên entity đã extract
        extra: list[DocType] = []

        if result.customer_name and DocType.CUSTOMER not in base:
            extra.append(DocType.CUSTOMER)

        if result.invoice_id and DocType.TRANSACTION not in base:
            extra.append(DocType.TRANSACTION)

        if result.category_name or result.category_names:
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
        for prefix in QueryAnalysisRules.CUSTOMER_PREFIXES:
            if text.startswith(prefix + " "):
                text = text[len(prefix) :].strip()
        # "xóm N" → "xN"  (e.g. "xóm 3" → "x3", "xóm 10" → "x10")
        text = re.sub(r"\bxóm\s*(\d+)\b", r"x\1", text)
        # "letter space digit(s)" → "letterdigit"  (e.g. "x 3" → "x3", "c 12" → "c12")
        text = re.sub(r"\b([a-z])\s+(\d+)\b", r"\1\2", text)
        text = re.sub(r"[^\w\s]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize_query_text(text: str) -> str:
        """Chuẩn hóa câu hỏi nhưng không bỏ danh xưng ở đầu câu."""
        text = text.lower().strip()
        text = re.sub(r"\bxóm\s*(\d+)\b", r"x\1", text)
        text = re.sub(r"\b([a-z])\s+(\d+)\b", r"\1\2", text)
        text = re.sub(r"[^\w\s]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _fold_text(text: str) -> str:
        """Tạo khóa so khớp không dấu; giá trị canonical trả về vẫn giữ nguyên dấu."""
        decomposed = unicodedata.normalize("NFD", text)
        without_marks = "".join(
            char for char in decomposed if unicodedata.category(char) != "Mn"
        )
        return without_marks.replace("đ", "d").replace("Đ", "D").lower()

    def _customer_candidate_prefixes(self, query_text: str) -> list[str]:
        """Lấy các cụm đứng sau danh xưng/nhãn khách hàng, không lấy cả câu hỏi."""
        prefixes: list[str] = []
        max_tokens = max((len(key.split()) for key in self._customer_keys), default=0)
        if not max_tokens:
            return prefixes

        for cue in self._CUSTOMER_CUE_RE.finditer(query_text):
            tail = query_text[cue.end() :].strip()
            tokens = tail.split()
            if not tokens:
                continue

            is_title = cue.group("title") is not None
            first_token_key = self._fold_text(tokens[0])
            if not is_title and first_token_key in {"ten", "la"}:
                tokens = tokens[1:]
                is_title = True
            if not tokens:
                continue
            first_token_key = self._fold_text(tokens[0])
            if (
                not is_title
                and first_token_key in self._GENERIC_CUSTOMER_NON_NAME_STARTS
            ):
                continue

            for size in range(1, min(len(tokens), max_tokens) + 1):
                prefixes.append(" ".join(tokens[:size]))

        return list(dict.fromkeys(prefixes))

    def _exact_customer_indexes(
        self,
        query_key: str,
        cue_prefixes: list[str],
    ) -> list[int]:
        cue_keys = set(cue_prefixes)
        matched: list[int] = []
        for index, key in enumerate(self._customer_keys):
            if not key:
                continue
            key_tokens = set(key.split())
            requires_cue = (
                len(key_tokens) == 1
                or key_tokens.issubset(self._BUSINESS_NAME_TOKENS)
            )
            has_cue = key in cue_keys
            appears_in_query = re.search(
                rf"(?<!\w){re.escape(key)}(?!\w)", query_key
            ) is not None
            if appears_in_query and (not requires_cue or has_cue):
                matched.append(index)
        return matched

    def _extract_customer_name(self, result: AnalyzedQuery) -> None:
        """Nhận diện tên KH chính xác cao và chủ động từ chối khi mơ hồ."""
        if not self._customer_keys:
            return

        query_norm = self._normalize_query_text(result.normalized)
        query_key = self._fold_text(query_norm)
        cue_prefixes = [
            self._fold_text(prefix)
            for prefix in self._customer_candidate_prefixes(query_norm)
        ]

        exact_indexes = self._exact_customer_indexes(query_key, cue_prefixes)
        exact_keys = {self._customer_keys[index] for index in exact_indexes}
        # Một câu nhắc nhiều KH hoặc nhiều canonical name có cùng khóa thì không
        # thể biểu diễn an toàn bằng trường customer_name đơn hiện tại.
        if len(exact_keys) > 1:
            return
        if len(exact_indexes) == 1:
            index = exact_indexes[0]
            result.customer_name = self.customer_names[index]
            result.customer_score = 100
            return
        if exact_indexes:
            return

        # Fuzzy chỉ chạy trên cụm sau cue rõ ràng và chỉ dành cho tên >= 2 token.
        scores_by_index: dict[int, float] = {}
        for index, key in enumerate(self._customer_keys):
            token_count = len(key.split())
            if token_count < 2:
                continue
            for prefix in cue_prefixes:
                prefix_tokens = prefix.split()
                if len(prefix_tokens) != token_count:
                    continue
                score = fuzz.ratio(prefix, key)
                scores_by_index[index] = max(scores_by_index.get(index, 0), score)

        ranked = sorted(scores_by_index.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return
        best_index, best_score = ranked[0]
        min_score = max(self.fuzzy_threshold, self.CUSTOMER_FUZZY_MIN_SCORE)
        if best_score < min_score:
            return
        second_score = ranked[1][1] if len(ranked) > 1 else 0
        if best_score - second_score < self.CUSTOMER_FUZZY_MIN_MARGIN:
            return

        result.customer_name = self.customer_names[best_index]
        result.customer_score = int(round(best_score))

    def _extract_category_name(self, result: AnalyzedQuery) -> None:
        """Map cách gọi trong câu hỏi về đúng tên danh mục canonical từ DB."""
        if not self._category_keys:
            return

        query_norm = self._normalize_query_text(result.normalized)
        query_key = self._fold_text(query_norm)
        matches: list[tuple[int, str]] = []
        for index, (normalized, key) in enumerate(
            zip(self._norm_categories, self._category_keys)
        ):
            if not key:
                continue
            exact_with_accents = re.search(
                rf"(?<!\w){re.escape(normalized)}(?!\w)", query_norm
            ) is not None
            folded_match = re.search(
                rf"(?<!\w){re.escape(key)}(?!\w)", query_key
            ) is not None
            # Không cho category cực ngắn như "Ve" khớp với từ có dấu "vệ"
            # chỉ nhờ folding. Exact "danh mục Ve" vẫn được chấp nhận.
            unsafe_short_fold = (
                len(key.split()) == 1
                and len(key) <= 2
                and not exact_with_accents
            )
            if folded_match and not unsafe_short_fold:
                matches.append((index, key))

        if matches:
            distinct_keys = {key for _, key in matches}
            containing_keys = [
                key
                for key in distinct_keys
                if all(
                    other == key
                    or re.search(rf"(?<!\w){re.escape(other)}(?!\w)", key)
                    for other in distinct_keys
                )
            ]
            if len(containing_keys) == 1:
                selected_keys = {containing_keys[0]}
            else:
                selected_keys = distinct_keys
            indexes = list(
                dict.fromkeys(
                    index for index, key in matches if key in selected_keys
                )
            )
            names = [self.category_names[index] for index in indexes]
            result.category_names = names
            if len(names) == 1:
                result.category_name = names[0]
            result.category_score = 100
            return

        # Người dùng có thể gọi một họ danh mục, ví dụ "thiết bị vệ sinh",
        # trong khi DB lưu "Bộ/Dây/Phụ kiện thiết bị vệ sinh". Tìm n-gram dài
        # nhất của câu hỏi xuất hiện trọn vẹn trong các canonical category.
        tokens = query_key.split()
        max_size = min(
            len(tokens),
            max((len(key.split()) for key in self._category_keys), default=0),
        )
        family_candidates: list[tuple[int, str, tuple[int, ...]]] = []
        for size in range(2, max_size + 1):
            for start in range(0, len(tokens) - size + 1):
                phrase_tokens = tokens[start : start + size]
                if not (
                    set(phrase_tokens) - self._CATEGORY_GENERIC_TOKENS
                ):
                    continue
                phrase = " ".join(phrase_tokens)
                indexes = tuple(
                    index
                    for index, key in enumerate(self._category_keys)
                    if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", key)
                )
                if indexes:
                    family_candidates.append((size, phrase, indexes))

        if not family_candidates:
            return
        longest = max(size for size, _, _ in family_candidates)
        best = [item for item in family_candidates if item[0] == longest]
        distinct_index_sets = {item[2] for item in best}
        if len(distinct_index_sets) != 1:
            return

        indexes = next(iter(distinct_index_sets))
        names = [self.category_names[index] for index in indexes]
        result.category_names = names
        if len(names) == 1:
            result.category_name = names[0]
        result.category_score = 95
