import logging
from typing import List, Dict, Any
from app.utils.llm_client import LLMClient
from app.schemas.dataset import TargetLanguage, ModelName

class LLMService:
    def __init__(self):
        self.client = LLMClient()
    
    def clean_text(self, content: str, model: ModelName) -> str:
        """Cleans text using an LLM model"""
        logging.info(f"Cleaning text with model: {model}")
        return self.client.clean_text(content, model)
    
    def generate_qa(self, cleaned_text: str, target_language: TargetLanguage, model: ModelName) -> List[Any]:
        """Generates QA pairs from cleaned text"""
        logging.info(f"Generating QA with model: {model}, target language: {target_language}")
        return self.client.generate_qa(cleaned_text, target_language, model)
