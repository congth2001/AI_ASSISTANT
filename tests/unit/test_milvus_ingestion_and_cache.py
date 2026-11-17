from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.assistant.application.use_cases.chat_use_case import ChatUseCase
from src.modules.assistant.domain.entities.document_chunk import DocumentChunk
from src.modules.assistant.domain.errors import VectorStoreWriteError
from src.modules.assistant.infrastructure.repositories.milvus_ingestion_repository import (
    MilvusIngestionRepository,
)


def _chunks(n):
    return [
        DocumentChunk(doc_id=f"d{i}", doc_type="period_summary", text="x" * 5000, metadata={"year": 2026})
        for i in range(n)
    ]


def _repo(upsert_result=True, existing=None):
    client = MagicMock()
    client.upsert.return_value = upsert_result
    client.query.return_value = existing
    embedder = MagicMock()
    embedder.generate_embeddings.side_effect = lambda texts: [[0.1] * 4 for _ in texts]
    return MilvusIngestionRepository(embedder, client=client), client, embedder


@pytest.mark.asyncio
async def test_update_upserts_every_chunk_in_batch():
    repo, client, _ = _repo(existing=[{"embedding": [0.5] * 4}])
    await repo.update(_chunks(3))
    rows = client.upsert.call_args.kwargs["data"]
    assert [r["doc_id"] for r in rows] == ["d0", "d1", "d2"]
    assert all(r["embedding"] == [0.5] * 4 for r in rows)


@pytest.mark.asyncio
async def test_update_reembeds_when_stored_embedding_missing():
    repo, client, embedder = _repo(existing=None)
    await repo.update(_chunks(2))
    embedder.generate_embeddings.assert_called_once()
    assert all(r["embedding"] == [0.1] * 4 for r in client.upsert.call_args.kwargs["data"])


@pytest.mark.asyncio
async def test_insert_truncates_text_and_raises_on_failed_write():
    repo, client, _ = _repo(upsert_result=False)
    with pytest.raises(VectorStoreWriteError):
        await repo.insert(_chunks(2))
    assert all(len(r["text"]) == 4096 for r in client.upsert.call_args.kwargs["data"])


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"tool_success": True}, True),
        ({}, True),
        ({"needs_clarification": True}, False),
        ({"tool_success": False}, False),
        ({"tool_error_code": "sql_error"}, False),
    ],
)
def test_only_successful_answers_are_cacheable(metadata, expected):
    assert ChatUseCase._is_cacheable(metadata) is expected
