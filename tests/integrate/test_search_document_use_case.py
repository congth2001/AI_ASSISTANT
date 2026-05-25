"""
Integration tests for SearchDocumentsUseCase and MilvusSearchRepository.
Uses mocked IVectorDB and IEmbeddingService to isolate infrastructure.
"""

from unittest.mock import MagicMock
import pytest

from src.application.use_cases.search_document_use_case import SearchDocumentsUseCase
from src.domain.entities.analyzed_query import AnalyzedQuery
from src.domain.value_objects.doc_type import DocType
from src.domain.value_objects.query_intent import QueryIntent
from src.domain.value_objects.search_config import SearchConfig
from src.domain.entities.search_document_result import SearchDocumentsResult
from src.domain.entities.search_result import SearchResult
from src.domain.entities.time_filter import TimeFilter
from src.infrastructure.repositories.milvus_search_repository import MilvusSearchRepository


# ─────────────────────────────────────────────
# Fixtures & helpers
# ─────────────────────────────────────────────

DUMMY_VECTOR = [0.1] * 128


def make_analyzed(
    intent: QueryIntent = QueryIntent.REVENUE,
    customer_name: str | None = None,
    time_filter: TimeFilter | None = None,
    invoice_id: str | None = None,
    category_name: str | None = None,
    product_name: str | None = None,
    doc_types: list[DocType] | None = None,
) -> AnalyzedQuery:
    return AnalyzedQuery(
        original_query="test query",
        normalized="test query",
        intents=[intent],
        primary_intent=intent,
        time_filter=time_filter or TimeFilter(),
        customer_name=customer_name,
        category_name=category_name,
        product_name=product_name,
        invoice_id=invoice_id,
        doc_types=doc_types or [DocType.TRANSACTION],
    )


def make_result(
    doc_id: str = "doc1",
    year: int | None = None,
    month: int | None = None,
    customer_id: str | None = None,
) -> SearchResult:
    return SearchResult(
        doc_id=doc_id,
        doc_type="transaction",
        text="sample text",
        score=0.9,
        metadata={
            "year": year,
            "month": month,
            "customer_id": customer_id,
            "co_no": False,
        },
    )


def make_mock_repo(results: list[SearchResult] | None = None) -> MagicMock:
    repo = MagicMock()
    repo.search.return_value = results if results is not None else []
    return repo


# ─────────────────────────────────────────────
# SearchDocumentsUseCase — short-circuit
# ─────────────────────────────────────────────

class TestSearchDocumentsUseCaseShortCircuit:

    def test_unknown_intent_no_entity_returns_empty(self):
        repo = make_mock_repo()
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(intent=QueryIntent.UNKNOWN)
        result = uc.execute(analyzed)

        assert result.results == []
        assert result.used_fallback is False
        repo.search.assert_not_called()

    def test_unknown_intent_with_customer_does_not_short_circuit(self):
        repo = make_mock_repo([make_result()])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(intent=QueryIntent.UNKNOWN, customer_name="Anh Tuan")
        uc.execute(analyzed)

        repo.search.assert_called_once()

    def test_unknown_intent_with_time_filter_does_not_short_circuit(self):
        repo = make_mock_repo([make_result(year=2025, month=3)])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(
            intent=QueryIntent.UNKNOWN,
            time_filter=TimeFilter(year=2025, month=3),
        )
        uc.execute(analyzed)

        repo.search.assert_called_once()

    def test_unknown_intent_with_invoice_id_does_not_short_circuit(self):
        repo = make_mock_repo([make_result()])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(intent=QueryIntent.UNKNOWN, invoice_id="XB24169-0125")
        uc.execute(analyzed)

        repo.search.assert_called_once()

    def test_known_intent_no_entity_does_not_short_circuit(self):
        repo = make_mock_repo([make_result()])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(intent=QueryIntent.REVENUE)
        uc.execute(analyzed)

        repo.search.assert_called_once()


# ─────────────────────────────────────────────
# SearchDocumentsUseCase — fallback detection
# ─────────────────────────────────────────────

class TestSearchDocumentsUseCaseFallbackDetection:

    def test_no_fallback_when_results_empty(self):
        repo = make_mock_repo([])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(time_filter=TimeFilter(month=3, year=2025))
        result = uc.execute(analyzed)

        assert result.used_fallback is False

    def test_no_fallback_when_month_matches(self):
        repo = make_mock_repo([make_result(month=3, year=2025)])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(time_filter=TimeFilter(month=3, year=2025))
        result = uc.execute(analyzed)

        assert result.used_fallback is False

    def test_fallback_detected_on_month_mismatch(self):
        repo = make_mock_repo([make_result(month=12, year=2024)])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(time_filter=TimeFilter(month=3, year=2025))
        result = uc.execute(analyzed)

        assert result.used_fallback is True

    def test_fallback_detected_on_year_mismatch(self):
        repo = make_mock_repo([make_result(year=2024)])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(time_filter=TimeFilter(year=2025))
        result = uc.execute(analyzed)

        assert result.used_fallback is True

    def test_no_fallback_when_year_matches(self):
        repo = make_mock_repo([make_result(year=2025)])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(time_filter=TimeFilter(year=2025))
        result = uc.execute(analyzed)

        assert result.used_fallback is False

    def test_fallback_detected_on_customer_mismatch(self):
        repo = make_mock_repo([make_result(customer_id="nguyen_van_b")])
        uc = SearchDocumentsUseCase(repo)

        # _detect_fallback normalizes "Nguyen Van A" → "nguyen_van_a"
        analyzed = make_analyzed(customer_name="Nguyen Van A")
        result = uc.execute(analyzed)

        assert result.used_fallback is True

    def test_no_fallback_when_customer_matches(self):
        repo = make_mock_repo([make_result(customer_id="nguyen_van_a")])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(customer_name="Nguyen Van A")
        result = uc.execute(analyzed)

        assert result.used_fallback is False

    def test_no_fallback_when_no_filter_set(self):
        repo = make_mock_repo([make_result()])
        uc = SearchDocumentsUseCase(repo)

        analyzed = make_analyzed(intent=QueryIntent.REVENUE)
        result = uc.execute(analyzed)

        assert result.used_fallback is False


# ─────────────────────────────────────────────
# SearchDocumentsUseCase — result structure
# ─────────────────────────────────────────────

class TestSearchDocumentsUseCaseResult:

    def test_result_contains_analyzed_query(self):
        analyzed = make_analyzed()
        repo = make_mock_repo([make_result()])
        uc = SearchDocumentsUseCase(repo)

        result = uc.execute(analyzed)

        assert result.analyzed_query is analyzed

    def test_result_contains_search_results(self):
        search_results = [make_result("d1"), make_result("d2")]
        repo = make_mock_repo(search_results)
        uc = SearchDocumentsUseCase(repo)

        result = uc.execute(make_analyzed())

        assert result.results == search_results

    def test_returns_search_documents_result_type(self):
        repo = make_mock_repo([make_result()])
        uc = SearchDocumentsUseCase(repo)

        result = uc.execute(make_analyzed())

        assert isinstance(result, SearchDocumentsResult)


# ─────────────────────────────────────────────
# MilvusSearchRepository — filter chain
# ─────────────────────────────────────────────

class TestMilvusSearchRepositoryFilterChain:

    def _make_repo(self) -> MilvusSearchRepository:
        return MilvusSearchRepository(client=MagicMock(), embedding_service=MagicMock())

    def test_invoice_lookup_single_filter(self):
        repo = self._make_repo()
        analyzed = make_analyzed(invoice_id="XB24169-0125")

        chain = repo._build_filter_chain(analyzed)

        assert chain == ['so_phieu == "XB24169-0125"']

    def test_no_filter_only_fallback_when_no_constraints(self):
        repo = self._make_repo()
        analyzed = AnalyzedQuery(
            original_query="q", normalized="q",
            intents=[QueryIntent.REVENUE], primary_intent=QueryIntent.REVENUE,
            time_filter=TimeFilter(), doc_types=[],
        )

        chain = repo._build_filter_chain(analyzed)

        assert chain == [""]

    def test_chain_ends_with_empty_filter(self):
        repo = self._make_repo()
        analyzed = make_analyzed(
            time_filter=TimeFilter(year=2025, month=3),
            customer_name="Anh Tuan",
        )

        chain = repo._build_filter_chain(analyzed)

        assert chain[-1] == ""

    def test_chain_contains_full_strict_filter(self):
        repo = self._make_repo()
        analyzed = make_analyzed(
            doc_types=[DocType.TRANSACTION],
            customer_name="Anh Tuan",
            time_filter=TimeFilter(year=2025, month=3),
        )

        chain = repo._build_filter_chain(analyzed)
        strictest = chain[0]

        assert 'doc_type == "transaction"' in strictest
        assert "year == 2025" in strictest
        assert "month == 3" in strictest
        assert "anh_tuan" in strictest

    def test_chain_has_no_month_variant(self):
        repo = self._make_repo()
        analyzed = make_analyzed(
            doc_types=[DocType.TRANSACTION],
            time_filter=TimeFilter(year=2025, month=3),
        )

        chain = repo._build_filter_chain(analyzed)
        no_month_filters = [f for f in chain if "year == 2025" in f and "month" not in f]

        assert len(no_month_filters) >= 1

    def test_debt_intent_adds_co_no_expr(self):
        repo = self._make_repo()
        analyzed = make_analyzed(intent=QueryIntent.DEBT, customer_name="Anh Nam")

        chain = repo._build_filter_chain(analyzed)
        strictest = chain[0]

        assert "co_no == true" in strictest

    def test_no_duplicate_filters_in_chain(self):
        repo = self._make_repo()
        analyzed = make_analyzed(
            doc_types=[DocType.TRANSACTION],
            time_filter=TimeFilter(year=2025),
        )

        chain = repo._build_filter_chain(analyzed)

        assert len(chain) == len(set(chain))

    def test_year_only_no_month_variant_skipped(self):
        repo = self._make_repo()
        # Only year, no month → the "no_month" branch shouldn't add duplicates
        analyzed = make_analyzed(
            doc_types=[DocType.PERIOD_SUMMARY],
            time_filter=TimeFilter(year=2025),
        )

        chain = repo._build_filter_chain(analyzed)

        assert len(chain) == len(set(chain))


# ─────────────────────────────────────────────
# MilvusSearchRepository — hybrid search fallback
# ─────────────────────────────────────────────

class TestMilvusSearchRepositoryHybridSearch:

    def _make_raw(self, doc_id: str = "d1", year: int = 2025, month: int = 3) -> dict:
        return {
            "id": doc_id,
            "score": 0.85,
            "content": "nội dung phiếu",
            "metadata": {
                "doc_type": "transaction",
                "year": year,
                "month": month,
                "customer_id": "anh_tuan",
                "co_no": False,
            },
        }

    def test_returns_results_from_first_matching_filter(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = [self._make_raw()]

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        analyzed = make_analyzed(time_filter=TimeFilter(year=2025, month=3))

        results = repo.search(analyzed)

        assert len(results) == 1
        assert results[0].doc_id == "d1"
        # Should stop at first success
        assert client.hybrid_search.call_count == 1

    def test_falls_back_to_next_filter_when_empty(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR

        fallback_raw = self._make_raw(doc_id="fallback_doc", year=2024, month=12)
        # First call → empty, second call → results
        client.hybrid_search.side_effect = [[], [fallback_raw]]

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        analyzed = make_analyzed(
            doc_types=[DocType.TRANSACTION],
            time_filter=TimeFilter(year=2025, month=3),
        )

        results = repo.search(analyzed)

        assert len(results) == 1
        assert results[0].doc_id == "fallback_doc"
        assert client.hybrid_search.call_count == 2

    def test_returns_empty_when_all_filters_yield_nothing(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = []

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        analyzed = make_analyzed(time_filter=TimeFilter(year=2025, month=3))

        results = repo.search(analyzed)

        assert results == []

    def test_result_metadata_mapped_correctly(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = [self._make_raw("doc99", year=2025, month=3)]

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        results = repo.search(make_analyzed())

        r = results[0]
        assert r.doc_id == "doc99"
        assert r.metadata["year"] == 2025
        assert r.metadata["month"] == 3
        assert r.metadata["customer_id"] == "anh_tuan"
        assert r.doc_type == "transaction"
        assert r.score == 0.85

    def test_top_k_resolved_by_ranking_intent(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = []

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        repo.search(make_analyzed(intent=QueryIntent.RANKING))

        call_kwargs = client.hybrid_search.call_args_list[0][1]
        assert call_kwargs["top_k"] == SearchConfig.TOP_K_BY_INTENT[QueryIntent.RANKING]

    def test_top_k_resolved_by_invoice_intent(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = []

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        repo.search(make_analyzed(intent=QueryIntent.INVOICE, invoice_id="XB001"))

        call_kwargs = client.hybrid_search.call_args_list[0][1]
        assert call_kwargs["top_k"] == SearchConfig.TOP_K_BY_INTENT[QueryIntent.INVOICE]

    def test_ef_resolved_by_comparison_intent(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = []

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        repo.search(make_analyzed(intent=QueryIntent.COMPARISON))

        call_kwargs = client.hybrid_search.call_args_list[0][1]
        assert call_kwargs["ef"] == SearchConfig.EF_BY_INTENT[QueryIntent.COMPARISON]

    def test_ef_uses_default_for_revenue_intent(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = []

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        repo.search(make_analyzed(intent=QueryIntent.REVENUE))

        call_kwargs = client.hybrid_search.call_args_list[0][1]
        assert call_kwargs["ef"] == SearchConfig.DEFAULT_EF

    def test_invoice_lookup_uses_single_strict_filter(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = [self._make_raw()]

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        repo.search(make_analyzed(intent=QueryIntent.INVOICE, invoice_id="XB24169-0125"))

        assert client.hybrid_search.call_count == 1
        call_kwargs = client.hybrid_search.call_args_list[0][1]
        assert call_kwargs["filter"] == 'so_phieu == "XB24169-0125"'

    def test_embedding_called_with_original_query(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = []

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        analyzed = make_analyzed()
        repo.search(analyzed)

        embedder.generate_embedding.assert_called_once_with("test query")


# ─────────────────────────────────────────────
# End-to-end: UseCase + Repository (mocked infra)
# ─────────────────────────────────────────────

class TestSearchDocumentsEndToEnd:

    def test_full_flow_with_matching_results(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR
        client.hybrid_search.return_value = [{
            "id": "e2e_doc",
            "score": 0.92,
            "content": "doanh thu tháng 3/2025",
            "metadata": {
                "doc_type": "period_summary",
                "year": 2025,
                "month": 3,
                "customer_id": None,
                "co_no": False,
            },
        }]

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        uc = SearchDocumentsUseCase(repo)
        analyzed = make_analyzed(
            intent=QueryIntent.REVENUE,
            time_filter=TimeFilter(year=2025, month=3),
            doc_types=[DocType.PERIOD_SUMMARY],
        )

        result = uc.execute(analyzed)

        assert len(result.results) == 1
        assert result.results[0].doc_id == "e2e_doc"
        assert result.used_fallback is False

    def test_full_flow_detects_fallback_on_time_mismatch(self):
        client = MagicMock()
        embedder = MagicMock()
        embedder.generate_embedding.return_value = DUMMY_VECTOR

        # All filters with constraints fail; empty filter returns old data
        def hybrid_search_side_effect(**kw):
            if kw.get("filter", ""):
                return []
            return [{
                "id": "old_doc",
                "score": 0.7,
                "content": "doanh thu tháng 12/2024",
                "metadata": {
                    "doc_type": "period_summary",
                    "year": 2024,
                    "month": 12,
                    "customer_id": None,
                    "co_no": False,
                },
            }]

        client.hybrid_search.side_effect = hybrid_search_side_effect

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        uc = SearchDocumentsUseCase(repo)
        analyzed = make_analyzed(
            intent=QueryIntent.REVENUE,
            time_filter=TimeFilter(year=2025, month=3),
            doc_types=[DocType.PERIOD_SUMMARY],
        )

        result = uc.execute(analyzed)

        assert len(result.results) == 1
        assert result.used_fallback is True

    def test_unknown_query_no_entity_never_hits_vector_db(self):
        client = MagicMock()
        embedder = MagicMock()

        repo = MilvusSearchRepository(client=client, embedding_service=embedder)
        uc = SearchDocumentsUseCase(repo)
        analyzed = make_analyzed(intent=QueryIntent.UNKNOWN)

        result = uc.execute(analyzed)

        assert result.results == []
        client.hybrid_search.assert_not_called()
        embedder.generate_embedding.assert_not_called()
