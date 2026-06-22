import os
import google.generativeai as genai
from pydantic import BaseModel
from typing import Optional, Type
from shared.llm.base import LLMProvider

class GeminiProvider(LLMProvider):
    def __init__(self, model_name: str = "gemini-3.5-flash"):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
    
    def generate_json(self, prompt: str, schema: Optional[Type[BaseModel]] = None) -> str:
        generation_config = genai.types.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.0
        )
        response = self.model.generate_content(prompt, generation_config=generation_config)
        return response.text
