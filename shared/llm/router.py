import os
import yaml
import json
import hashlib
import logging
from typing import Dict, Any, Type, TypeVar, Optional
from pydantic import BaseModel, ValidationError
from shared.llm.providers.gemini import GeminiProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)

class LLMRouter:
    def __init__(self, config_path: str = "config/hyperparams.yaml"):
        # Ensure we can find config from anywhere
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        abs_config_path = os.path.join(root_dir, config_path)
            
        with open(abs_config_path, "r") as f:
            config = yaml.safe_load(f)
            
        self.llm_config = config.get("llm", {})
        self.provider_priority = self.llm_config.get("provider_priority", {})
        self.max_retries = self.llm_config.get("max_retries", 3)
        self.cache_enabled = self.llm_config.get("cache_responses", True)
        self.cache_version = self.llm_config.get("cache_version", "v1")
        
        self.cache_dir = os.path.join(root_dir, "data", "artifacts", "llm_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.providers = {}
        # Lazily instantiate providers based on available keys
        if os.getenv("GEMINI_API_KEY"):
            self.providers["gemini"] = GeminiProvider()
            
    def _get_cache_path(self, prompt: str, phase: str) -> str:
        prompt_hash = hashlib.sha256(f"{self.cache_version}_{phase}_{prompt}".encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{prompt_hash}.json")

    def _read_cache(self, prompt: str, phase: str) -> Optional[str]:
        if not self.cache_enabled:
            return None
        cache_path = self._get_cache_path(prompt, phase)
        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                return f.read()
        return None

    def _write_cache(self, prompt: str, phase: str, response: str):
        if not self.cache_enabled:
            return
        cache_path = self._get_cache_path(prompt, phase)
        with open(cache_path, "w") as f:
            f.write(response)

    def generate(self, prompt: str, phase: str, schema: Type[T]) -> T:
        """
        Generates a JSON response from the optimal provider, enforcing Pydantic schema validation.
        """
        # 1. Check cache
        cached = self._read_cache(prompt, phase)
        if cached:
            try:
                # If cached version perfectly matches current Pydantic schema bounds
                parsed = schema.model_validate_json(cached)
                logger.info(f"[{phase}] Cache hit. Skipping LLM call.")
                return parsed
            except ValidationError:
                logger.warning(f"[{phase}] Cache exists but invalid for current schema. Ignoring cache.")
                
        # 2. Get provider chain
        chain = self.provider_priority.get(phase, ["gemini"])
        last_exception = None
        
        for provider_name in chain:
            provider = self.providers.get(provider_name)
            if not provider:
                logger.debug(f"[{phase}] Provider '{provider_name}' requested but no API key configured. Skipping.")
                continue
                
            logger.info(f"[{phase}] Attempting generation with provider: {provider_name}")
            
            for attempt in range(self.max_retries):
                try:
                    # Append strict JSON instruction
                    full_prompt = prompt + f"\n\nYou MUST return ONLY valid JSON that precisely matches this JSON schema:\n{json.dumps(schema.model_json_schema())}"
                    
                    raw_json = provider.generate_json(full_prompt, schema)
                    
                    # Clean markdown code blocks
                    raw_json = raw_json.strip()
                    if raw_json.startswith("```json"):
                        raw_json = raw_json[7:-3].strip()
                    elif raw_json.startswith("```"):
                        raw_json = raw_json[3:-3].strip()
                        
                    # Validate against Pydantic schema
                    parsed = schema.model_validate_json(raw_json)
                    
                    # Success
                    self._write_cache(prompt, phase, raw_json)
                    return parsed
                    
                except ValidationError as e:
                    last_exception = e
                    logger.warning(f"[{phase}] Provider {provider_name} returned invalid JSON structure (Attempt {attempt+1}/{self.max_retries}). Error: {e}")
                    # Retry on validation error
                    continue
                except Exception as e:
                    last_exception = e
                    logger.warning(f"[{phase}] Provider {provider_name} failed with provider error: {e}")
                    # Break to failover to the next provider on 429/503
                    break 
                    
        raise RuntimeError(f"All configured providers for phase '{phase}' failed. Last error: {str(last_exception)}")
