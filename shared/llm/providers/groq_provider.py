import os
from groq import Groq
from pydantic import BaseModel
from typing import Optional, Type
from shared.llm.base import LLMProvider

class GroqProvider(LLMProvider):
    def __init__(self, model_name: str = "llama-3.1-8b-instant"):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment.")
        self.client = Groq(api_key=api_key)
        self.model = model_name
    
    def generate_json(self, prompt: str, schema: Optional[Type[BaseModel]] = None) -> str:
        messages = [
            {"role": "system", "content": "You are an expert analytical JSON extractor."},
            {"role": "user", "content": prompt}
        ]
        response = self.client.chat.completions.create(
            messages=messages,
            model=self.model,
            response_format={"type": "json_object"},
            temperature=0.0
        )
        return response.choices[0].message.content
