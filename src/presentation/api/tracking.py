from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from src.application.use_cases import search_faces_use_case
from src.presentation.dto.common import BaseResponse
from src.presentation.dto.tracking_dto import (
    FaceTrackingDetectionRequest,
    FaceTrackingDetectionResponse,
    FaceTrackingRequest,
    FaceTrackingResponse
)

from src.presentation.controllers.tracking_controller import TrackingController
from src.presentation.dependencies import verify_user
from src.domain.entities.user import User
from src.domain.entities.errors import (
    FaceNotDetectedException,
    FaceNotFoundException,
    PersonNotFoundException,
    InvalidImageException,
    StorageException
)
import logging
import tempfile
import os


logger = logging.getLogger(__name__)
router = APIRouter(tags=['ai_assistant'])


def get_tracking_controller() -> TrackingController:
    """Dependency to get face controller"""
    # This would be injected via dependency injection in a real application
    # For now, we'll create a placeholder
    from src.domain.repositories.milvus_vector_repository import MilvusVectorRepository
    from src.domain.repositories.mongo_face_repository import MongoFaceRepository
    from src.domain.repositories.mongo_person_repository import MongoPersonRepository
    from src.application.services.face_detection_service import MTCNNFaceDetectionService, RetinaFaceDetectionService
    from src.application.services.face_encoding_service import FaceNetEncodingService, DeepFaceEncodingService
    from src.application.services.face_matching_service import CosineSimilarityMatchingService
    from src.application.use_cases.detect_faces_use_case import DetectFacesUseCase
    from src.application.use_cases.search_faces_use_case import SearchFacesUseCase
    from src.application.use_cases.track_faces_event_use_case import TrackFacesEventUseCase
    from src.domain.repositories.mongo_face_tracking_repository import MongoFaceTrackingRepository
    from src.domain.repositories.mongo_event_tracking_repository import MongoEventTrackingRepository
    from src.domain.repositories.mongo_counter_repository import MongoCounterRepository

    
    # Create dependencies
    # face_detection_service = MTCNNFaceDetectionService()
    face_detection_service = RetinaFaceDetectionService()
    # face_encoding_service = FaceNetEncodingService()
    face_encoding_service = DeepFaceEncodingService()
    face_matching_service = CosineSimilarityMatchingService()

    face_tracking_repository = MongoFaceTrackingRepository()
    event_tracking_repository = MongoEventTrackingRepository()    
    vector_repository = MilvusVectorRepository()
    face_repository = MongoFaceRepository()
    person_repository = MongoPersonRepository()
    counter_repository = MongoCounterRepository()
    
    # Create use cases
    detect_faces_use_case = DetectFacesUseCase(face_detection_service, face_encoding_service)
    search_faces_use_case = SearchFacesUseCase(
        detect_faces_use_case, face_encoding_service, face_matching_service,
        face_repository, person_repository, vector_repository
    )
    track_faces_use_case = TrackFacesEventUseCase(
        detect_faces_use_case, search_faces_use_case,
        person_repository, face_repository, face_tracking_repository,
        event_tracking_repository, vector_repository, counter_repository
    )
    
    return TrackingController(
        detect_faces_use_case, track_faces_use_case,
        face_repository, person_repository, vector_repository  # Repositories would be injected
    )


@router.post(
    "/detect",
    response_model=BaseResponse[FaceTrackingDetectionResponse],
    summary="Detect faces tracking in an image"
)
async def detect_faces(
    request: FaceTrackingDetectionRequest,
    user: User = Depends(verify_user),
    controller: TrackingController = Depends(get_tracking_controller)
):
    """Detect faces tracking in an image"""
    try:
        result = await controller.detect_faces(request, user)
        return BaseResponse(
            message="Face detection completed successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"Face detection failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/track-faces",
    response_model=BaseResponse[FaceTrackingResponse],
    summary="Track all faces from an image"
)
async def track_faces(
    request: FaceTrackingRequest,
    user: User = Depends(verify_user),
    controller: TrackingController = Depends(get_tracking_controller)
):
    """Track all faces from an image"""
    try:
        result = await controller.track_faces(request, user)
        return BaseResponse(
            message="Tracking all faces completed successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"Face registration failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


