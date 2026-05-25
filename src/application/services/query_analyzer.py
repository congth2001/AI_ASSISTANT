import os
import sys
import json
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import re
from src.domain.interfaces.i_llm_service import ILLMService
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.entities.time_filter import TimeFilter
from src.domain.value_objects.doc_type import DocType
from src.domain.value_objects.query_intent import QueryIntent
from src.domain.value_objects.aggregation_type import AggregationType
from src.domain.value_objects.intent_extractor import IntentExtractor
from rapidfuzz import fuzz, process


class QueryAnalyzer:
    """
    Phân tích câu hỏi tiếng Việt → AnalyzedQuery.

    Không phụ thuộc vào bất kỳ external service nào.
    Toàn bộ rule-based + fuzzy matching.
    """

    def __init__(
        self,
        document_dir: str | None = None,
        fuzzy_threshold: int = 75,
        llm_service: ILLMService = None,  # placeholder cho future LLM-based analysis
    ):
        if document_dir is None:
            document_dir = str(
                Path(__file__).resolve().parent.parent.parent.parent / "data" / "ingestions"
            )
        self.document_dir    = document_dir
        self.fuzzy_threshold = fuzzy_threshold
        self.llm_service     = llm_service
        self._read_jsonl_file()

        # Pre-build normalized lookup để tăng tốc fuzzy match
        self._norm_customers = [self._normalize_name(n) for n in self.customer_names]
        self._norm_categories= [c.lower().strip() for c in self.category_names]
        self._norm_products  = [p.lower().strip() for p in self.product_names]

    # Helper methods
    @staticmethod
    def _load_jsonl(path: Path, meta_key: str) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    name = json.loads(line).get("metadata", {}).get(meta_key, "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        results.append(name)
                except json.JSONDecodeError:
                    continue
        return results

    def _read_jsonl_file(self):
        out = Path(self.document_dir)
        sources = [
            ("customers.jsonl",  "ten_kh",        "customer_names"),
            ("categories.jsonl", "loai_mat_hang",  "category_names"),
            ("products.jsonl",   "ten_hang",       "product_names"),
        ]
        for filename, meta_key, attr in sources:
            path = out / filename
            setattr(self, attr, self._load_jsonl(path, meta_key) if path.exists() else [])

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

        # Chạy từng bước phân tích
        self._extract_intents(result)
        self._extract_time(result)
        self._extract_invoice_id(result)
        self._extract_customer(result)
        self._extract_category(result)
        self._extract_product(result)
        self._detect_analytics(result)

        # Xác định doc_types cần search
        self._resolve_doc_types(result)

        # Build Milvus filter expression
        self._build_milvus_filter(result)

        # Đánh dấu cần LLM fallback nếu không tự tin
        result.needs_llm_fallback = (
            result.primary_intent == QueryIntent.UNKNOWN
            or (result.customer_name and result.customer_score < 80)
        )

        return result


    # ─────────────────────────────
    # Step 1: Intent classification
    # ─────────────────────────────

    def _extract_intents(self, result: AnalyzedQuery) -> None:
        text = result.normalized
        matched: list[tuple[QueryIntent, int]] = []

        for intent, keywords in IntentExtractor.INTENT_PATTERNS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                matched.append((intent, score))

        if not matched:
            result.intents        = [QueryIntent.UNKNOWN]
            result.primary_intent = QueryIntent.UNKNOWN
            return

        # Sắp xếp theo score giảm dần
        matched.sort(key=lambda x: x[1], reverse=True)
        result.intents        = [m[0] for m in matched]
        result.primary_intent = matched[0][0]

        # DEBT thắng CUSTOMER khi cả 2 xuất hiện (keyword "anh/chị" overlap nhiều)
        # INVOICE chỉ được set bởi _extract_invoice_id khi tìm được mã phiếu thực,
        # không set ở đây vì top_k=1 không phù hợp cho query không có mã cụ thể.
        if QueryIntent.DEBT in result.intents:
            result.primary_intent = QueryIntent.DEBT

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
    # Step 4: Customer name (fuzzy)
    # ─────────────────────────────

    def _extract_customer(self, result: AnalyzedQuery) -> None:
        if result.primary_intent not in IntentExtractor.CUSTOMER_INTENTS:
            return
        if result.primary_intent == QueryIntent.INVOICE:
            return

        # Lọc stop words khỏi query trước khi match — tránh "mua gì gần đây" làm loãng score
        query_norm = self._normalize_name(result.normalized)
        query_tokens_clean = " ".join(
            t for t in query_norm.split() if t not in IntentExtractor.QUERY_STOP_WORDS
        )
        query_norm = query_tokens_clean or query_norm  # fallback nếu xóa hết

        # Exact substring — bỏ qua tên quá ngắn để tránh false positive
        for i, norm_name in enumerate(self._norm_customers):
            if len(norm_name) < 4:
                continue
            if norm_name in query_norm or query_norm in norm_name:
                result.customer_name  = self.customer_names[i]
                result.customer_score = 100
                return

        # Fuzzy match với weighted scoring — ưu tiên personal tokens
        best_score = 0
        best_idx   = -1

        for idx, norm_name in enumerate(self._norm_customers):
            if len(norm_name) < 4:
                continue
            score = self._weighted_customer_score(query_norm, norm_name)
            if score > best_score:
                best_score = score
                best_idx   = idx

        if best_idx >= 0 and best_score >= self.fuzzy_threshold:
            result.customer_name  = self.customer_names[best_idx]
            result.customer_score = best_score

    # ─────────────────────────────
    # Step 5: Category name (fuzzy)
    # ─────────────────────────────

    def _extract_category(self, result: AnalyzedQuery) -> None:
        text = result.normalized

        # Exact match — bỏ qua category quá ngắn (T, Y, ...) để tránh noise
        for i, cat in enumerate(self._norm_categories):
            if len(cat) < 3:
                continue
            if cat in text:
                result.category_name = self.category_names[i]
                return

        # Fuzzy — chỉ khi intent liên quan đến hàng hóa
        if result.primary_intent in (
            QueryIntent.PRODUCT, QueryIntent.CATEGORY,
            QueryIntent.RANKING, QueryIntent.REVENUE,
        ):
            # Chỉ fuzzy với category có độ dài hợp lý
            valid_cats  = [(i, c) for i, c in enumerate(self._norm_categories)
                            if len(c) >= 3]
            valid_names = [c for _, c in valid_cats]
            match = process.extractOne(
                text,
                valid_names,
                scorer       = fuzz.partial_ratio,
                score_cutoff = 80,
            )
            if match:
                _, _, local_idx      = match
                real_idx             = valid_cats[local_idx][0]
                result.category_name = self.category_names[real_idx]

    # ─────────────────────────────
    # Step 6: Product name (fuzzy)
    # ─────────────────────────────

    def _extract_product(self, result: AnalyzedQuery) -> None:
        if result.primary_intent not in (
            QueryIntent.PRODUCT, QueryIntent.RANKING, QueryIntent.COMPARISON,
        ):
            return

        text = result.normalized
        match = process.extractOne(
            text,
            self._norm_products,
            scorer       = fuzz.partial_ratio,
            score_cutoff = 75,
        )
        if match:
            _, _, idx          = match
            result.product_name = self.product_names[idx]

    # ─────────────────────────────
    # Step 7: Resolve doc_types
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

        if result.product_name and DocType.PRODUCT not in base:
            extra.append(DocType.PRODUCT)

        result.doc_types = base + extra

    # ─────────────────────────────
    # Step 8: Build Milvus filter
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
    # Step 9: Detect analytics need
    # ─────────────────────────────

    def _detect_analytics(self, result: AnalyzedQuery) -> None:
        text = result.normalized
        tf   = result.time_filter

        # "ngày nào" → cần group-by day trên raw transactions
        if any(p in text for p in ("ngày nào", "hôm nào", "ngày có doanh thu")):
            result.needs_analytics  = True
            result.aggregation_type = AggregationType.DAILY_REVENUE
            return

        # "tháng nào" trong năm cụ thể → group-by month
        if "tháng nào" in text and tf.year:
            result.needs_analytics  = True
            result.aggregation_type = AggregationType.MONTHLY_REVENUE
            return

        # RANKING + có time filter → top N khách hàng trong kỳ
        if result.primary_intent == QueryIntent.RANKING and not tf.is_empty:
            result.needs_analytics  = True
            result.aggregation_type = AggregationType.TOP_CUSTOMERS
            n_match = re.search(r"\btop\s+(\d+)", text)
            result.top_n = int(n_match.group(1)) if n_match else 10
    
    
    # ────────────────────────────
    # ALTERNATIVE: USING LLM FOR QUERY ANALYSIS
    # ────────────────────────────
    async def analyze_with_llm(self, query: str) -> AnalyzedQuery:
        """Phân tích câu hỏi bằng LLM và trả về AnalyzedQuery có cấu trúc."""
        if not self.llm_service:
            raise ValueError("LLM service not configured")

        normalized = query.lower().strip()

        intents_desc = "\n".join(
            f'  - "{i.value}": {i.name.lower().replace("_", " ")}' for i in QueryIntent
        )
        agg_desc = "\n".join(f'  - "{a.value}"' for a in AggregationType)

        prompt = (
            f"Phân tích câu hỏi kinh doanh và chỉ trả về JSON (không markdown, không giải thích).\n"
            f"Q: \"{query}\"\n\n"
            f"intents hợp lệ:\n{intents_desc}\n\n"
            f"aggregation_type hợp lệ:\n{agg_desc}\n\n"
            'Trả về JSON với các trường: primary_intent, intents (mảng, giảm dần độ phù hợp), '
            'time_filter {day,month,quarter,year} (null nếu không đề cập), '
            'customer_name (null nếu không có tên cụ thể), category_name, product_name, '
            'invoice_id (null nếu không có mã phiếu, dạng XB12345-0125), '
            'needs_analytics (true khi cần tổng hợp: top N, cao nhất, ...), '
            'aggregation_type, top_n (mặc định 10).'
        )

        raw = await self.llm_service.generate_response(prompt)

        # Strip markdown fences nếu LLM trả về
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw.strip())

        try:
            data: dict = json.loads(raw)
        except json.JSONDecodeError:
            # JSON parse thất bại → fallback về rule-based
            return self.analyze(query)

        result = AnalyzedQuery(
            original_query=query,
            normalized=normalized,
            intents=[],
            primary_intent=QueryIntent.UNKNOWN,
        )

        # --- intents ---
        intent_map = {i.value: i for i in QueryIntent}
        primary_raw = data.get("primary_intent", "unknown")
        result.primary_intent = intent_map.get(primary_raw, QueryIntent.UNKNOWN)
        raw_intents = data.get("intents") or [primary_raw]
        result.intents = [intent_map[v] for v in raw_intents if v in intent_map] or [result.primary_intent]

        # --- time_filter ---
        tf_data = data.get("time_filter") or {}
        result.time_filter = TimeFilter(
            day=tf_data.get("day"),
            month=tf_data.get("month"),
            quarter=tf_data.get("quarter"),
            year=tf_data.get("year"),
        )

        # --- entities ---
        result.customer_name  = data.get("customer_name") or None
        result.customer_score = 90 if result.customer_name else 0
        result.category_name  = data.get("category_name") or None
        result.product_name   = data.get("product_name") or None
        result.invoice_id     = data.get("invoice_id") or None

        # INVOICE intent khi có mã phiếu rõ ràng
        if result.invoice_id:
            result.primary_intent = QueryIntent.INVOICE

        # --- analytics ---
        result.needs_analytics  = bool(data.get("needs_analytics", False))
        agg_map = {a.value: a for a in AggregationType}
        result.aggregation_type = agg_map.get(data.get("aggregation_type", "none"), AggregationType.NONE)
        result.top_n            = int(data.get("top_n") or 10)

        # --- reuse existing logic cho doc_types + milvus filter ---
        self._resolve_doc_types(result)
        self._build_milvus_filter(result)

        result.needs_llm_fallback = False
        return result

        

    # ─────────────────────────────
    # Helper
    # ─────────────────────────────

    @staticmethod
    def _normalize_name(text: str) -> str:
        """
        Normalize tên KH để tăng độ chính xác fuzzy match.
        Bỏ prefix (Anh, Chị...), lowercase, strip khoảng trắng thừa.
        """
        text = text.lower().strip()
        for prefix in IntentExtractor.CUSTOMER_PREFIXES:
            if text.startswith(prefix + " "):
                text = text[len(prefix):].strip()
        # Chuẩn hóa khoảng trắng
        return re.sub(r"\s+", " ", text)
    
    @staticmethod
    def _weighted_customer_score(query_norm: str, candidate_norm: str) -> int:
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


# ─────────────────────────────────────────────
# 6. Demo
# ─────────────────────────────────────────────
if __name__ == "__main__":
    analyzer = QueryAnalyzer(document_dir="./data/ingestions")

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
            print(f"   Danh mục: {r.category_name}")
        if r.product_name:
            print(f"   Sản phẩm: {r.product_name}")
        if r.invoice_id:
            print(f"   Phiếu   : {r.invoice_id}")
        print(f"   DocTypes: {[d.value for d in r.doc_types]}")
        print(f"   Filter  : {r.milvus_filter or '(none)'}")
        if r.needs_analytics:
            print(f"   ⚠️  Cần phân tích số liệu (aggregation: {r.aggregation_type.value})")
        if r.needs_llm_fallback:
            print(f"   ⚠️  Cần LLM fallback")
    print("\n" + "=" * 68)