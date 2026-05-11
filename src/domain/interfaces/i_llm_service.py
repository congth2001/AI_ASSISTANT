from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from uuid import UUID


class ILLMService(ABC):
    """Interface for LLM service"""

    @abstractmethod
    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate a response using LLM"""
        pass

    @abstractmethod
    async def analyze_intent(self, message: str) -> str:
        """Analyze the intent of a user message"""
        pass


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