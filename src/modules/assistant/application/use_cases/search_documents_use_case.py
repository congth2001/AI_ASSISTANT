"""
Orchestrate việc tìm kiếm documents liên quan đến câu hỏi của user.
"""
import asyncio
import logging
import re

from src.modules.assistant.application.services.query_analyzer import QueryAnalyzer
from src.modules.assistant.domain.repositories.i_search_repository import ISearchRepository
from src.modules.assistant.domain.entities.analyzed_query import AnalyzedQuery
from src.modules.assistant.domain.constants.query_intent import QueryIntent
from src.modules.assistant.domain.entities.search_documents_result import SearchDocumentsResult
from src.modules.assistant.domain.entities.search_result import SearchResult
from src.modules.assistant.domain.errors import (
    QueryAnalyzerRequiredError,
    VectorStoreQueryError,
)

logger = logging.getLogger(__name__)


class SearchDocumentsUseCase:
    """
    Input : AnalyzedQuery (từ QueryAnalyzer)
    Output: SearchDocumentsResult (cho ContextBuilder)

    Business rules duy nhất ở đây:
        - Query UNKNOWN và không có entity → trả rỗng, không tốn vector search
        - Kết quả rỗng sau search → đánh dấu used_fallback để LLM biết
        context không đầy đủ, tránh hallucinate
        - Kho vector lỗi (VectorStoreQueryError) → không làm sập lượt chat: trả kết quả rỗng
        kèm `error_code`, để caller (vd. hybrid) tiếp tục với nguồn khác như SQL

    `execute`/`execute_analyzed` là đồng bộ (embedding + Milvus là I/O chặn); từ code async hãy dùng
    `execute_async`/`execute_analyzed_async` (chạy trong thread, không chặn event loop).
    """

    def __init__(
        self,
        search_repo: ISearchRepository,
        query_analyzer: QueryAnalyzer | None = None,
    ):
        self.repo = search_repo
        self.query_analyzer = query_analyzer

    def execute(self, query: str | AnalyzedQuery) -> SearchDocumentsResult:
        # Preserve the convenient pre-analyzed entry point for callers/tests
        # while keeping string analysis available to API-level consumers.
        if isinstance(query, AnalyzedQuery):
            return self.execute_analyzed(query)
        if self.query_analyzer is None:
            raise QueryAnalyzerRequiredError()
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

        try:
            results = self.repo.search(analyzed)
        except VectorStoreQueryError as exc:
            logger.warning("Vector store unavailable, returning empty search result: %s", exc)
            return SearchDocumentsResult(
                results        = [],
                analyzed_query = analyzed,
                used_fallback  = False,
                error_code     = exc.code,
            )

        # Phát hiện fallback: filter gốc không có kết quả
        # → repo đã nới lỏng filter, context có thể không đúng kỳ/KH
        used_fallback = self._detect_fallback(analyzed, results)

        return SearchDocumentsResult(
            results        = results,
            analyzed_query = analyzed,
            used_fallback  = used_fallback,
        )

    async def execute_async(self, query: str | AnalyzedQuery) -> SearchDocumentsResult:
        """Bản không chặn event loop của `execute` (chạy trong thread)."""
        return await asyncio.to_thread(self.execute, query)

    async def execute_analyzed_async(self, analyzed: AnalyzedQuery) -> SearchDocumentsResult:
        """Bản không chặn event loop của `execute_analyzed` (chạy trong thread)."""
        return await asyncio.to_thread(self.execute_analyzed, analyzed)

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

        Giả định: `customer_id` trong Milvus được ETL ghi bằng cùng phép slug hóa với
        `MilvusSearchRepository._build_filter_chain` (lower → bỏ ký tự không phải \\w/khoảng trắng
        → khoảng trắng thành "_"). Giữ nguyên dấu tiếng Việt (\\w Unicode), nên "Tiệc" ≠ "Tiec".
        Nếu quy ước ghi dữ liệu thay đổi, phải đổi đồng thời ở cả hai nơi.
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
            expected_cid = re.sub(r"[^\w\s]", "", analyzed.customer_name.lower())
            expected_cid = re.sub(r"\s+", "_", expected_cid).strip("_")
            if cids and expected_cid not in cids:
                return True

        return False
