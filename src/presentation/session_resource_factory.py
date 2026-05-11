from typing import Optional
from src.infrastructure.repositories.milvus_vector_repository import MilvusVectorRepository
from src.domain.repositories.face_repository import FaceRepository
from src.domain.repositories.person_repository import PersonRepository


class MissingRequiredParams(ValueError):
    pass


class SessionResourceFactory:
    """Factory for creating face recognition resources"""
    
    def __init__(self, user_id: Optional[str] = None):
        self._user_id = user_id

        self._face_repository = None
        self._person_repository = None
        self._vector_repository = None

    async def get_face_repository(self) -> FaceRepository:
        """Get face repository instance"""
        if not self._face_repository:
            from src.infrastructure.repositories.mongo_face_repository import MongoFaceRepository
            self._face_repository = MongoFaceRepository()
        return self._face_repository

    async def get_person_repository(self) -> PersonRepository:
        """Get person repository instance"""
        if not self._person_repository:
            from src.infrastructure.repositories.mongo_person_repository import MongoPersonRepository
            self._person_repository = MongoPersonRepository()
        return self._person_repository

    async def get_vector_repository(self) -> MilvusVectorRepository:
        """Get vector repository instance"""
        if not self._vector_repository:
            self._vector_repository = MilvusVectorRepository()
        return self._vector_repository
