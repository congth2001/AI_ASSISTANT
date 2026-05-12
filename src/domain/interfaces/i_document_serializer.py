from abc import ABC, abstractmethod
import pandas as pd
from domain.entities.document_chunk import DocumentChunk

class IDocumentSerializer(ABC):
    """Interface for document serialization"""
    @abstractmethod
    def serialize(self, data: pd.Series | pd.DataFrame) -> DocumentChunk:
        """Serialize data into a DocumentChunk"""
        pass

    @abstractmethod
    def get_doc_id(self, data: pd.Series | pd.DataFrame) -> str:
        """Extract document ID from data"""
        pass