from pymilvus import (
    MilvusClient,
    DataType,
    CollectionSchema,
    FieldSchema,
)
from src.domain.interfaces.i_ingestion_repository import IIngestionRepository
from src.domain.entities.document_chunk import DocumentChunk
from src.infrastructure.embedding.openai_embedding import OpenAIEmbedding


COLLECTION_NAME = "business_docs"
EMBEDDING_DIM   = 1536  # text-embedding-3-small


class MilvusIngestionRepository(IIngestionRepository):

    def __init__(
        self,
        uri             : str,             # "data/milvus.db" (local) hoặc "http://localhost:19530" (server)
        embedding_service: OpenAIEmbedding,
    ):
        self.client = MilvusClient(uri=uri)
        self.embedder = embedding_service
        self._ensure_collection()

    # ─────────────────────────────────────────
    # Setup collection
    # ─────────────────────────────────────────

    def _ensure_collection(self) -> None:
        if self.client.has_collection(COLLECTION_NAME):
            return

        schema = self.client.create_schema(auto_id=False)
        schema.add_field("doc_id",    DataType.VARCHAR, max_length=128, is_primary=True)
        schema.add_field("doc_type",  DataType.VARCHAR, max_length=32)
        schema.add_field("text",      DataType.VARCHAR, max_length=4096)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)

        # Metadata fields để filter trước khi search
        schema.add_field("year",       DataType.INT32)
        schema.add_field("month",      DataType.INT32)
        schema.add_field("customer_id",DataType.VARCHAR, max_length=128)
        schema.add_field("co_no",      DataType.BOOL)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name  = "embedding",
            index_type  = "HNSW",
            metric_type = "COSINE",
            params      = {"M": 16, "efConstruction": 200},
        )

        self.client.create_collection(
            collection_name = COLLECTION_NAME,
            schema          = schema,
            index_params    = index_params,
        )

    # ─────────────────────────────────────────
    # IIngestionRepository implementation
    # ─────────────────────────────────────────

    def list_existing_ids(self, doc_type: str) -> set[str]:
        results = self.client.query(
            collection_name = COLLECTION_NAME,
            filter          = f'doc_type == "{doc_type}"',
            output_fields   = ["doc_id"],
            limit           = 16384,
        )
        return {r["doc_id"] for r in results}

    def save(self, chunks: list[DocumentChunk]) -> None:
        """Batch insert — dùng cho transactions (append only)."""
        if not chunks:
            return
        self._upsert_batch(chunks)

    def upsert(self, chunk: DocumentChunk) -> None:
        """Upsert 1 document — dùng cho customer_profile, period_summary."""
        self._upsert_batch([chunk])

    # ─────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────

    def _upsert_batch(
        self,
        chunks    : list[DocumentChunk],
        batch_size: int = 100,
    ) -> None:
        """
        Tự động embed rồi upsert theo batch.
        Milvus upsert = insert nếu chưa có, update nếu đã có (theo primary key).
        """
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.text for c in batch]

            # Gọi embedding API theo batch — tránh gọi từng cái một
            vectors = self.embedder.embed_batch(texts)

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
                }
                for j, c in enumerate(batch)
            ]

            self.client.upsert(
                collection_name = COLLECTION_NAME,
                data            = rows,
            )