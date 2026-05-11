from typing import List, Optional
from pydantic import BaseModel, Field, validator
from datetime import datetime


class   PersonCreateRequest(BaseModel):
    """Request for creating a new person"""
    name: str = Field(..., min_length=1, max_length=100, description="Person's name")
    description: Optional[str] = Field(None, max_length=500, description="Person's description")
    
    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip()


class PersonUpdateRequest(BaseModel):
    """Request for updating a person"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Person's name")
    description: Optional[str] = Field(None, max_length=500, description="Person's description")
    is_active: Optional[bool] = Field(None, description="Whether person is active")


class PersonResponse(BaseModel):
    """Person information response"""
    id: str = Field(..., description="Person ID")
    name: str = Field(..., description="Person's name")
    user_id: str = Field(..., description="User ID who owns this person")
    description: Optional[str] = Field(None, description="Person's description")
    is_active: bool = Field(..., description="Whether person is active")
    face_count: int = Field(..., description="Number of registered faces")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class PersonListResponse(BaseModel):
    """Response for person list"""
    total_persons: int = Field(..., description="Total number of persons")
    persons: List[PersonResponse] = Field(..., description="List of persons")


class PersonFaceRegistrationRequest(BaseModel):
    """Request for registering faces for a person"""
    person_id: str = Field(..., description="Person ID")
    image_paths: List[str] = Field(..., min_items=1, description="List of image paths")
    
    @validator('image_paths')
    def validate_image_paths(cls, v):
        if not v:
            raise ValueError("Image paths list cannot be empty")
        for path in v:
            if not path or not path.strip():
                raise ValueError("Image path cannot be empty")
        return [path.strip() for path in v]


class PersonFaceRegistrationResponse(BaseModel):
    """Response for person face registration"""
    person_id: str = Field(..., description="Person ID")
    person_name: str = Field(..., description="Person's name")
    faces_registered: int = Field(..., description="Number of faces registered")
    total_faces: int = Field(..., description="Total number of faces for this person")


class PersonDeletionRequest(BaseModel):
    """Request for deleting a person"""
    person_id: str = Field(..., description="Person ID to delete")
    delete_faces: bool = Field(True, description="Whether to delete all associated faces")


class PersonDeletionResponse(BaseModel):
    """Response for person deletion"""
    success: bool = Field(..., description="Whether deletion was successful")
    person_id: str = Field(..., description="Deleted person ID")
    faces_deleted: int = Field(..., description="Number of faces deleted")
    message: str = Field(..., description="Deletion message")


class PersonSearchRequest(BaseModel):
    """Request for searching persons by name"""
    name: str = Field(..., min_length=1, description="Name to search for")
    exact_match: bool = Field(False, description="Whether to perform exact match")
    
    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Search name cannot be empty")
        return v.strip()


class PersonSearchResponse(BaseModel):
    """Response for person search"""
    matches_found: int = Field(..., description="Number of matches found")
    persons: List[PersonResponse] = Field(..., description="List of matching persons")
