from abc import ABC, abstractmethod
from typing import List, Tuple, Optional
from src.domain.entities.face_vector import FaceVector
from src.domain.entities.face_match import FaceMatch
from src.domain.entities.errors import VectorNotFoundException, StorageException


class VectorRepository(ABC):
    """Abstract interface for vector repository (Milvus)"""
    
    @abstractmethod
    async def create_collection(self, collection_name: str, dimension: int) -> bool:
        """Create a new vector collection"""
        pass
    
    @abstractmethod
    async def drop_collection(self, collection_name: str) -> bool:
        """Drop a vector collection"""
        pass
    
    @abstractmethod
    async def insert_vectors(self, vectors: List[FaceVector]) -> bool:
        """Insert face vectors into the collection"""
        pass
    
    @abstractmethod
    async def insert_vector(self, vector: FaceVector) -> bool:
        """Insert a single face vector"""
        pass
    
    @abstractmethod
    async def get_vector(self, face_id: str) -> Optional[FaceVector]:
        """Get vector by face ID"""
        pass
    
    @abstractmethod
    async def search_similar(
        self, 
        query_vector: List[float], 
        top_k: int = 10,
        threshold: float = 0.6
    ) -> List[Tuple[str, float]]:
        """
        Search for similar vectors
        
        Args:
            query_vector: Query vector
            top_k: Number of top results
            threshold: Similarity threshold
            
        Returns:
            List of (face_id, similarity_score) tuples
        """
        pass
    
    @abstractmethod
    async def delete_vector(self, face_id: str) -> bool:
        """Delete vector by face ID"""
        pass
    
    @abstractmethod
    async def delete_vectors(self, face_ids: List[str]) -> bool:
        """Delete multiple vectors by face IDs"""
        pass
    
    @abstractmethod
    async def get_collection_stats(self, collection_name: str) -> dict:
        """Get collection statistics"""
        pass
    
    @abstractmethod
    async def create_index(self, collection_name: str, index_type: str = "IVF_FLAT") -> bool:
        """Create index for the collection"""
        pass
