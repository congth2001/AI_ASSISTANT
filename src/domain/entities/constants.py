from enum import Enum


class FaceRecognitionErrorType(Enum):
    FACE_NOT_DETECTED = "FACE_NOT_DETECTED"
    FACE_NOT_FOUND = "FACE_NOT_FOUND"
    PERSON_NOT_FOUND = "PERSON_NOT_FOUND"
    INVALID_IMAGE = "INVALID_IMAGE"
    VECTOR_NOT_FOUND = "VECTOR_NOT_FOUND"
    MATCHING_FAILED = "MATCHING_FAILED"
    STORAGE_ERROR = "STORAGE_ERROR"
    EVENT_TRACKING_NOT_FOUND = "EVENT_TRACKING_NOT_FOUND"


class FaceRecognitionConstants:
    # FaceNet model constants
    FACENET_VECTOR_DIMENSION = 512
    FACENET_MODEL_VERSION = "facenet_512"
    
    # ArcFace model constants
    ARCFACE_VECTOR_DIMENSION = 512
    ARCFACE_MODEL_VERSION = "arcface_512"
    
    # Face detection constants
    MIN_FACE_CONFIDENCE = 0.5
    MIN_FACE_SIZE = 32  # pixels
    
    # Face matching constants
    DEFAULT_SIMILARITY_THRESHOLD = 0.6
    MAX_SEARCH_RESULTS = 10
    
    # Image processing constants
    SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.bmp']
    MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
    
    # Milvus collection constants
    MILVUS_COLLECTION_NAME = "face_vectors"
    MILVUS_INDEX_TYPE = "IVF_FLAT"
    MILVUS_METRIC_TYPE = "L2"
