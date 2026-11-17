from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class SearchDocumentRequest(BaseModel):
    query: str


class SearchResultItem(BaseModel):
    doc_id: str
    doc_type: str
    text: str
    score: float
    metadata: Dict[str, Any] = {}


class SearchDocumentResponse(BaseModel):
    query: str
    results: List[SearchResultItem]
    used_fallback: bool = False
