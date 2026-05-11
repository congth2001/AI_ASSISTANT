from typing import List
from PIL import Image
from src.presentation.dto.tracking_dto import (
    FaceTrackingDetail,
    FaceTrackingDetectionDetail,
    FaceTrackingDetectionRequest,
    FaceTrackingDetectionResponse,
    FaceTrackingRequest,
    FaceTrackingResponse,
)
from src.application.use_cases.detect_faces_use_case import DetectFacesUseCase
from src.application.use_cases.track_faces_event_use_case import TrackFacesEventUseCase
from src.domain.repositories.mongo_face_repository import MongoFaceRepository
from src.domain.repositories.mongo_person_repository import MongoPersonRepository
from src.domain.repositories.milvus_vector_repository import MilvusVectorRepository
from src.domain.entities.errors import (
    FaceNotDetectedException,
    InvalidImageException,
)
from src.domain.entities.user import User
import logging

logger = logging.getLogger(__name__)


class TrackingController:
    """Controller for face tracking event operations"""
    
    def __init__(
        self,
        detect_faces_use_case: DetectFacesUseCase,
        track_faces_use_case: TrackFacesEventUseCase,
        face_repository: MongoFaceRepository,
        person_repository: MongoPersonRepository,
        vector_repository: MilvusVectorRepository
    ):
        self.detect_faces_use_case = detect_faces_use_case
        self.track_faces_use_case = track_faces_use_case
        self.face_repository = face_repository
        self.person_repository = person_repository
        self.vector_repository = vector_repository


    async def detect_faces(
        self, 
        request: FaceTrackingDetectionRequest, 
        user: User
    ) -> FaceTrackingDetectionResponse:
        """
        Detect faces tracking in an image
        
        Args:
            request: Face tracking detection request
            user: Current user
            
        Returns:
            Face tracking detection response
        """
        try:
            # Load image
            image = Image.open(request.image_path)
            
            # Detect faces
            detected_faces = await self.detect_faces_use_case.execute(
                image, "", request.image_path
            )
            
            # Convert to response format
            face_details = []
            for face, _ in detected_faces:
                face_detail = FaceTrackingDetectionDetail(
                    id=face.id,
                    image_path=face.image_path,
                    bounding_box=face.bounding_box,
                    confidence=face.confidence,
                    tracked_at=face.created_at
                )
                face_details.append(face_detail)
            
            return FaceTrackingDetectionResponse(
                faces_detected=len(face_details),
                faces=face_details
            )
            
        except (FaceNotDetectedException, InvalidImageException) as e:
            logger.warning(f"Face detection failed: {str(e)}")
            return FaceTrackingDetectionResponse(
                faces_detected=0,
                faces=[]
            )
        except Exception as e:
            logger.error(f"Unexpected error in face detection: {str(e)}")
            raise
        
        
    async def track_faces(
        self, 
        request: FaceTrackingRequest, 
        user: User
    ) -> FaceTrackingResponse:
        """
        Track faces from an image
        
        Args:
            request: Face tracking request
            user: Current user
            
        Returns:
            Face tracking response
        """
        try:
            # Load image
            image = Image.open(request.image_path)
            
            # Register faces
            tracked_faces = await self.track_faces_use_case.execute(
                user.id, image, request.image_path, max_results=10, min_checks=3
            )
            
            # Convert to response format
            face_details = []
            for face in tracked_faces:
                face_detail = FaceTrackingDetail(
                    id=face.id,
                    person_id=face.person_id,
                    event_id=face.event_id,
                    image_path=face.image_path,
                    bounding_box=face.bounding_box,
                    confidence=face.confidence,
                    similarity_score=face.similarity_score,
                    tracked_at=face.tracked_at
                )
                face_details.append(face_detail)
            
            return FaceTrackingResponse(
                success=True,
                faces_tracked=len(face_details),
                faces=face_details
            )
            
        except (FaceNotDetectedException, InvalidImageException) as e:
            logger.warning(f"Face tracking failed: {str(e)}")
            return FaceTrackingResponse(
                success=False,
                faces_tracked=0,
                faces=[]
            )
        except Exception as e:
            logger.error(f"Unexpected error in face tracking: {str(e)}")
            raise
