import asyncio
from src.domain.interfaces.i_ingestion_repository import IIngestionRepository
from src.domain.entities.document_chunk import DocumentChunk
from src.domain.interfaces.i_embedding_service import IEmbeddingService
from src.domain.interfaces.i_vector_db import IVectorDB

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
        expr_parts: list[str] = []
        if doc_type != "all":
            expr_parts.append(f'doc_type == "{doc_type}"')
        if cursor:
            expr_parts.append(f'doc_id > "{cursor}"')

        results = await asyncio.to_thread(
            self.client.query,
            filter          = " && ".join(expr_parts) if expr_parts else "",
            output_fields   = ["doc_id"],
            limit           = page_size,
        )

        if not results:
            return set(), None

        doc_ids     = sorted(r["doc_id"] for r in results)
        next_cursor = doc_ids[-1] if len(doc_ids) == page_size else None
        return set(doc_ids), next_cursor

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
        filter_str = f'doc_type == "period_summary" && year == {year} && month == {month}'
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
        filter_str = f'doc_id == "{doc_id}"'
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

            # Call embedding service in async thread to avoid blocking event loop
            vectors = self.embedder.generate_embeddings(texts)

            rows = [
                {
                    "doc_id"     : c.doc_id,
                    "doc_type"   : c.doc_type,
                    "text"       : c.text,
                    "embedding"  : vectors[j],
                    # Flatten metadata — chỉ lấy field đã khai báo trong schema
                    "year"       : c.metadata.get("year",        0),
                    "month"      : c.metadata.get("month",       0),
                    "customer_id": c.metadata.get("customer_id", ""),
                    "co_no"      : c.metadata.get("co_no",       False),
                    "doanh_thu"  : float(c.metadata.get("doanh_thu", 0.0)),
                }
                for j, c in enumerate(batch)
            ]

            await asyncio.to_thread(
                self.client.upsert,
                collection_name = self.collection_name,
                data            = rows,
            )
    
    async def _update_batch(
        self,
        chunks    : list[DocumentChunk],
        batch_size: int = 10,
    ) -> None:
        """
        Update batch of existing documents without embedding generation.
        """
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            for j, c in enumerate(batch):
                existed_doc = await asyncio.to_thread(
                    self.client.query,
                    filter        = f'doc_id == "{c.doc_id}"',
                    output_fields = ["embedding"],
                    limit         = 1,
                )
                rows = [
                    {
                        "doc_id"     : c.doc_id,
                        "doc_type"   : c.doc_type,
                        "text"       : c.text,
                        "embedding"  : existed_doc[0].get("embedding", []) if existed_doc else [],
                        # Flatten metadata — chỉ lấy field đã khai báo trong schema
                        "year"       : c.metadata.get("year",        0),
                        "month"      : c.metadata.get("month",       0),
                        "customer_id": c.metadata.get("customer_id", ""),
                        "co_no"      : c.metadata.get("co_no",       False),
                        "doanh_thu"  : float(c.metadata.get("doanh_thu", 0.0)),
                    }
                ]

            await asyncio.to_thread(
                self.client.upsert,
                collection_name = self.collection_name,
                data            = rows,
            )