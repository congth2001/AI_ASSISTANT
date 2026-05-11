from typing import List
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
from src.domain.entities.person import Person
from src.domain.repositories.mongo_person_repository import MongoPersonRepository
from src.domain.repositories.mongo_face_repository import MongoFaceRepository
from src.application.use_cases.register_face_use_case import RegisterFaceUseCase
from src.application.use_cases.delete_face_use_case import DeleteFaceUseCase
from src.domain.entities.errors import (
    PersonNotFoundException,
    StorageException
)
from src.domain.entities.user import User
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class PersonController:
    """Controller for person management operations"""
    
    def __init__(
        self,
        mongo_person_repository: MongoPersonRepository,
        mongo_face_repository: MongoFaceRepository,
        register_face_use_case: RegisterFaceUseCase,
        delete_face_use_case: DeleteFaceUseCase
    ):
        self.mongo_person_repository = mongo_person_repository
        self.mongo_face_repository = mongo_face_repository
        self.register_face_use_case = register_face_use_case
        self.delete_face_use_case = delete_face_use_case

    async def create_person(
        self, 
        request: PersonCreateRequest, 
        user: User
    ) -> PersonResponse:
        """
        Create a new person
        
        Args:
            request: Person creation request
            user: Current user
            
        Returns:
            Person response
        """
        try:
            # Create person entity
            person = Person(
                name=request.name,
                user_id=user.id,
                description=request.description
            )
            
            # Save to database
            saved_person = await self.mongo_person_repository.create(person)
            
            # Convert to response format
            return PersonResponse(
                id=saved_person.id,
                name=saved_person.name,
                user_id=saved_person.user_id,
                description=saved_person.description,
                is_active=saved_person.is_active,
                face_count=saved_person.face_count,
                created_at=saved_person.created_at,
                updated_at=saved_person.updated_at
            )
            
        except Exception as e:
            logger.error(f"Unexpected error creating person: {str(e)}")
            raise

    async def get_person(
        self, 
        person_id: str, 
        user: User
    ) -> PersonResponse:
        """
        Get person by ID
        
        Args:
            person_id: Person ID
            user: Current user
            
        Returns:
            Person response
        """
        try:
            # Get person from database
            person = await self.mongo_person_repository.get_by_id(person_id)
            if not person or person.user_id != user.id:
                raise PersonNotFoundException(person_id)
            
            # Convert to response format
            return PersonResponse(
                id=person.id,
                name=person.name,
                user_id=person.user_id,
                description=person.description,
                is_active=person.is_active,
                face_count=person.face_count,
                created_at=person.created_at,
                updated_at=person.updated_at
            )
            
        except PersonNotFoundException as e:
            logger.warning(f"Person not found: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting person: {str(e)}")
            raise

    async def update_person(
        self, 
        person_id: str, 
        request: PersonUpdateRequest, 
        user: User
    ) -> PersonResponse:
        """
        Update person
        
        Args:
            person_id: Person ID
            request: Person update request
            user: Current user
            
        Returns:
            Person response
        """
        try:
            # Get existing person
            person = await self.mongo_person_repository.get_by_id(person_id)
            if not person or person.user_id != user.id:
                raise PersonNotFoundException(person_id)
            
            # Update fields
            if request.name is not None:
                person.name = request.name
            if request.description is not None:
                person.description = request.description
            if request.is_active is not None:
                person.is_active = request.is_active
            
            # Save updated person
            updated_person = await self.mongo_person_repository.update(person)
            
            # Convert to response format
            return PersonResponse(
                id=updated_person.id,
                name=updated_person.name,
                user_id=updated_person.user_id,
                description=updated_person.description,
                is_active=updated_person.is_active,
                face_count=updated_person.face_count,
                created_at=updated_person.created_at,
                updated_at=updated_person.updated_at
            )
            
        except PersonNotFoundException as e:
            logger.warning(f"Person not found: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating person: {str(e)}")
            raise

    async def list_persons(
        self, 
        user: User
    ) -> PersonListResponse:
        """
        List all persons for a user
        
        Args:
            user: Current user
            
        Returns:
            Person list response
        """
        try:
            # Get all persons for user
            persons = await self.mongo_person_repository.get_by_user_id(user.id)
            
            # Convert to response format
            person_responses = []
            for person in persons:
                person_response = PersonResponse(
                    id=person.id,
                    name=person.name,
                    user_id=person.user_id,
                    description=person.description,
                    is_active=person.is_active,
                    face_count=person.face_count,
                    created_at=person.created_at,
                    updated_at=person.updated_at
                )
                person_responses.append(person_response)
            
            return PersonListResponse(
                total_persons=len(person_responses),
                persons=person_responses
            )
            
        except Exception as e:
            logger.error(f"Unexpected error listing persons: {str(e)}")
            raise

    async def search_persons(
        self, 
        request: PersonSearchRequest, 
        user: User
    ) -> PersonSearchResponse:
        """
        Search persons by name
        
        Args:
            request: Person search request
            user: Current user
            
        Returns:
            Person search response
        """
        try:
            # Get all persons for user
            all_persons = await self.mongo_person_repository.get_by_user_id(user.id)
            
            # Filter by name
            if request.exact_match:
                matching_persons = [
                    p for p in all_persons 
                    if p.name.lower() == request.name.lower()
                ]
            else:
                matching_persons = [
                    p for p in all_persons 
                    if request.name.lower() in p.name.lower()
                ]
            
            # Convert to response format
            person_responses = []
            for person in matching_persons:
                person_response = PersonResponse(
                    id=person.id,
                    name=person.name,
                    user_id=person.user_id,
                    description=person.description,
                    is_active=person.is_active,
                    face_count=person.face_count,
                    created_at=person.created_at,
                    updated_at=person.updated_at
                )
                person_responses.append(person_response)
            
            return PersonSearchResponse(
                matches_found=len(person_responses),
                persons=person_responses
            )
            
        except Exception as e:
            logger.error(f"Unexpected error searching persons: {str(e)}")
            raise

    async def register_person_faces(
        self, 
        request: PersonFaceRegistrationRequest, 
        user: User
    ) -> PersonFaceRegistrationResponse:
        """
        Register faces for a person from multiple images
        
        Args:
            request: Person face registration request
            user: Current user
            
        Returns:
            Person face registration response
        """
        try:
            # Verify person exists and belongs to user
            person = await self.mongo_person_repository.get_by_id(request.person_id)
            if not person or person.user_id != user.id:
                raise PersonNotFoundException(request.person_id)
            
            # Register faces from all images
            all_registered_faces = []
            for image_path in request.image_paths:
                try:
                    # Load image
                    image = Image.open(image_path)
                    
                    # Register faces
                    faces = await self.register_face_use_case.execute(
                        image, request.person_id, image_path
                    )
                    all_registered_faces.extend(faces)
                    
                except Exception as e:
                    # Continue with other images if one fails
                    logger.warning(f"Failed to process image {image_path}: {str(e)}")
                    continue
            
            return PersonFaceRegistrationResponse(
                person_id=person.id,
                person_name=person.name,
                faces_registered=len(all_registered_faces),
                total_faces=person.face_count + len(all_registered_faces)
            )
            
        except PersonNotFoundException as e:
            logger.warning(f"Person not found: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error registering person faces: {str(e)}")
            raise

    async def delete_person(
        self,
        request: PersonDeletionRequest, 
        user: User
    ) -> PersonDeletionResponse:
        """
        Delete a person
        
        Args:
            request: Person deletion request
            user: Current user
            
        Returns:
            Person deletion response
        """
        try:
            # Verify person exists and belongs to user
            person = await self.mongo_person_repository.get_by_id(request.person_id)
            if not person or person.user_id != user.id:
                raise PersonNotFoundException(request.person_id)
            
            faces_deleted = 0
            
            # Delete faces if requested
            if request.delete_faces:
                faces_deleted = await self.delete_face_use_case.delete_faces_for_person(
                    request.person_id, user.id
                )
            
            # Delete person
            success = await self.mongo_person_repository.delete(request.person_id)
            
            if not success:
                raise StorageException(f"Failed to delete person {request.person_id}")
            
            return PersonDeletionResponse(
                success=True,
                person_id=request.person_id,
                faces_deleted=faces_deleted,
                message=f"Person {person.name} deleted successfully"
            )
            
        except PersonNotFoundException as e:
            logger.warning(f"Person not found: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error deleting person: {str(e)}")
            raise
