"""Framework-independent errors shared by config and business modules."""
from .base import ApplicationError, ErrorType
from .configuration import ConfigurationError
from .types import (
    ConflictError, ExternalServiceError, InternalError, NotFoundError,
    OperationTimeoutError, PermissionDeniedError, RateLimitedError, RequestValidationError,
    UnauthorizedError, ValidationError,
)

__all__ = [
    "ApplicationError", "ErrorType", "ConfigurationError", "ConflictError",
    "ExternalServiceError", "InternalError", "NotFoundError", "OperationTimeoutError",
    "PermissionDeniedError", "RateLimitedError", "RequestValidationError", "UnauthorizedError", "ValidationError",
]
