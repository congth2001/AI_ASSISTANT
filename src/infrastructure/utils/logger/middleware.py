"""
FastAPI Logging Middleware for  AI Assistant Service
"""
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from .core import get_logger, log_api_request


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all HTTP requests and responses"""
    
    def __init__(self, app, logger_name: str = "api_middleware"):
        super().__init__(app)
        self.logger = get_logger(logger_name)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Start timing
        start_time = time.time()
        
        # Extract request info
        method = request.method
        url = str(request.url)
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Log request start
        self.logger.info(
            f"Request started: {method} {path}",
            request_id=request_id,
            method=method,
            path=path,
            client_ip=client_ip,
            user_agent=user_agent
        )
        
        # Process request
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            
            # Log successful response
            self.logger.info(
                f"Request completed: {method} {path} -> {response.status_code}",
                request_id=request_id,
                method=method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration * 1000,
                client_ip=client_ip
            )
            
            # Log API request for performance tracking
            log_api_request(
                method=method,
                path=path,
                status_code=response.status_code,
                duration=duration,
                request_id=request_id,
                client_ip=client_ip
            )
            
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            
            # Log error
            self.logger.error(
                f"Request failed: {method} {path} -> {str(e)}",
                request_id=request_id,
                method=method,
                path=path,
                error=str(e),
                duration_ms=duration * 1000,
                client_ip=client_ip,
                exc_info=True
            )
            
            # Log API request for performance tracking
            log_api_request(
                method=method,
                path=path,
                status_code=500,
                duration=duration,
                request_id=request_id,
                client_ip=client_ip,
                error=str(e)
            )
            
            raise


class DatabaseLoggingMiddleware:
    """Middleware to log database operations"""
    
    def __init__(self, logger_name: str = "database_middleware"):
        self.logger = get_logger(logger_name)
    
    def log_operation(self, operation: str, collection: str, duration: float = None, **kwargs):
        """Log database operation"""
        self.logger.debug(
            f"DB {operation} on {collection}",
            operation=operation,
            collection=collection,
            duration_ms=duration * 1000 if duration else None,
            **kwargs
        )


class FaceOperationLoggingMiddleware:
    """Middleware to log face recognition operations"""
    
    def __init__(self, logger_name: str = "face_operation_middleware"):
        self.logger = get_logger(logger_name)
    
    def log_face_detection(self, image_path: str, faces_count: int, duration: float = None, **kwargs):
        """Log face detection operation"""
        self.logger.info(
            f"Face detection completed: {faces_count} faces found",
            operation="face_detection",
            image_path=image_path,
            faces_count=faces_count,
            duration_ms=duration * 1000 if duration else None,
            **kwargs
        )
    
    def log_face_encoding(self, face_id: str, duration: float = None, **kwargs):
        """Log face encoding operation"""
        self.logger.info(
            f"Face encoding completed: {face_id}",
            operation="face_encoding",
            face_id=face_id,
            duration_ms=duration * 1000 if duration else None,
            **kwargs
        )
    
    def log_face_matching(self, query_face_id: str, matches_count: int, duration: float = None, **kwargs):
        """Log face matching operation"""
        self.logger.info(
            f"Face matching completed: {matches_count} matches found",
            operation="face_matching",
            query_face_id=query_face_id,
            matches_count=matches_count,
            duration_ms=duration * 1000 if duration else None,
            **kwargs
        )
    
    def log_face_registration(self, face_id: str, person_id: str, duration: float = None, **kwargs):
        """Log face registration operation"""
        self.logger.info(
            f"Face registration completed: {face_id} -> {person_id}",
            operation="face_registration",
            face_id=face_id,
            person_id=person_id,
            duration_ms=duration * 1000 if duration else None,
            **kwargs
        )


# Global middleware instances
api_logging_middleware = LoggingMiddleware
database_logging_middleware = DatabaseLoggingMiddleware()
face_operation_logging_middleware = FaceOperationLoggingMiddleware()
