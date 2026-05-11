from typing import TypeVar, Generic, Optional
from pydantic import BaseModel

T = TypeVar('T')


class BaseResponse(BaseModel, Generic[T]):
    """Base response model for all API responses"""
    success: bool = True
    message: str = ""
    data: Optional[T] = None
    error: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True


class ErrorResponse(BaseModel):
    """Error response model"""
    success: bool = False
    message: str = ""
    error: str = ""
    details: Optional[dict] = None

    class Config:
        arbitrary_types_allowed = True


class PaginationResponse(BaseModel):
    """Pagination response model"""
    page: int = 1
    page_size: int = 10
    total: int = 0
    total_pages: int = 0

    class Config:
        arbitrary_types_allowed = True
