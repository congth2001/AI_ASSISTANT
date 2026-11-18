import logging
from unittest.mock import MagicMock, patch

import pytest

from src.modules.assistant.application.use_cases.search_documents_use_case import SearchDocumentsUseCase
from src.modules.assistant.domain.constants.doc_type import DocType
from src.modules.assistant.domain.constants.query_intent import QueryIntent
from src.modules.assistant.domain.entities.analyzed_query import AnalyzedQuery
from src.modules.assistant.domain.entities.time_filter import TimeFilter
from src.modules.assistant.domain.errors import EmbeddingRequestError, VectorStoreQueryError
from src.modules.assistant.infrastructure.database.milvus_client import (
    MilvusClient,
    quote_filter_value,
    _KEYWORD_SCAN_LIMIT,
)
from src.modules.assistant.infrastructure.llm.openai_embedding import OpenAIEmbedding
from src.modules.assistant.infrastructure.repositories.milvus_ingestion_repository import (
    MilvusIngestionRepository,
)
from src.modules.assistant.infrastructure.repositories.milvus_search_repository import (
    MilvusSearchRepository,
)

VECTOR = [0.1] * 4


def analyzed(**kw) -> AnalyzedQuery:
    return AnalyzedQuery(
        original_query="q",
        normalized="q",
        intents=[QueryIntent.REVENUE],
        primary_intent=QueryIntent.REVENUE,
        time_filter=kw.pop("time_filter", TimeFilter()),
        customer_name=kw.pop("customer_name", None),
        category_name=None,
        invoice_id=kw.pop("invoice_id", None),
        doc_types=kw.pop("doc_types", [DocType.TRANSACTION]),
    )


def raw_hit(doc_id="d1"):
    return {"id": doc_id, "score": 0.5, "content": "x", "metadata": {"doc_type": "transaction"}}


def milvus_client_with(py_client) -> MilvusClient:
    client = MilvusClient()
    client._connection = py_client  # bỏ qua kết nối thật
    return client


# ───────────── filter chain ─────────────

def test_filter_chain_never_references_so_phieu():
    repo = MilvusSearchRepository(client=MagicMock(), embedding_service=MagicMock())
    chain = repo._build_filter_chain(analyzed(invoice_id="XB001", customer_name="Anh Tiệc X3",
                                              time_filter=TimeFilter(year=2025, month=3)))
    assert chain
    assert not any("so_phieu" in c for c in chain)
    assert chain[0] == (
        '(doc_type == "transaction") && customer_id == "anh_tiệc_x3" && year == 2025 && month == 3'
    )
    assert chain[-1] == ""


# ───────────── escaping ─────────────

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("abc", '"abc"'),
        ('a"b', '"a\\"b"'),
        ("a\\b", '"a\\\\b"'),
        ('x" || doc_id != "', '"x\\" || doc_id != \\""'),
        ("line1\nline2\tz", '"line1\\nline2\\tz"'),
        ("a\x00b", '"ab"'),
    ],
)
def test_quote_filter_value_escapes(raw, expected):
    assert quote_filter_value(raw) == expected


def test_delete_get_and_page_filters_are_escaped():
    py = MagicMock()
    client = milvus_client_with(py)
    client.delete_embedding('a"b')
    assert py.delete.call_args.kwargs["filter"] == 'doc_id == "a\\"b"'

    inner = MagicMock()
    inner.query.return_value = [{"doc_id": "x"}]
    repo = MilvusIngestionRepository(MagicMock(), client=inner)
    import asyncio
    asyncio.run(repo.get_by_doc_id('i"d'))
    assert inner.query.call_args.kwargs["filter"] == 'doc_id == "i\\"d"'


def test_customer_filter_value_is_quoted():
    repo = MilvusSearchRepository(client=MagicMock(), embedding_service=MagicMock())
    # Slug hóa đã bỏ dấu nháy; literal vẫn phải được quote và không chứa dấu nháy thô bên trong.
    chain = repo._build_filter_chain(analyzed(customer_name='bad" || x == "'))
    assert 'customer_id == "bad_x"' in chain[0]


# ───────────── errors vs empty ─────────────

def test_search_similar_raises_domain_error_with_cause():
    py = MagicMock()
    py.search.side_effect = RuntimeError("boom")
    client = milvus_client_with(py)
    with pytest.raises(VectorStoreQueryError) as exc:
        client.search_similar(VECTOR)
    assert exc.value.code == "vector_store_query"
    assert isinstance(exc.value.__cause__, RuntimeError)


def test_query_distinguishes_empty_from_error():
    py = MagicMock()
    py.query.return_value = []
    client = milvus_client_with(py)
    assert client.query("doc_id != ''") == []
    py.query.side_effect = RuntimeError("down")
    with pytest.raises(VectorStoreQueryError):
        client.query("doc_id != ''")


def test_connection_failure_is_domain_error():
    with patch(
        "src.modules.assistant.infrastructure.database.milvus_client.PyMilvusClient",
        side_effect=RuntimeError("unreachable"),
    ):
        client = MilvusClient()
        with pytest.raises(VectorStoreQueryError):
            client.keyword_search("abc")
        with pytest.raises(VectorStoreQueryError):
            client.hybrid_search(VECTOR, "abc")


def test_hybrid_propagates_keyword_failure():
    py = MagicMock()
    py.search.return_value = [[]]
    py.query.side_effect = RuntimeError("down")
    client = milvus_client_with(py)
    with pytest.raises(VectorStoreQueryError):
        client.hybrid_search(VECTOR, "abc")


def test_keyword_search_warns_when_scan_cap_reached(caplog):
    py = MagicMock()
    py.query.return_value = [
        {"doc_id": f"d{i}", "text": "abc", "doc_type": "transaction"} for i in range(_KEYWORD_SCAN_LIMIT)
    ]
    client = milvus_client_with(py)
    with caplog.at_level(logging.WARNING):
        results = client.keyword_search("abc", top_k=3)
    assert len(results) == 3
    assert any("scan cap" in r.message for r in caplog.records)
    assert py.query.call_args.kwargs["limit"] == _KEYWORD_SCAN_LIMIT


def test_query_all_uses_iterator_and_closes():
    py = MagicMock()
    iterator = MagicMock()
    iterator.next.side_effect = [[{"doc_id": "a"}], [{"doc_id": "b"}], []]
    py.query_iterator.return_value = iterator
    client = milvus_client_with(py)
    assert client.query_all('doc_type == "x"', ["doc_id"]) == [{"doc_id": "a"}, {"doc_id": "b"}]
    iterator.close.assert_called_once()


# ───────────── fallback chain ─────────────

def _search_repo(client):
    embedder = MagicMock()
    embedder.generate_embedding.return_value = VECTOR
    return MilvusSearchRepository(client=client, embedding_service=embedder)


def test_fallback_continues_on_valid_empty_results():
    client = MagicMock()
    client.hybrid_search.side_effect = [[], [], [raw_hit()]]
    repo = _search_repo(client)
    results = repo.search(analyzed(customer_name="a", time_filter=TimeFilter(year=2025, month=3)))
    assert [r.doc_id for r in results] == ["d1"]
    assert client.hybrid_search.call_count == 3


def test_fallback_stops_immediately_on_infrastructure_error():
    client = MagicMock()
    client.hybrid_search.side_effect = VectorStoreQueryError(operation="search_similar", collection="c")
    repo = _search_repo(client)
    with pytest.raises(VectorStoreQueryError):
        repo.search(analyzed(customer_name="a", time_filter=TimeFilter(year=2025, month=3)))
    assert client.hybrid_search.call_count == 1


# ───────────── use case ─────────────

def test_use_case_returns_empty_result_with_error_code_when_store_fails():
    repo = MagicMock()
    repo.search.side_effect = VectorStoreQueryError(operation="x", collection="c")
    result = SearchDocumentsUseCase(repo).execute_analyzed(analyzed())
    assert result.results == []
    assert result.error_code == "vector_store_query"


def test_use_case_normal_result_has_no_error_code():
    repo = MagicMock()
    repo.search.return_value = []
    assert SearchDocumentsUseCase(repo).execute_analyzed(analyzed()).error_code is None


@pytest.mark.asyncio
async def test_execute_analyzed_async_runs_in_thread():
    import threading

    seen = {}
    repo = MagicMock()

    def search(_):
        seen["thread"] = threading.current_thread()
        return []

    repo.search.side_effect = search
    result = await SearchDocumentsUseCase(repo).execute_analyzed_async(analyzed())
    assert result.results == []
    assert seen["thread"] is not threading.main_thread()


# ───────────── ingestion paging ─────────────

@pytest.mark.asyncio
async def test_page_existing_ids_is_ordered_complete_and_cursor_correct():
    client = MagicMock()
    client.query_all.return_value = [{"doc_id": i} for i in ["d5", "d1", "d3", "d2", "d4"]]
    repo = MilvusIngestionRepository(MagicMock(), client=client)

    ids, cursor = await repo.page_existing_ids("transaction", "d0", 2)
    assert ids == {"d1", "d2"} and cursor == "d2"
    assert client.query_all.call_args.kwargs["filter"] == 'doc_type == "transaction" && doc_id > "d0"'

    ids, cursor = await repo.page_existing_ids("all", None, 10)
    assert ids == {"d1", "d2", "d3", "d4", "d5"} and cursor is None
    assert client.query_all.call_args.kwargs["filter"] == ""


@pytest.mark.asyncio
async def test_page_existing_ids_propagates_store_errors():
    client = MagicMock()
    client.query_all.side_effect = VectorStoreQueryError(operation="query_all", collection="c")
    repo = MilvusIngestionRepository(MagicMock(), client=client)
    with pytest.raises(VectorStoreQueryError):
        await repo.page_existing_ids("all", None, 5)


# ───────────── OpenAI embedding ─────────────

def test_embedding_configures_timeout_and_preserves_cause(caplog):
    with patch("src.modules.assistant.infrastructure.llm.openai_embedding.OpenAI") as openai:
        emb = OpenAIEmbedding(api_key="k", timeout=7, max_retries=1)
        assert openai.call_args.kwargs["timeout"] == 7
        assert openai.call_args.kwargs["max_retries"] == 1
        openai.return_value.embeddings.create.side_effect = RuntimeError("rate limited")
        with caplog.at_level(logging.ERROR), pytest.raises(EmbeddingRequestError) as exc:
            emb.generate_embedding("x")
        assert isinstance(exc.value.__cause__, RuntimeError)
        assert any("rate limited" in r.getMessage() for r in caplog.records)
        with pytest.raises(Exception) as batch_exc:
            emb.generate_embeddings(["a"])
        assert isinstance(batch_exc.value.__cause__, RuntimeError)
