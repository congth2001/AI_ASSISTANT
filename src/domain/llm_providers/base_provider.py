"""
Abstract base class for LLM (Large Language Model) services.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class LLMProvider(ABC):
    """
    Abstract base class for LLM services.
    All LLM implementations should inherit from this class.
    """
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to the LLM service and initialize resources.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """
        Disconnect from the LLM service and release resources.
        
        Returns:
            bool: True if disconnection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def generate_response(
        self, 
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a response from the LLM.
        
        Args:
            prompt: The user prompt/question
            system_prompt: Optional system instructions
            temperature: Temperature for response generation (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            **kwargs: Additional model-specific parameters
            
        Returns:
            Dict containing response text and metadata
        """
        pass
    
    @abstractmethod
    def prepare_prompt(
        self, 
        question: str, 
        context: List[Dict[str, Any]],
        system_prompt: Optional[str] = None
        ) -> Dict[str, Any]:
        """
        Prepare the prompt for the LLM by combining question and context.
        
        Args:
            question: The user's question
            context: List of context documents
            system_prompt: Optional system instructions
            
        Returns:
            Dict with prepared prompt information
        """
        pass
    
    @abstractmethod
    def process_response(self, raw_response: Any) -> Dict[str, Any]:
        """
        Process the raw response from the LLM.
        
        Args:
            raw_response: Raw response from the LLM
            
        Returns:
            Dict with processed response data
        """
        pass