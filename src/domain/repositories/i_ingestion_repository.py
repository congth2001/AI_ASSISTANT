from abc import ABC, abstractmethod
from src.domain.entities.document_chunk import DocumentChunk

class IIngestionRepository(ABC):
    """Interface for ingestion repository"""
    @abstractmethod
    async def insert(self, chunks: list[DocumentChunk]) -> None:
        """Batch insert new documents"""
        pass

    @abstractmethod
    async def page_existing_ids(self, doc_type: str, cursor: str | None, page_size: int) -> tuple[set[str], str | None]:
        """List existing document IDs using cursor-based pagination.
        Returns (doc_ids, next_cursor). next_cursor is None when no more pages."""
        pass

    @abstractmethod
    async def update(self, chunks: list[DocumentChunk]) -> None:
        """Batch update existing documents"""
        pass
    
    @abstractmethod
    async def get_by_doc_id(self, doc_id: str) -> dict:
        """Get the document ID for a given chunk (used for upsert logic)"""
        pass

    @abstractmethod
    async def get_period_revenue(self, year: int, month: int) -> float:
        """Get total revenue for a specific period (year and month)"""
        pass
