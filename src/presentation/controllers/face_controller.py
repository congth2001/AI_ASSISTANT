from typing import List
from PIL import Image
from src.presentation.dto.face_dto import (
    FaceDetectionRequest,
    FaceDetectionResponse,
    FaceDetailResponse,
    FaceRegistrationRequest,
    FaceRegistrationResponse,
    FaceSearchRequest,
    FaceSearchResponse,
    FaceMatchResponse,
    FaceDeletionRequest,
    FaceDeletionResponse,
    PersonFaceListResponse,
    FaceVectorSearchRequest,
    FaceStatisticsResponse
)
from src.application.use_cases.detect_faces_use_case import DetectFacesUseCase
from src.application.use_cases.register_face_use_case import RegisterFaceUseCase
from src.application.use_cases.search_faces_use_case import SearchFacesUseCase
from src.application.use_cases.delete_face_use_case import DeleteFaceUseCase
from src.domain.repositories.mongo_face_repository import MongoFaceRepository
from src.domain.repositories.mongo_person_repository import MongoPersonRepository
from src.domain.repositories.milvus_vector_repository import MilvusVectorRepository
from src.domain.entities.errors import (
    FaceNotDetectedException,
    FaceNotFoundException,
    PersonNotFoundException,
    InvalidImageException,
    StorageException
)
from src.domain.entities.user import User
import logging

logger = logging.getLogger(__name__)


class FaceController:
    """Controller for face recognition operations"""
    
    def __init__(
        self,
        detect_faces_use_case: DetectFacesUseCase,
        register_face_use_case: RegisterFaceUseCase,
        search_faces_use_case: SearchFacesUseCase,
        delete_face_use_case: DeleteFaceUseCase,
        face_repository: MongoFaceRepository,
        person_repository: MongoPersonRepository,
        vector_repository: MilvusVectorRepository
    ):
        self.detect_faces_use_case = detect_faces_use_case
        self.register_face_use_case = register_face_use_case
        self.search_faces_use_case = search_faces_use_case
        self.delete_face_use_case = delete_face_use_case
        self.face_repository = face_repository
        self.person_repository = person_repository
        self.vector_repository = vector_repository

    async def detect_faces(
        self, 
        request: FaceDetectionRequest, 
        user: User
    ) -> FaceDetectionResponse:
        """
        Detect faces in an image
        
        Args:
            request: Face detection request
            user: Current user
            
        Returns:
            Face detection response
        """
        try:
            # Load image
            image = Image.open(request.image_path)
            
            # Detect faces
            detected_faces = await self.detect_faces_use_case.execute(
                image, request.person_id, request.image_path
            )
            
            # Convert to response format
            face_details = []
            for face, _ in detected_faces:
                face_detail = FaceDetailResponse(
                    id=face.id,
                    person_id=face.person_id,
                    image_path=face.image_path,
                    bounding_box=face.bounding_box,
                    confidence=face.confidence,
                    created_at=face.created_at,
                    updated_at=face.updated_at
                )
                face_details.append(face_detail)
            
            return FaceDetectionResponse(
                faces_detected=len(face_details),
                faces=face_details
            )
            
        except (FaceNotDetectedException, InvalidImageException) as e:
            logger.warning(f"Face detection failed: {str(e)}")
            return FaceDetectionResponse(
                faces_detected=0,
                faces=[]
            )
        except Exception as e:
            logger.error(f"Unexpected error in face detection: {str(e)}")
            raise

    async def register_faces(
        self, 
        request: FaceRegistrationRequest, 
        user: User
    ) -> FaceRegistrationResponse:
        """
        Register faces from an image
        
        Args:
            request: Face registration request
            user: Current user
            
        Returns:
            Face registration response
        """
        try:
            # Load image
            image = Image.open(request.image_path)
            
            # Register faces
            registered_faces = await self.register_face_use_case.execute(
                image, request.person_id, request.image_path
            )
            
            # Convert to response format
            face_details = []
            for face in registered_faces:
                face_detail = FaceDetailResponse(
                    id=face.id,
                    person_id=face.person_id,
                    image_path=face.image_path,
                    bounding_box=face.bounding_box,
                    confidence=face.confidence,
                    created_at=face.created_at,
                    updated_at=face.updated_at
                )
                face_details.append(face_detail)
            
            return FaceRegistrationResponse(
                success=True,
                faces_registered=len(face_details),
                faces=face_details
            )
            
        except (FaceNotDetectedException, PersonNotFoundException, InvalidImageException) as e:
            logger.warning(f"Face registration failed: {str(e)}")
            return FaceRegistrationResponse(
                success=False,
                faces_registered=0,
                faces=[]
            )
        except Exception as e:
            logger.error(f"Unexpected error in face registration: {str(e)}")
            raise

    async def search_faces(
        self, 
        request: FaceSearchRequest, 
        user: User
    ) -> FaceSearchResponse:
        """
        Search for similar faces
        
        Args:
            request: Face search request
            user: Current user
            
        Returns:
            Face search response
        """
        try:
            # Load image
            image = Image.open(request.image_path)
            
            # Search for similar faces
            matches = await self.search_faces_use_case.execute(
                image, user.id, request.threshold, request.max_results
            )
            
            # Convert to response format
            match_responses = []
            for match in matches:
                match_response = FaceMatchResponse(
                    person_id=match.person_id,
                    person_name=match.person_name,
                    face_id=match.face_id,
                    similarity_score=match.similarity_score,
                    confidence=match.confidence,
                    distance=match.distance
                )
                match_responses.append(match_response)
            
            return FaceSearchResponse(
                query_processed=True,
                matches_found=len(match_responses),
                matches=match_responses
            )
            
        except (FaceNotDetectedException, InvalidImageException) as e:
            logger.warning(f"Face search failed: {str(e)}")
            return FaceSearchResponse(
                query_processed=False,
                matches_found=0,
                matches=[]
            )
        except Exception as e:
            logger.error(f"Unexpected error in face search: {str(e)}")
            raise

    async def search_faces_by_vector(
        self, 
        request: FaceVectorSearchRequest, 
        user: User
    ) -> FaceSearchResponse:
        """
        Search for similar faces using pre-computed vector
        
        Args:
            request: Face vector search request
            user: Current user
            
        Returns:
            Face search response
        """
        try:
            # Search for similar faces using vector
            matches = await self.search_faces_use_case.search_by_vector(
                request.vector, user.id, request.threshold, request.max_results
            )
            
            # Convert to response format
            match_responses = []
            for match in matches:
                match_response = FaceMatchResponse(
                    person_id=match.person_id,
                    person_name=match.person_name,
                    face_id=match.face_id,
                    similarity_score=match.similarity_score,
                    confidence=match.confidence,
                    distance=match.distance
                )
                match_responses.append(match_response)
            
            return FaceSearchResponse(
                query_processed=True,
                matches_found=len(match_responses),
                matches=match_responses
            )
            
        except Exception as e:
            logger.error(f"Unexpected error in vector search: {str(e)}")
            raise

    async def delete_faces(
        self, 
        request: FaceDeletionRequest, 
        user: User
    ) -> FaceDeletionResponse:
        """
        Delete faces
        
        Args:
            request: Face deletion request
            user: Current user
            
        Returns:
            Face deletion response
        """
        try:
            # Delete faces
            deleted_count = await self.delete_face_use_case.delete_multiple_faces(
                request.face_ids, user.id
            )
            
            return FaceDeletionResponse(
                success=True,
                faces_deleted=deleted_count,
                deleted_face_ids=request.face_ids[:deleted_count]
            )
            
        except Exception as e:
            logger.error(f"Unexpected error in face deletion: {str(e)}")
            raise

    async def get_person_faces(
        self, 
        person_id: str, 
        user: User
    ) -> PersonFaceListResponse:
        """
        Get all faces for a person
        
        Args:
            person_id: Person ID
            user: Current user
            
        Returns:
            Person face list response
        """
        try:
            # Get person details
            person = await self.person_repository.get_by_id(person_id)
            if not person or person.user_id != user.id:
                raise PersonNotFoundException(person_id)
            
            # Get faces for the person
            faces = await self.search_faces_use_case.get_face_matches_for_person(
                person_id, user.id
            )
            
            # Convert to response format
            face_details = []
            for face in faces:
                face_detail = FaceDetailResponse(
                    id=face.id,
                    person_id=face.person_id,
                    image_path=face.image_path,
                    bounding_box=face.bounding_box,
                    confidence=face.confidence,
                    created_at=face.created_at,
                    updated_at=face.updated_at
                )
                face_details.append(face_detail)
            
            return PersonFaceListResponse(
                person_id=person.id,
                person_name=person.name,
                total_faces=len(face_details),
                faces=face_details
            )
            
        except PersonNotFoundException as e:
            logger.warning(f"Person not found: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting person faces: {str(e)}")
            raise

    async def get_statistics(self, user: User) -> FaceStatisticsResponse:
        """
        Get face recognition statistics
        
        Args:
            user: Current user
            
        Returns:
            Face statistics response
        """
        try:
            # Get user's faces
            user_faces = await self.face_repository.get_by_user_id(user.id)
            
            # Get user's persons
            user_persons = await self.person_repository.get_by_user_id(user.id)
            
            # Get collection stats
            collection_stats = await self.vector_repository.get_collection_stats(
                "face_vectors"  # Default collection name
            )
            
            return FaceStatisticsResponse(
                total_faces=len(user_faces),
                total_persons=len(user_persons),
                total_vectors=collection_stats.get("num_entities", 0),
                collection_stats=collection_stats
            )
            
        except Exception as e:
            logger.error(f"Unexpected error getting statistics: {str(e)}")
            raise
