from typing import Optional
from .constants import FaceRecognitionErrorType


class FaceRecognitionException(Exception):
    """Base exception for face recognition operations"""
    
    def __init__(self, message: str, error_type: FaceRecognitionErrorType, details: Optional[str] = None):
        self.message = message
        self.error_type = error_type
        self.details = details
        super().__init__(self.message)


class FaceNotDetectedException(FaceRecognitionException):
    """Raised when no face is detected in the image"""
    
    def __init__(self, message: str = "No face detected in the image", details: Optional[str] = None):
        super().__init__(message, FaceRecognitionErrorType.FACE_NOT_DETECTED, details)


class FaceNotFoundException(FaceRecognitionException):
    """Raised when a specific face is not found"""
    
    def __init__(self, face_id: str, message: str = None, details: Optional[str] = None):
        if message is None:
            message = f"Face with ID {face_id} not found"
        super().__init__(message, FaceRecognitionErrorType.FACE_NOT_FOUND, details)


class PersonNotFoundException(FaceRecognitionException):
    """Raised when a person is not found"""
    
    def __init__(self, person_id: str, message: str = None, details: Optional[str] = None):
        if message is None:
            message = f"Person with ID {person_id} not found"
        super().__init__(message, FaceRecognitionErrorType.PERSON_NOT_FOUND, details)


class InvalidImageException(FaceRecognitionException):
    """Raised when the provided image is invalid"""
    
    def __init__(self, message: str = "Invalid image format or corrupted image", details: Optional[str] = None):
        super().__init__(message, FaceRecognitionErrorType.INVALID_IMAGE, details)


class VectorNotFoundException(FaceRecognitionException):
    """Raised when face vector is not found in the database"""
    
    def __init__(self, face_id: str, message: str = None, details: Optional[str] = None):
        if message is None:
            message = f"Vector for face {face_id} not found"
        super().__init__(message, FaceRecognitionErrorType.VECTOR_NOT_FOUND, details)


class MatchingFailedException(FaceRecognitionException):
    """Raised when face matching operation fails"""
    
    def __init__(self, message: str = "Face matching operation failed", details: Optional[str] = None):
        super().__init__(message, FaceRecognitionErrorType.MATCHING_FAILED, details)


class StorageException(FaceRecognitionException):
    """Raised when storage operations fail"""
    
    def __init__(self, message: str = "Storage operation failed", details: Optional[str] = None):
        super().__init__(message, FaceRecognitionErrorType.STORAGE_ERROR, details)

class EventTrackingNotFoundException(FaceRecognitionException):
    """Raised when a specific event tracking is not found"""
    
    def __init__(self, event_tracking_id: str, message: str = None, details: Optional[str] = None):
        if message is None:
            message = f"Event tracking with ID {event_tracking_id} not found"
        super().__init__(message, FaceRecognitionErrorType.EVENT_TRACKING_NOT_FOUND, details)