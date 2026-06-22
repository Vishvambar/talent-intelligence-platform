import os
from openai import OpenAI
from pydantic import BaseModel
from typing import Optional, Type
from shared.llm.base import LLMProvider

class GitHubModelsProvider(LLMProvider):
    def __init__(self, model_name: str = "gpt-4o-mini"):
        api_key = os.getenv("GITHUB_TOKEN")
        if not api_key:
            raise ValueError("GITHUB_TOKEN not found in environment.")
        # GitHub Models provides an OpenAI-compatible endpoint
        self.client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
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
