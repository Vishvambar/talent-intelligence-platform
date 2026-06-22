import os
from openai import OpenAI
from pydantic import BaseModel
from typing import Optional, Type
from shared.llm.base import LLMProvider

class OpenRouterProvider(LLMProvider):
    def __init__(self, model_name: str = "meta-llama/llama-3-8b-instruct"):
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment.")
        # OpenRouter provides an OpenAI-compatible endpoint
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.model = model_name
    
    def generate_json(self, prompt: str, schema: Optional[Type[BaseModel]] = None) -> str:
        messages = [
            {"role": "system", "content": "You are an expert analytical JSON extractor. Return raw JSON."},
            {"role": "user", "content": prompt}
        ]
        response = self.client.chat.completions.create(
            messages=messages,
            model=self.model,
            response_format={"type": "json_object"},
            temperature=0.0
        )
        return response.choices[0].message.content
