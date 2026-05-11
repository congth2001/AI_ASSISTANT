from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from src.presentation.dto.common import BaseResponse
from src.presentation.dto.face_dto import (
    FaceDetectionRequest,
    FaceDetectionResponse,
    FaceRegistrationRequest,
    FaceRegistrationResponse,
    FaceSearchRequest,
    FaceSearchResponse,
    FaceDeletionRequest,
    FaceDeletionResponse,
    PersonFaceListResponse,
    FaceVectorSearchRequest,
    FaceStatisticsResponse
)
from src.presentation.controllers.face_controller import FaceController
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


def get_face_controller() -> FaceController:
    """Dependency to get face controller"""
    # This would be injected via dependency injection in a real application
    # For now, we'll create a placeholder
    from src.presentation.session_resource_factory import SessionResourceFactory
    from src.domain.repositories.milvus_vector_repository import MilvusVectorRepository
    from src.domain.repositories.mongo_face_repository import MongoFaceRepository
    from src.domain.repositories.mongo_person_repository import MongoPersonRepository
    from src.application.services.face_detection_service import MTCNNFaceDetectionService
    from src.application.services.face_encoding_service import FaceNetEncodingService
    from src.application.services.face_matching_service import CosineSimilarityMatchingService
    from src.application.use_cases.detect_faces_use_case import DetectFacesUseCase
    from src.application.use_cases.register_face_use_case import RegisterFaceUseCase
    from src.application.use_cases.search_faces_use_case import SearchFacesUseCase
    from src.application.use_cases.delete_face_use_case import DeleteFaceUseCase
    
    # Create dependencies
    face_detection_service = MTCNNFaceDetectionService()
    face_encoding_service = FaceNetEncodingService()
    face_matching_service = CosineSimilarityMatchingService()
    vector_repository = MilvusVectorRepository()
    face_repository = MongoFaceRepository()
    person_repository = MongoPersonRepository()
    
    # Create use cases
    detect_faces_use_case = DetectFacesUseCase(face_detection_service, face_encoding_service)
    register_face_use_case = RegisterFaceUseCase(
        detect_faces_use_case, face_repository, person_repository, vector_repository  # Repositories would be injected
    )
    search_faces_use_case = SearchFacesUseCase(
        detect_faces_use_case, face_encoding_service, face_matching_service,
        face_repository, person_repository, vector_repository  # Repositories would be injected
    )
    delete_face_use_case = DeleteFaceUseCase(face_repository, person_repository, vector_repository)  # Repositories would be injected
    
    return FaceController(
        detect_faces_use_case, register_face_use_case, search_faces_use_case,
        delete_face_use_case, face_repository, person_repository, vector_repository  # Repositories would be injected
    )


@router.post(
    "/detect",
    response_model=BaseResponse[FaceDetectionResponse],
    summary="Detect faces in an image"
)
async def detect_faces(
    request: FaceDetectionRequest,
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Detect faces in an image"""
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
    "/register",
    response_model=BaseResponse[FaceRegistrationResponse],
    summary="Register faces from an image"
)
async def register_faces(
    request: FaceRegistrationRequest,
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Register faces from an image"""
    try:
        result = await controller.register_faces(request, user)
        return BaseResponse(
            message="Face registration completed successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"Face registration failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/search",
    response_model=BaseResponse[FaceSearchResponse],
    summary="Search for similar faces"
)
async def search_faces(
    request: FaceSearchRequest,
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Search for similar faces"""
    try:
        result = await controller.search_faces(request, user)
        return BaseResponse(
            message="Face search completed successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"Face search failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/search/vector",
    response_model=BaseResponse[FaceSearchResponse],
    summary="Search for similar faces using vector"
)
async def search_faces_by_vector(
    request: FaceVectorSearchRequest,
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Search for similar faces using pre-computed vector"""
    try:
        result = await controller.search_faces_by_vector(request, user)
        return BaseResponse(
            message="Vector search completed successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"Vector search failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/upload/detect",
    response_model=BaseResponse[FaceDetectionResponse],
    summary="Upload image and detect faces"
)
async def upload_and_detect_faces(
    file: UploadFile = File(...),
    person_id: str = None,
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Upload image file and detect faces"""
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            # Create request
            request = FaceDetectionRequest(
                image_path=tmp_file_path,
                person_id=person_id or "unknown"
            )
            
            # Detect faces
            result = await controller.detect_faces(request, user)
            
            return BaseResponse(
                message="Face detection completed successfully",
                data=result
            )
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
                
    except Exception as e:
        logger.error(f"Upload and detect faces failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/upload/register",
    response_model=BaseResponse[list[FaceRegistrationResponse]],
    summary="Upload image and register faces"
)
async def upload_and_register_faces(
    files: list[UploadFile] = File(...),
    person_id: str = Form(...),
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Upload image files and register faces"""
    try:
        if not person_id:
            raise HTTPException(status_code=400, detail="person_id is required")
        
        if not files:
            raise HTTPException(status_code=400, detail="At least one file is required")
        
        tmp_file_paths = []
        results = []
        try:
            # Save uploaded files temporarily
            for file in files:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                    content = await file.read()
                    tmp_file.write(content)
                    tmp_file_paths.append(tmp_file.name)
            
            for tmp_file_path in tmp_file_paths:
                # Create request with list of image paths
                request = FaceRegistrationRequest(
                    image_path=tmp_file_path,
                    person_id=person_id
                )
                
                # Register faces
                result = await controller.register_faces(request, user)
                results.append(result)
            
            return BaseResponse(
                message="Face registration completed successfully",
                data=results
            )
        finally:
            # Clean up temporary files
            for tmp_file_path in tmp_file_paths:
                if os.path.exists(tmp_file_path):
                    os.unlink(tmp_file_path)
                
    except Exception as e:
        logger.error(f"Upload and register faces failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/upload/search",
    response_model=BaseResponse[FaceSearchResponse],
    summary="Upload image and search for similar faces"
)
async def upload_and_search_faces(
    file: UploadFile = File(...),
    threshold: float = 0.6,
    max_results: int = 10,
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Upload image file and search for similar faces"""
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            # Create request
            request = FaceSearchRequest(
                image_path=tmp_file_path,
                threshold=threshold,
                max_results=max_results
            )
            
            # Search faces
            result = await controller.search_faces(request, user)
            
            return BaseResponse(
                message="Face search completed successfully",
                data=result
            )
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
                
    except Exception as e:
        logger.error(f"Upload and search faces failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/delete",
    response_model=BaseResponse[FaceDeletionResponse],
    summary="Delete faces"
)
async def delete_faces(
    request: FaceDeletionRequest,
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Delete faces"""
    try:
        result = await controller.delete_faces(request, user)
        return BaseResponse(
            message="Face deletion completed successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"Face deletion failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/person/{person_id}/faces",
    response_model=BaseResponse[PersonFaceListResponse],
    summary="Get all faces for a person"
)
async def get_person_faces(
    person_id: str,
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Get all faces for a person"""
    try:
        result = await controller.get_person_faces(person_id, user)
        return BaseResponse(
            message="Person faces retrieved successfully",
            data=result
        )
    except PersonNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Get person faces failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/statistics",
    response_model=BaseResponse[FaceStatisticsResponse],
    summary="Get face recognition statistics"
)
async def get_statistics(
    user: User = Depends(verify_user),
    controller: FaceController = Depends(get_face_controller)
):
    """Get face recognition statistics"""
    try:
        result = await controller.get_statistics(user)
        return BaseResponse(
            message="Statistics retrieved successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"Get statistics failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
