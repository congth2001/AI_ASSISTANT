"""Common categories; business-specific codes/messages belong to module catalogs."""
from .base import ApplicationError, ErrorType


class NotFoundError(ApplicationError, ValueError):
    code = "not_found"
    error_type = ErrorType.NOT_FOUND
    message_template = "Resource not found"


class PermissionDeniedError(ApplicationError, PermissionError):
    code = "not_permission"
    error_type = ErrorType.NOT_PERMISSION
    message_template = "Insufficient permissions"


class UnauthorizedError(ApplicationError, ValueError):
    code = "unauthorized"
    error_type = ErrorType.UNAUTHORIZED
    message_template = "Authentication required"


class ValidationError(ApplicationError, ValueError):
    code = "validation"
    error_type = ErrorType.VALIDATION
    message_template = "Invalid input"


class RequestValidationError(ValidationError):
    error_type = ErrorType.INVALID_REQUEST

    def __init__(self, *, error: ValueError):
        super().__init__(str(error))
        if isinstance(error, ApplicationError):
            self.code = error.code


class ConflictError(ValidationError):
    code = "conflict"
    error_type = ErrorType.CONFLICT
    message_template = "Resource already exists"


class InternalError(ApplicationError, RuntimeError):
    code = "internal"
    message_template = "Unable to process the request"


class OperationTimeoutError(ApplicationError, TimeoutError):
    code = "timeout"
    error_type = ErrorType.TIMEOUT
    message_template = "Operation timed out"


class ExternalServiceError(InternalError):
    code = "external_service"
    error_type = ErrorType.EXTERNAL_SERVICE
    message_template = "External service unavailable"


class RateLimitedError(ApplicationError):
    """Too many requests; ``retry_after`` (seconds) is exposed as the Retry-After header."""

    code = "rate_limited"
    error_type = ErrorType.RATE_LIMITED
    message_template = "Too many requests. Please retry later"

    def __init__(self, message: str | None = None, *, retry_after: int = 1, **parameters):
        super().__init__(message, **parameters)
        self.retry_after = max(1, int(retry_after))
