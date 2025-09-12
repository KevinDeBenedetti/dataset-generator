import logging
import openai
import instructor
from typing import List
from core.config import config
from schemas.dataset import QA


class PromptManager:
    CLEANING_PROMPT = """
    You are an expert text cleaner. Goal: extract only the main informative content.
    
    Remove ALL of the following:
    - Navigation, menus, headers, footers
    - Bracketed references like [1], [2], etc.
    - Technical metadata, modification dates
    - Advertisements and promotional content
    - "edit" or "edit code" mentions
    - Language lists and navigation links
    - Scripts and technical tags
    
    KEEP ONLY:
    - The main written content
    - Important factual information
    - Logical structure in clear paragraphs
    
    Respond only with the cleaned text, no comments.
    """

    @classmethod
    def get_qa_prompt(cls, context: str, target_language: str = None) -> str:
        target_language = target_language or config.target_language or "en"
        return f"""
        Generate high-quality question-answer pairs based on this text.
        
        Strict rules:
        - Varied questions (what, who, when, where, why, how)
        - Complete and precise answers (minimum 2 sentences)
        - Context must be the exact excerpt that enables the answer
        - Avoid trivial or overly generic questions
        - Questions and answers must be in {target_language} language
        
        Source text:
        {context}...
        """


class LLMService:
    def __init__(self):
        self.client = openai.OpenAI(
            api_key=config.openai_api_key, base_url=config.openai_base_url
        )
        self.instructor_client = instructor.from_openai(
            self.client, mode=instructor.Mode.MD_JSON
        )
        self.prompt_manager = PromptManager()

    def clean_text(self, text: str, model: str = None) -> str:
        """Clean text using provided model or fallback to config.model_cleaning."""
        model = model or config.model_cleaning
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self.prompt_manager.CLEANING_PROMPT},
                    {"role": "user", "content": text[:10000]},
                ],
                max_tokens=config.max_tokens_cleaning,
                temperature=config.temperature,
            )
            return response.choices[0].message.content.strip() or text.strip()
        except Exception as e:
            logging.error(f"Text cleaning failed: {e}")
            return text

    def generate_qa(
        self, text: str, target_language: str = None, model: str = None
    ) -> List[QA]:
        """Generate QA using optional target_language and model; fall back to config."""
        target_language = target_language or config.target_language
        model = model or config.model_qa
        try:
            result = self.instructor_client.chat.completions.create(
                model=model,
                response_model=list[QA],
                messages=[
                    {
                        "role": "user",
                        "content": self.prompt_manager.get_qa_prompt(
                            text, target_language
                        ),
                    }
                ],
                max_tokens=config.max_tokens_qa,
            )
            return result
        except Exception as e:
            logging.error(f"QA generation failed: {e}")
            return []
