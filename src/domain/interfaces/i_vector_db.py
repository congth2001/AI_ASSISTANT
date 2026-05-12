from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class IVectorDB(ABC):
    """Interface for vector database operations"""

    @abstractmethod
    async def store_embedding(self, id: str, vector: List[float], metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Store an embedding vector"""
        pass

    @abstractmethod
    async def search_similar(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for similar vectors"""
        pass

    @abstractmethod
    async def delete_embedding(self, id: str) -> bool:
        """Delete an embedding by ID"""
        pass

    @abstractmethod
    async def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        top_k: int = 5,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3
    ) -> List[Dict[str, Any]]:
        """Hybrid search combining vector similarity and keyword matching"""
        pass

    @abstractmethod
    async def keyword_search(
        self,
        query_text: str,
        top_k: int = 5,
        case_sensitive: bool = False
    ) -> List[Dict[str, Any]]:
        """Keyword/BM25-like search by matching query terms"""
        pass
