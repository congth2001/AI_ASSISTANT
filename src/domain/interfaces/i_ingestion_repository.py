from abc import ABC, abstractmethod
from src.domain.entities.document_chunk import DocumentChunk

class IIngestionRepository(ABC):
    """Interface for ingestion repository"""
    @abstractmethod
    def save(self, chunks: list[DocumentChunk]) -> None:
        """Save document chunks to the repository"""
        pass

    @abstractmethod
    def list_existing_ids(self, doc_type: str) -> set[str]:
        """List existing document IDs of a specific type"""
        pass

    @abstractmethod
    def upsert(self, chunk: DocumentChunk) -> None:
        """Insert or update a document chunk in the repository"""
        pass