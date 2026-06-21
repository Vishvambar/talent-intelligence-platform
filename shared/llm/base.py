from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel

class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""
    
    @abstractmethod
    def generate_json(self, prompt: str, schema: Optional[Type[BaseModel]] = None) -> str:
        """
        Generate a JSON response from the LLM provider.
        Should return the raw JSON string.
        Should raise an exception if it hits a 429, 503, or other provider errors.
        """
        pass
