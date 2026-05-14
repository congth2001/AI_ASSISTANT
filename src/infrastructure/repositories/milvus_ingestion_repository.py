import asyncio
import uuid

from pymilvus import (
    MilvusClient,
    DataType
)
from src.domain.interfaces.i_ingestion_repository import IIngestionRepository
from src.domain.entities.document_chunk import DocumentChunk
from src.infrastructure.embedding.openai_embedding import OpenAIEmbedding


COLLECTION_NAME = "business_docs"
EMBEDDING_DIM   = 1536  # text-embedding-3-small


class MilvusIngestionRepository(IIngestionRepository):

    def __init__(
        self,
        embedding_service: OpenAIEmbedding,
        host: str = "localhost",
        port: str = "19530",
        collection_name: str = COLLECTION_NAME,
        embedding_dim: int = EMBEDDING_DIM,
    ):
        self.client = MilvusClient(uri=f"http://{host}:{port}")
        self.embedder = embedding_service
        self.collection_name = collection_name
        self.embedding_dim = embedding_dim
        self._ensure_collection()

    # ─────────────────────────────────────────
    # Setup collection
    # ─────────────────────────────────────────

    def _ensure_collection(self) -> None:
        if self.client.has_collection(self.collection_name):
            return

        schema = self.client.create_schema(auto_id=False)
        schema.add_field("doc_id",    DataType.VARCHAR, max_length=128, is_primary=True)
        schema.add_field("doc_type",  DataType.VARCHAR, max_length=32)
        schema.add_field("text",      DataType.VARCHAR, max_length=4096)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.embedding_dim)

        # Metadata fields để filter trước khi search
        schema.add_field("year",       DataType.INT16)
        schema.add_field("month",      DataType.INT8)
        schema.add_field("customer_id",DataType.VARCHAR, max_length=128)
        schema.add_field("co_no",      DataType.BOOL)
        schema.add_field("doanh_thu",  DataType.DOUBLE)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name  = "embedding",
            index_type  = "HNSW",
            metric_type = "COSINE",
            params      = {"M": 16, "efConstruction": 200},
        )

        self.client.create_collection(
            collection_name = self.collection_name,
            schema          = schema,
            index_params    = index_params,
        )

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
            collection_name = self.collection_name,
            filter          = " && ".join(expr_parts) if expr_parts else "",
            output_fields   = ["doc_id"],
            limit           = page_size,
        )

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
            collection_name = self.collection_name,
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
            collection_name = self.collection_name,
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
                    collection_name = self.collection_name,
                    filter          = f'doc_id == "{c.doc_id}"',
                    output_fields   = ["embedding"],
                    limit           = 1,
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