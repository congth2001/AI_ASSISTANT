from abc import ABC, abstractmethod
import pandas as pd
from src.domain.entities.document_chunk import DocumentChunk

class IDocumentSerializer(ABC):
    """Interface for document serialization"""
    @abstractmethod
    def serialize(self, data: pd.Series | pd.DataFrame) -> DocumentChunk:
        """Serialize data into a DocumentChunk"""
        pass
    
    @abstractmethod
    def save_jsonl(self, chunks: list[DocumentChunk], file_path: str) -> None:
        """Save a list of DocumentChunks to a JSONL file"""
        pass