from pydantic import BaseModel
from typing import Optional, Dict, Any
from uuid import UUID


class ChatRequestSchema(BaseModel):
    """Schema for chat requests"""
    conversation_id: UUID
    message: str
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ChatResponseSchema(BaseModel):
    """Schema for chat responses"""
    conversation_id: str
    response: str
    intent: str
    timestamp: str
    metadata: Optional[Dict[str, Any]] = None


class ReportRequestSchema(BaseModel):
    """Schema for report requests"""
    query: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None


class ReportResponseSchema(BaseModel):
    """Schema for report responses"""
    report: Dict[str, Any]
    generated_at: str


class DataIngestSchema(BaseModel):
    """Schema for data ingestion"""
    id: str
    data_type: str
    value: float
    date: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ConversationSchema(BaseModel):
    """Schema for conversation data"""
    id: str
    user_id: Optional[str] = None
    title: Optional[str] = None
    created_at: str
    updated_at: str
    message_count: int = 0