from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Optional, Dict, Any
from uuid import UUID


class ILLMService(ABC):
    """Interface for LLM service"""

    @abstractmethod
    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate a response using LLM"""
        pass

    @abstractmethod
    async def stream_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> AsyncGenerator[str, None]:
        """Stream response tokens using LLM"""
        pass

    @abstractmethod
    async def analyze_intent(self, message: str) -> str:
        """Analyze the intent of a user message"""
        pass

    @abstractmethod
    async def classify_route(self, query: str) -> str:
        """Classify query into routing label: 'text_to_sql' | 'rag' | 'hybrid'."""
        pass

    @abstractmethod
    async def rewrite_query(self, prompt: str) -> str:
        """Rewrite an ambiguous query into a fully explicit one given conversation context."""
        pass
