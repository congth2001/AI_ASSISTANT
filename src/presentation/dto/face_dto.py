from typing import List, Optional
from pydantic import BaseModel, Field, validator
from datetime import datetime


class FaceDetectionRequest(BaseModel):
    """Request for face detection"""
    image_path: str = Field(..., description="Path to the image file")
    person_id: str = Field(..., description="ID of the person")


class FaceDetectionResponse(BaseModel):
    """Response for face detection"""
    faces_detected: int = Field(..., description="Number of faces detected")
    faces: List['FaceDetailResponse'] = Field(..., description="List of detected faces")


class FaceDetailResponse(BaseModel):
    """Detailed face information"""
    id: str = Field(..., description="Face ID")
    person_id: str = Field(..., description="Person ID")
    image_path: str = Field(..., description="Path to the image file")
    bounding_box: List[int] = Field(..., description="Face bounding box [x, y, width, height]")
    confidence: float = Field(..., description="Detection confidence score")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class FaceRegistrationRequest(BaseModel):
    """Request for face registration"""
    image_path: str = Field(..., description="Path to the image file")
    person_id: str = Field(..., description="ID of the person")
    
    @validator('image_path')
    def validate_image_path(cls, v):
        if not v or not v.strip():
            raise ValueError("Image path cannot be empty")
        return v.strip()


class FaceRegistrationResponse(BaseModel):
    """Response for face registration"""
    success: bool = Field(..., description="Whether registration was successful")
    faces_registered: int = Field(..., description="Number of faces registered")
    faces: List[FaceDetailResponse] = Field(..., description="List of registered faces")


class FaceSearchRequest(BaseModel):
    """Request for face search"""
    image_path: str = Field(..., description="Path to the query image file")
    threshold: float = Field(0.6, ge=0.0, le=1.0, description="Similarity threshold")
    max_results: int = Field(10, ge=1, le=100, description="Maximum number of results")
    
    @validator('image_path')
    def validate_image_path(cls, v):
        if not v or not v.strip():
            raise ValueError("Image path cannot be empty")
        return v.strip()


class FaceMatchResponse(BaseModel):
    """Face match result"""
    person_id: str = Field(..., description="Person ID")
    person_name: str = Field(..., description="Person name")
    face_id: str = Field(..., description="Face ID")
    similarity_score: float = Field(..., description="Similarity score")
    confidence: float = Field(..., description="Confidence score")
    distance: float = Field(..., description="Distance score")


class FaceSearchResponse(BaseModel):
    """Response for face search"""
    query_processed: bool = Field(..., description="Whether query was processed successfully")
    matches_found: int = Field(..., description="Number of matches found")
    matches: List[FaceMatchResponse] = Field(..., description="List of face matches")


class FaceDeletionRequest(BaseModel):
    """Request for face deletion"""
    face_ids: List[str] = Field(..., description="List of face IDs to delete")
    
    @validator('face_ids')
    def validate_face_ids(cls, v):
        if not v:
            raise ValueError("Face IDs list cannot be empty")
        return v


class FaceDeletionResponse(BaseModel):
    """Response for face deletion"""
    success: bool = Field(..., description="Whether deletion was successful")
    faces_deleted: int = Field(..., description="Number of faces deleted")
    deleted_face_ids: List[str] = Field(..., description="List of deleted face IDs")


class PersonFaceListResponse(BaseModel):
    """Response for person's face list"""
    person_id: str = Field(..., description="Person ID")
    person_name: str = Field(..., description="Person name")
    total_faces: int = Field(..., description="Total number of faces")
    faces: List[FaceDetailResponse] = Field(..., description="List of faces")


class FaceVectorSearchRequest(BaseModel):
    """Request for face search using pre-computed vector"""
    vector: List[float] = Field(..., description="Face vector (512 dimensions)")
    threshold: float = Field(0.6, ge=0.0, le=1.0, description="Similarity threshold")
    max_results: int = Field(10, ge=1, le=100, description="Maximum number of results")
    
    @validator('vector')
    def validate_vector(cls, v):
        if len(v) != 512:
            raise ValueError("Vector must have exactly 512 dimensions")
        return v


class FaceStatisticsResponse(BaseModel):
    """Response for face recognition statistics"""
    total_faces: int = Field(..., description="Total number of faces in database")
    total_persons: int = Field(..., description="Total number of persons")
    total_vectors: int = Field(..., description="Total number of vectors in Milvus")
    collection_stats: dict = Field(..., description="Milvus collection statistics")


# Update forward references
FaceDetectionResponse.model_rebuild()
FaceRegistrationResponse.model_rebuild()
FaceSearchResponse.model_rebuild()
FaceDeletionResponse.model_rebuild()
PersonFaceListResponse.model_rebuild()
