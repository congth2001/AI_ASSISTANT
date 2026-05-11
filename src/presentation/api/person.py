from fastapi import APIRouter, Depends, HTTPException
from src.presentation.dto.common import BaseResponse
from src.presentation.dto.person_dto import (
    PersonCreateRequest,
    PersonUpdateRequest,
    PersonResponse,
    PersonListResponse,
    PersonFaceRegistrationRequest,
    PersonFaceRegistrationResponse,
    PersonDeletionRequest,
    PersonDeletionResponse,
    PersonSearchRequest,
    PersonSearchResponse
)
from src.presentation.controllers.person_controller import PersonController
from src.presentation.dependencies import verify_user
from src.domain.entities.user import User
from src.domain.entities.errors import (
    PersonNotFoundException,
    StorageException
)
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=['ai_assistant_person'])


def get_person_controller() -> PersonController:
    """Dependency to get person controller"""
    # This would be injected via dependency injection in a real application
    # For now, we'll create a placeholder
    from src.domain.repositories.milvus_vector_repository import MilvusVectorRepository
    from src.domain.repositories.mongo_person_repository import MongoPersonRepository
    from src.domain.repositories.mongo_face_repository import MongoFaceRepository
    from src.application.services.face_detection_service import MTCNNFaceDetectionService
    from src.application.services.face_encoding_service import FaceNetEncodingService
    from src.application.use_cases.detect_faces_use_case import DetectFacesUseCase
    from src.application.use_cases.register_face_use_case import RegisterFaceUseCase
    from src.application.use_cases.delete_face_use_case import DeleteFaceUseCase
    
    # Create dependencies
    face_detection_service = MTCNNFaceDetectionService()
    face_encoding_service = FaceNetEncodingService()
    vector_repository = MilvusVectorRepository()
    mongo_person_repository = MongoPersonRepository()
    mongo_face_repository = MongoFaceRepository()
    
    # Create use cases
    detect_faces_use_case = DetectFacesUseCase(face_detection_service, face_encoding_service)
    register_face_use_case = RegisterFaceUseCase(
        detect_faces_use_case, mongo_face_repository, mongo_person_repository, vector_repository  # Repositories would be injected
    )
    delete_face_use_case = DeleteFaceUseCase(mongo_face_repository, mongo_person_repository, vector_repository)  # Repositories would be injected
    
    return PersonController(
        mongo_person_repository, mongo_face_repository, register_face_use_case, delete_face_use_case  # Repositories would be injected
    )


@router.post(
    "/",
    response_model=BaseResponse[PersonResponse],
    summary="Create a new person"
)
async def create_person(
    request: PersonCreateRequest,
    user: User = Depends(verify_user),
    controller: PersonController = Depends(get_person_controller)
):
    """Create a new person"""
    try:
        result = await controller.create_person(request, user)
        return BaseResponse(
            message="Person created successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"Create person failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{person_id}",
    response_model=BaseResponse[PersonResponse],
    summary="Get person by ID"
)
async def get_person(
    person_id: str,
    user: User = Depends(verify_user),
    controller: PersonController = Depends(get_person_controller)
):
    """Get person by ID"""
    try:
        result = await controller.get_person(person_id, user)
        return BaseResponse(
            message="Person retrieved successfully",
            data=result
        )
    except PersonNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Get person failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/{person_id}",
    response_model=BaseResponse[PersonResponse],
    summary="Update person"
)
async def update_person(
    person_id: str,
    request: PersonUpdateRequest,
    user: User = Depends(verify_user),
    controller: PersonController = Depends(get_person_controller)
):
    """Update person"""
    try:
        result = await controller.update_person(person_id, request, user)
        return BaseResponse(
            message="Person updated successfully",
            data=result
        )
    except PersonNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Update person failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/",
    response_model=BaseResponse[PersonListResponse],
    summary="List all persons"
)
async def list_persons(
    user: User = Depends(verify_user),
    controller: PersonController = Depends(get_person_controller)
):
    """List all persons for the current user"""
    try:
        result = await controller.list_persons(user)
        return BaseResponse(
            message="Persons retrieved successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"List persons failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/search",
    response_model=BaseResponse[PersonSearchResponse],
    summary="Search persons by name"
)
async def search_persons(
    request: PersonSearchRequest,
    user: User = Depends(verify_user),
    controller: PersonController = Depends(get_person_controller)
):
    """Search persons by name"""
    try:
        result = await controller.search_persons(request, user)
        return BaseResponse(
            message="Person search completed successfully",
            data=result
        )
    except Exception as e:
        logger.error(f"Search persons failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/register-faces",
    response_model=BaseResponse[PersonFaceRegistrationResponse],
    summary="Register faces for a person"
)
async def register_person_faces(
    # person_id: str,
    request: PersonFaceRegistrationRequest,
    user: User = Depends(verify_user),
    controller: PersonController = Depends(get_person_controller)
):
    """Register faces for a person from multiple images"""
    try:
        # Update request with person_id from URL
        # request.person_id = person_id
        
        result = await controller.register_person_faces(request, user)
        return BaseResponse(
            message="Person faces registered successfully",
            data=result
        )
    except PersonNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Register person faces failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/{person_id}",
    response_model=BaseResponse[PersonDeletionResponse],
    summary="Delete person"
)
async def delete_person(
    person_id: str,
    delete_faces: bool = True,
    user: User = Depends(verify_user),
    controller: PersonController = Depends(get_person_controller)
):
    """Delete a person"""
    try:
        request = PersonDeletionRequest(
            person_id=person_id,
            delete_faces=delete_faces
        )
        
        result = await controller.delete_person(request, user)
        return BaseResponse(
            message="Person deleted successfully",
            data=result
        )
    except PersonNotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Delete person failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
