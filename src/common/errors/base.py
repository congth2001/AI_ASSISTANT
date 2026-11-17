"""Framework-independent error categories and message-template contract."""
from enum import Enum


class ErrorType(str, Enum):
    NOT_FOUND = "not_found"
    NOT_PERMISSION = "not_permission"
    UNAUTHORIZED = "unauthorized"
    VALIDATION = "validation"
    INVALID_REQUEST = "invalid_request"
    CONFLICT = "conflict"
    CONFIGURATION = "configuration"
    TIMEOUT = "timeout"
    EXTERNAL_SERVICE = "external_service"
    INTERNAL = "internal"


class ApplicationError(Exception):
    code = "application_error"
    error_type = ErrorType.INTERNAL
    message_template = "Application error"

    def __init__(self, message: str | None = None, **parameters):
        self.parameters = parameters
        self.message = self.message_template.format(**parameters) if message is None else message
        super().__init__(self.message)
