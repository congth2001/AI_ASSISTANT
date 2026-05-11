from typing import List, Optional
from pydantic import BaseModel, Field, validator
from datetime import datetime


class FaceTrackingDetectionDetail(BaseModel):
    """Detailed face information"""
    id: str = Field(..., description="Face ID")
    image_path: str = Field(..., description="Path to the image file")
    bounding_box: List[int] = Field(..., description="Face bounding box [x, y, width, height]")
    confidence: float = Field(..., description="Detection confidence score")
    tracked_at: datetime = Field(..., description="Timestamp when the face was tracked")


class FaceTrackingDetectionRequest(BaseModel):
    """Request for face tracking detection"""
    image_path: str = Field(..., description="Path to the image file")


class FaceTrackingDetectionResponse(BaseModel):
    """Response for face detection"""
    faces_detected: int = Field(..., description="Number of faces detected")
    faces: List[FaceTrackingDetectionDetail] = Field(..., description="List of detected faces")


class FaceTrackingDetail(BaseModel):
    """Detailed face information"""
    id: str = Field(..., description="Face ID")
    person_id: Optional[str] = Field(None, description="Associated person ID, both for known and unknown persons")
    event_id: Optional[str] = Field(None, description="Event ID associated with the tracking")
    image_path: str = Field(..., description="Path to the image file")
    bounding_box: List[int] = Field(..., description="Face bounding box [x, y, width, height]")
    confidence: float = Field(..., description="Detection confidence score")
    similarity_score: Optional[float] = Field(None, description="Similarity score to persons, if applicable")
    tracked_at: datetime = Field(..., description="Timestamp when the face was tracked")


class FaceTrackingRequest(BaseModel):
    """Request for face tracking"""
    image_path: str = Field(..., description="Path to the image file")
    
    @validator('image_path')
    def validate_image_path(cls, v):
        if not v or not v.strip():
            raise ValueError("Image path cannot be empty")
        return v.strip()


class FaceTrackingResponse(BaseModel):
    """Response for face tracking"""
    success: bool = Field(..., description="Whether tracking was successful")
    faces_tracked: int = Field(..., description="Number of faces tracked")
    faces: List[FaceTrackingDetail] = Field(..., description="List of tracked faces")


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


# Update forward references
FaceTrackingDetectionResponse.model_rebuild()
FaceSearchResponse.model_rebuild()
