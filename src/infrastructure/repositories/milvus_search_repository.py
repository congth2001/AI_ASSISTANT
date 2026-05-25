import re
from typing import Optional

from src.domain.interfaces.i_embedding_service import IEmbeddingService
from src.domain.interfaces.i_search_repository import ISearchRepository
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.value_objects.query_intent import QueryIntent
from src.domain.value_objects.search_config import SearchConfig
from src.domain.entities.search_result import SearchResult
from src.domain.interfaces.i_vector_db import IVectorDB


class MilvusSearchRepository(ISearchRepository):

    def __init__(
        self,
        client: IVectorDB = None,
        embedding_service: IEmbeddingService = None,
    ):
        self.client   = client
        self.embedder = embedding_service

    # ─────────────────────────────
    # Public API
    # ─────────────────────────────

    def search(self, analyzed: AnalyzedQuery) -> list[SearchResult]:
        """
        Pipeline:
            1. Embed query text
            2. Build filter chain (strict → loose) from AnalyzedQuery
            3. Hybrid search (vector + keyword via RRF) with fallback
            4. Return list[SearchResult]
        """
        vector = self.embedder.generate_embedding(analyzed.original_query)
        top_k  = SearchConfig.TOP_K_BY_INTENT.get(analyzed.primary_intent, 5)
        ef     = SearchConfig.EF_BY_INTENT.get(analyzed.primary_intent, SearchConfig.DEFAULT_EF)

        return self._hybrid_search_with_fallback(
            vector       = vector,
            query_text   = analyzed.original_query,
            top_k        = top_k,
            ef           = ef,
            filter_chain = self._build_filter_chain(analyzed),
        )

    # ─────────────────────────────
    # Filter fallback chain
    # ─────────────────────────────

    def _build_filter_chain(self, analyzed: AnalyzedQuery) -> list[str]:
        """
        Builds a chain of Milvus filter expressions from strict → loose.
        If a strict filter yields no results, the next looser filter is tried.

        Example for "Anh Tiệc X3, tháng 3/2025":
            [0] doc_type + customer + year + month  ← strictest
            [1] doc_type + customer + year
            [2] doc_type + customer
            [3] doc_type
            [4] ""                                   ← no filter fallback
        """
        tf = analyzed.time_filter

        type_expr = ""
        if analyzed.doc_types:
            type_expr = "({})".format(
                " || ".join(f'doc_type == "{dt.value}"' for dt in analyzed.doc_types)
            )

        customer_expr = ""
        if analyzed.customer_name:
            cid = analyzed.customer_name.strip().lower()
            cid = re.sub(r"[^\w\s]", "", cid)
            cid = re.sub(r"\s+", "_", cid).strip("_")
            customer_expr = f'customer_id == "{cid}"'

        debt_expr  = "co_no == true" if analyzed.primary_intent == QueryIntent.DEBT else ""
        year_expr  = f"year == {tf.year}"   if tf.year  else ""
        month_expr = f"month == {tf.month}" if tf.month else ""

        # Invoice lookup: single hard filter, no fallback needed
        if analyzed.invoice_id:
            return [f'so_phieu == "{analyzed.invoice_id}"']

        def join(*parts: str) -> str:
            return " && ".join(p for p in parts if p)

        chain = []

        full = join(type_expr, customer_expr, debt_expr, year_expr, month_expr)
        if full:
            chain.append(full)

        if month_expr:
            no_month = join(type_expr, customer_expr, debt_expr, year_expr)
            if no_month and no_month != full:
                chain.append(no_month)

        if year_expr or month_expr:
            no_time = join(type_expr, customer_expr, debt_expr)
            if no_time and no_time not in chain:
                chain.append(no_time)

        if type_expr and type_expr not in chain:
            chain.append(type_expr)

        chain.append("")  # final fallback: no filter

        seen = set()
        return [c for c in chain if not (c in seen or seen.add(c))]

    # ─────────────────────────────
    # Hybrid search with filter fallback
    # ─────────────────────────────

    def _hybrid_search_with_fallback(
        self,
        vector      : list[float],
        query_text  : str,
        top_k       : int,
        ef          : int,
        filter_chain: list[str],
        min_results : int = 1,
    ) -> list[SearchResult]:
        """
        Tries each filter in the chain in order.
        Stops at the first filter that returns >= min_results results.
        Each attempt runs hybrid search (vector + keyword via RRF).
        """
        for milvus_filter in filter_chain:
            raw = self.client.hybrid_search(
                query_vector   = vector,
                query_text     = query_text,
                top_k          = top_k,
                filter         = milvus_filter,
                ef             = ef,
            )
            results = [self._to_search_result(r) for r in raw]
            if len(results) >= min_results:
                return results

        return []

    def _to_search_result(self, r: dict) -> SearchResult:
        meta = r.get("metadata", {})
        return SearchResult(
            doc_id   = r["id"],
            doc_type = meta.get("doc_type", ""),
            text     = r.get("content", ""),
            score    = r["score"],
            metadata = {
                "year"       : meta.get("year"),
                "month"      : meta.get("month"),
                "customer_id": meta.get("customer_id"),
                "co_no"      : meta.get("co_no"),
            },
        )

    # ─────────────────────────────
    # Utility: direct text search (for quick testing)
    # ─────────────────────────────

    def raw_search(
        self,
        query_text  : str,
        doc_type    : Optional[str] = None,
        top_k       : int = 5,
        extra_filter: str = "",
    ) -> list[SearchResult]:
        vector = self.embedder.generate_embedding(query_text)

        parts = []
        if doc_type:
            parts.append(f'doc_type == "{doc_type}"')
        if extra_filter:
            parts.append(extra_filter)
        milvus_filter = " && ".join(parts)

        raw = self.client.hybrid_search(
            query_vector = vector,
            query_text   = query_text,
            top_k        = top_k,
            filter       = milvus_filter,
        )
        return [self._to_search_result(r) for r in raw]
