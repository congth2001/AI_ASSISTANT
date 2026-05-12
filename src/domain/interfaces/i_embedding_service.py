from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

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
