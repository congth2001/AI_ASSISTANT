"""
Face Recognition Service Logger Package

This package provides comprehensive logging functionality for the Face Recognition Service.
It includes core logging, decorators, middleware, and specialized logging for different operations.

Modules:
    - core: Main logger configuration and functionality
    - decorators: Logging decorators for functions and methods
    - middleware: FastAPI middleware for request/response logging
"""

# Import main logger functionality
from .core import (
    ServiceLogger,
    logger,
    get_logger,
    debug,
    info,
    warning,
    error,
    critical,
    log_performance,
    log_api_request,
    log_face_operation,
    log_database_operation,
    log_exception
)

# Import decorators
from .decorators import (
    log_execution_time,
    log_database_operation_time,
    log_api_endpoint,
    log_operation_context,
    log_database_context
)

# Import middleware
from .middleware import (
    LoggingMiddleware,
    DatabaseLoggingMiddleware,
    FaceOperationLoggingMiddleware,
    api_logging_middleware,
    database_logging_middleware,
    face_operation_logging_middleware
)

# Version info
__version__ = "1.0.0"
__author__ = "Face Recognition Service Team"

# Export all public functions and classes
__all__ = [
    # Core logging
    "ServiceLogger",
    "logger",
    "get_logger",
    "debug",
    "info",
    "warning",
    "error",
    "critical",
    "log_performance",
    "log_api_request",
    "log_face_operation",
    "log_database_operation",
    "log_exception",
    
    # Decorators
    "log_execution_time",
    "log_database_operation_time",
    "log_api_endpoint",
    "log_operation_context",
    "log_database_context",
    
    # Middleware
    "LoggingMiddleware",
    "DatabaseLoggingMiddleware",
    "FaceOperationLoggingMiddleware",
    "api_logging_middleware",
    "database_logging_middleware",
    "face_operation_logging_middleware",
]
