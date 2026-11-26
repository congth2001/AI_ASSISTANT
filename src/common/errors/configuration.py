from .base import ErrorType
from .types import InternalError


class ConfigurationError(InternalError):
    """Invalid or unavailable configuration; messages must not contain secret inputs."""

    code = "configuration_error"
    error_type = ErrorType.CONFIGURATION
    message_template = "Invalid configuration"
