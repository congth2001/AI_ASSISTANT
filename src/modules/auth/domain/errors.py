"""Central catalog of auth error codes and message templates."""
from src.common.errors import (
    ConflictError,
    ErrorType,
    PermissionDeniedError,
    UnauthorizedError,
    ValidationError,
)


class AuthenticationError(UnauthorizedError):
    code = "authentication_error"


class StaffCreationForbiddenError(PermissionDeniedError):
    code = 'staff_creation_forbidden'
    message_template = 'Only administrators can create staff accounts'


class DuplicateEmailError(ConflictError):
    code = 'duplicate_email'
    message_template = 'Email is already registered'


class InvalidCredentialsError(AuthenticationError):
    code = 'invalid_credentials'
    message_template = 'Email or password is incorrect'


class AccountDisabledError(AuthenticationError):
    code = 'account_disabled'
    message_template = 'Account is disabled'


class InvalidRefreshTokenError(AuthenticationError):
    code = 'invalid_refresh_token'
    message_template = 'Refresh token is invalid or has already been used'


class AccountUnavailableError(AuthenticationError):
    code = 'account_unavailable'
    message_template = 'Account is unavailable'


class InvalidJWTSecretError(ValidationError):
    error_type = ErrorType.CONFIGURATION
    code = 'invalid_jwt_secret'
    message_template = 'auth.jwt_secret must contain at least 32 characters'


class UnexpectedTokenTypeError(AuthenticationError):
    code = 'unexpected_token_type'
    message_template = 'Unexpected token type'


class MissingRefreshTokenIdentifierError(AuthenticationError):
    code = 'missing_refresh_token_identifier'
    message_template = 'Refresh token is missing an identifier'


class InvalidTokenError(AuthenticationError):
    code = 'invalid_token'
    message_template = 'Token is invalid or expired'


class InvalidEmailError(ValidationError):
    code = 'invalid_email'
    message_template = 'Invalid email address'


class PasswordTooLongError(ValidationError):
    code = 'password_too_long'
    message_template = 'Password must not exceed {max_bytes} bytes when UTF-8 encoded'
