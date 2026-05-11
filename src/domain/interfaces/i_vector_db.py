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


class IEmbeddingService(ABC):
    """Interface for embedding service"""

    @abstractmethod
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for text"""
        pass

    @abstractmethod
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        pass


class IDataRepository(ABC):
    """Interface for data repository operations"""

    @abstractmethod
    async def get_business_data(self, data_type: str, date_range: Optional['DateRange'] = None) -> List[Dict[str, Any]]:
        """Get business data by type and date range"""
        pass

    @abstractmethod
    async def store_business_data(self, data: Dict[str, Any]) -> bool:
        """Store business data"""
        pass

    @abstractmethod
    async def get_customers(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get customer data with optional filters"""
        pass