import asyncio

from src.modules.assistant.domain.errors import VectorStoreWriteError
from src.modules.assistant.domain.repositories.i_ingestion_repository import IIngestionRepository
from src.modules.assistant.domain.entities.document_chunk import DocumentChunk
from src.modules.assistant.domain.ports.i_embedding_service import IEmbeddingService
from src.modules.assistant.domain.ports.i_vector_db import IVectorDB
from src.modules.assistant.infrastructure.database.milvus_client import quote_filter_value

_MAX_TEXT_LENGTH = 4096  # khớp độ dài trường `text` trong schema collection


class MilvusIngestionRepository(IIngestionRepository):

    def __init__(
        self,
        embedding_service: IEmbeddingService,
        client: IVectorDB = None,
        collection_name: str = "business_data",
        embedding_dim: int = 1024,
    ):
        self.client = client
        self.embedder = embedding_service
        self.collection_name = collection_name
        self.embedding_dim = embedding_dim
        

    # ─────────────────────────────────────────
    # IIngestionRepository implementation
    # ─────────────────────────────────────────

    async def page_existing_ids(
        self,
        doc_type : str,
        cursor   : str | None,
        page_size: int,
    ) -> tuple[set[str], str | None]:
        """Trang `doc_id` đã tồn tại, theo thứ tự tăng dần của `doc_id` (xác định).

        Milvus `query(limit=N)` không bảo đảm thứ tự, nên lấy N bản ghi tùy ý rồi lấy max làm cursor sẽ
        bỏ sót id. Vì vậy quét đầy đủ phần `doc_id > cursor` bằng iterator (chỉ cột `doc_id`), sort rồi
        cắt `page_size`. `next_cursor` chỉ có khi còn trang sau. Ném VectorStoreQueryError khi Milvus lỗi.
        """
        expr_parts: list[str] = []
        if doc_type != "all":
            expr_parts.append(f"doc_type == {quote_filter_value(doc_type)}")
        if cursor:
            expr_parts.append(f"doc_id > {quote_filter_value(cursor)}")

        results = await asyncio.to_thread(
            self.client.query_all,
            filter        = " && ".join(expr_parts),
            output_fields = ["doc_id"],
        )

        if not results:
            return set(), None

        all_ids     = sorted({r["doc_id"] for r in results})
        page        = all_ids[:page_size]
        next_cursor = page[-1] if len(all_ids) > page_size else None
        return set(page), next_cursor

    async def insert(self, chunks: list[DocumentChunk]) -> None:
        """Batch insert new documents"""
        if not chunks:
            return
        await self._insert_batch(chunks)

    async def update(self, chunks: list[DocumentChunk]) -> None:
        """Batch update existing documents"""
        if not chunks:
            return
        await self._update_batch(chunks)

    async def get_period_revenue(self, year: int, month: int) -> float:
        """Return total revenue for a specific period, used for calculating month-over-month growth in period summaries."""
        filter_str = f'doc_type == "period_summary" && year == {int(year)} && month == {int(month)}'
        results = await asyncio.to_thread(
            self.client.query,
            filter          = filter_str,
            output_fields   = ["doanh_thu"],
            limit           = 1,
        )
        if results:
            return results[0].get("doanh_thu", 0.0)
        return 0.0

    async def get_by_doc_id(self, doc_id: str) -> dict:
        """Get document by ID for a given chunk (used for upsert logic)"""
        filter_str = f"doc_id == {quote_filter_value(doc_id)}"
        results = await asyncio.to_thread(
            self.client.query,
            filter          = filter_str,
            output_fields   = ["doc_id", "doanh_thu", "co_no"],
            limit           = 1,
        )

        return results[0] if results else None

    # ─────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────

    async def _insert_batch(
        self,
        chunks    : list[DocumentChunk],
        batch_size: int = 10,
    ) -> None:
        """
        Upsert batch of documents with embedding generation. 
        For simplicity, we upsert in batches without checking existing IDs (idempotency is handled by Milvus on primary key conflict).
        """
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.text for c in batch]

            # Embedding là I/O đồng bộ: chạy trong thread để không chặn event loop
            vectors = await asyncio.to_thread(self.embedder.generate_embeddings, texts)

            rows = [self._to_row(c, vectors[j]) for j, c in enumerate(batch)]
            await self._upsert_rows(rows)
    
    async def _update_batch(
        self,
        chunks    : list[DocumentChunk],
        batch_size: int = 10,
    ) -> None:
        """
        Update batch of existing documents, reusing the stored embedding.
        Chunks whose embedding cannot be found are re-embedded.
        """
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            rows: list[dict] = []
            missing: list[DocumentChunk] = []

            for c in batch:
                existed_doc = await asyncio.to_thread(
                    self.client.query,
                    filter        = f"doc_id == {quote_filter_value(c.doc_id)}",
                    output_fields = ["embedding"],
                    limit         = 1,
                )
                embedding = existed_doc[0].get("embedding") if existed_doc else None
                if embedding:
                    rows.append(self._to_row(c, embedding))
                else:
                    missing.append(c)

            if missing:
                vectors = await asyncio.to_thread(
                    self.embedder.generate_embeddings, [c.text for c in missing]
                )
                rows.extend(self._to_row(c, vectors[j]) for j, c in enumerate(missing))

            await self._upsert_rows(rows)

    @staticmethod
    def _to_row(chunk: DocumentChunk, embedding: list[float]) -> dict:
        """Flatten metadata — chỉ lấy field đã khai báo trong schema."""
        return {
            "doc_id"     : chunk.doc_id,
            "doc_type"   : chunk.doc_type,
            "text"       : chunk.text[:_MAX_TEXT_LENGTH],
            "embedding"  : embedding,
            "year"       : chunk.metadata.get("year",        0),
            "month"      : chunk.metadata.get("month",       0),
            "customer_id": chunk.metadata.get("customer_id", ""),
            "co_no"      : chunk.metadata.get("co_no",       False),
            "doanh_thu"  : float(chunk.metadata.get("doanh_thu", 0.0)),
        }

    async def _upsert_rows(self, rows: list[dict]) -> None:
        """Upsert one batch; MilvusClient reports failure via return value, so raise here."""
        if not rows:
            return
        ok = await asyncio.to_thread(
            self.client.upsert,
            collection_name = self.collection_name,
            data            = rows,
        )
        if ok is False:
            raise VectorStoreWriteError(collection=self.collection_name, count=len(rows))
