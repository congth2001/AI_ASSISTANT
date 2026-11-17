from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class IVectorDB(ABC):
    """Interface for vector database operations"""

    @abstractmethod
    def store_embedding(self, id: str, vector: List[float], metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Store an embedding vector"""
        pass

    @abstractmethod
    def search_similar(
        self,
        query_vector  : List[float],
        top_k         : int = 5,
        filter        : str = "",
        output_fields : Optional[List[str]] = None,
        search_params : Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Vector similarity search with optional metadata filter.
        Returns list of {"id", "score", "content", "metadata"} dicts."""
        pass

    @abstractmethod
    def query(self, filter: str, output_fields: Optional[List[str]] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Query vectors based on metadata filters"""
        pass

    @abstractmethod
    def delete_embedding(self, id: str) -> bool:
        """Delete an embedding by ID"""
        pass

    @abstractmethod
    def hybrid_search(
        self,
        query_vector  : List[float],
        query_text    : str,
        top_k         : int = 5,
        filter        : str = "",
        ef            : int = 100,
        vector_weight : float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """Hybrid search combining vector similarity and keyword matching via RRF.
        Returns list of {"id", "score", "content", "metadata"} dicts."""
        pass

    @abstractmethod
    def keyword_search(
        self,
        query_text    : str,
        top_k         : int = 5,
        filter        : str = "",
        case_sensitive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Keyword search by matching query terms against text field.
        Returns list of {"id", "score", "content", "metadata"} dicts."""
        pass
