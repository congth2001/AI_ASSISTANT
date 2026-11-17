"""Translate known application errors to the existing HTTP detail contract."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.common.errors import ApplicationError, ErrorType


ERROR_STATUS = {
    ErrorType.NOT_FOUND: 404,
    ErrorType.NOT_PERMISSION: 403,
    ErrorType.UNAUTHORIZED: 401,
    ErrorType.VALIDATION: 400,
    ErrorType.INVALID_REQUEST: 422,
    ErrorType.CONFLICT: 409,
    ErrorType.TIMEOUT: 504,
    ErrorType.EXTERNAL_SERVICE: 502,
    ErrorType.CONFIGURATION: 500,
    ErrorType.INTERNAL: 500,
}


async def application_error_handler(_request: Request, error: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=ERROR_STATUS[error.error_type], content={"detail": error.message})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)
