from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from uuid import UUID


class ILLMService(ABC):
    """Interface for LLM service"""

    @abstractmethod
    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate a response using LLM"""
        pass

    @abstractmethod
    async def analyze_intent(self, message: str) -> str:
        """Analyze the intent of a user message"""
        pass
