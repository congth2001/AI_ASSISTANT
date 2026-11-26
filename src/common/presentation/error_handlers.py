"""Translate known application errors to the existing HTTP detail contract."""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.common.errors import ApplicationError, ErrorType, RateLimitedError

logger = logging.getLogger(__name__)

ERROR_STATUS = {
    ErrorType.NOT_FOUND: 404,
    ErrorType.NOT_PERMISSION: 403,
    ErrorType.UNAUTHORIZED: 401,
    ErrorType.VALIDATION: 400,
    ErrorType.INVALID_REQUEST: 422,
    ErrorType.CONFLICT: 409,
    ErrorType.RATE_LIMITED: 429,
    ErrorType.TIMEOUT: 504,
    ErrorType.EXTERNAL_SERVICE: 502,
    ErrorType.CONFIGURATION: 500,
    ErrorType.INTERNAL: 500,
}

INTERNAL_ERROR_DETAIL = "internal_error"


async def application_error_handler(request: Request, error: ApplicationError) -> JSONResponse:
    status_code = ERROR_STATUS[error.error_type]
    if status_code >= 500:
        # Log server-side only; the client sees the catalog message, never adapter details.
        logger.error(
            "Application error %s (%s) on %s %s", error.code, error.error_type.value,
            request.method, request.url.path, exc_info=error,
        )
    headers = None
    if isinstance(error, RateLimitedError):
        headers = {"Retry-After": str(error.retry_after)}
    return JSONResponse(status_code=status_code, content={"detail": error.message}, headers=headers)


async def unhandled_exception_handler(request: Request, error: Exception) -> JSONResponse:
    """Last resort for HTTP requests; streaming endpoints report failures via SSE `error` events."""
    logger.error(
        "Unhandled exception on %s %s", request.method, request.url.path, exc_info=error,
    )
    return JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR_DETAIL})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
