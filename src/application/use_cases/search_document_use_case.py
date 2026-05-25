"""
Orchestrate việc tìm kiếm documents liên quan đến câu hỏi của user.
"""
from src.application.services.query_analyzer import QueryAnalyzer
from src.domain.interfaces.i_search_repository import ISearchRepository
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.value_objects.query_intent import QueryIntent
from src.domain.entities.search_document_result import SearchDocumentsResult
from src.domain.entities.search_result import SearchResult


class SearchDocumentsUseCase:
    """
    Input : AnalyzedQuery (từ QueryAnalyzer)
    Output: SearchDocumentsResult (cho ContextBuilder)

    Business rules duy nhất ở đây:
        - Query UNKNOWN và không có entity → trả rỗng, không tốn vector search
        - Kết quả rỗng sau search → đánh dấu used_fallback để LLM biết
        context không đầy đủ, tránh hallucinate
    """

    def __init__(self, search_repo: ISearchRepository, query_analyzer: QueryAnalyzer):
        self.repo = search_repo
        self.query_analyzer = query_analyzer

    def execute(self, query: str) -> SearchDocumentsResult:
        analyzed = self.query_analyzer.analyze(query)
        return self.execute_analyzed(analyzed)

    def execute_analyzed(self, analyzed: AnalyzedQuery) -> SearchDocumentsResult:
        """Nhận AnalyzedQuery đã parse sẵn để tránh phân tích lại."""
        if self._is_empty_query(analyzed):
            return SearchDocumentsResult(
                results        = [],
                analyzed_query = analyzed,
                used_fallback  = False,
            )

        results = self.repo.search(analyzed)

        # Phát hiện fallback: filter gốc không có kết quả
        # → repo đã nới lỏng filter, context có thể không đúng kỳ/KH
        used_fallback = self._detect_fallback(analyzed, results)

        return SearchDocumentsResult(
            results        = results,
            analyzed_query = analyzed,
            used_fallback  = used_fallback,
        )

    # ─────────────────────────────
    # Private helpers
    # ─────────────────────────────

    @staticmethod
    def _is_empty_query(analyzed: AnalyzedQuery) -> bool:
        """
        True nếu câu hỏi không đủ thông tin để search:
            - Intent UNKNOWN
            - Không có entity nào (KH, danh mục, sản phẩm, thời gian)
        """
        if analyzed.primary_intent != QueryIntent.UNKNOWN:
            return False

        has_entity = any([
            analyzed.customer_name,
            analyzed.category_name,
            analyzed.product_name,
            analyzed.invoice_id,
            not analyzed.time_filter.is_empty,
        ])
        return not has_entity

    @staticmethod
    def _detect_fallback(
        analyzed: AnalyzedQuery,
        results : list[SearchResult],
    ) -> bool:
        """
        Phát hiện kết quả trả về không khớp với filter gốc.

        Ví dụ: user hỏi tháng 3/2025 nhưng kết quả trả về tháng 12/2024
        → fallback đã xảy ra → ContextBuilder cần báo LLM biết
        """
        if not results:
            return False

        tf = analyzed.time_filter

        # Kiểm tra time mismatch
        if tf.month:
            months = {r.metadata.get("month") for r in results if r.metadata.get("month")}
            if months and tf.month not in months:
                return True

        if tf.year:
            years = {r.metadata.get("year") for r in results if r.metadata.get("year")}
            if years and tf.year not in years:
                return True

        # Kiểm tra customer mismatch
        if analyzed.customer_name:
            cids = {r.metadata.get("customer_id") for r in results}
            import re
            expected_cid = re.sub(r"[^\w\s]", "", analyzed.customer_name.lower())
            expected_cid = re.sub(r"\s+", "_", expected_cid).strip("_")
            if cids and expected_cid not in cids:
                return True

        return False