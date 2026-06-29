import base64
import logging
import openai
import instructor
from typing import Any, List, Dict, Optional, cast
from server.core.config import config
from server.schemas.dataset import QA


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

    EXTRACTION_PROMPT = """
    You are an expert document transcriber. Transcribe ALL readable text from
    this image into clean Markdown.

    Rules:
    - Output only the transcribed content — no preamble, no commentary.
    - Preserve headings, lists and tables; keep the reading order.
    - Drop page furniture: running headers/footers, page numbers, watermarks.
    - If the image contains no readable text, respond with an empty string.
    """

    @classmethod
    def get_qa_prompt(cls, context: str, target_language: Optional[str] = None) -> str:
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
        self.instructor_client = cast(
            Any, instructor.from_openai(self.client, mode=instructor.Mode.MD_JSON)
        )
        self.prompt_manager = PromptManager()

    def clean_text(self, text: str, model: Optional[str] = None) -> str:
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
            content = response.choices[0].message.content
            return (content or "").strip() or text.strip()
        except Exception as e:
            logging.error(f"Text cleaning failed: {e}")
            return text

    def extract_text_from_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        model: Optional[str] = None,
    ) -> str:
        """Transcribe an image (or rendered PDF page) to text via the VLM.

        Uses the configured vision model (``OPENAI_VLM_MODEL``). Returns the
        transcribed text, or an empty string if the call fails or the page has
        no readable text. Raises ``ValueError`` if no vision model is configured.
        """
        model = model or config.openai_vlm_model
        if not model:
            raise ValueError("No vision model configured (set OPENAI_VLM_MODEL)")

        b64 = base64.b64encode(image_bytes).decode("ascii")
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": self.prompt_manager.EXTRACTION_PROMPT,
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{b64}"
                                },
                            },
                        ],
                    }
                ],
                max_tokens=config.max_tokens_cleaning,
                temperature=config.temperature,
            )
            content = response.choices[0].message.content
            return (content or "").strip()
        except Exception as e:
            logging.error(f"VLM text extraction failed: {e}")
            return ""

    def generate_qa(
        self,
        text: str,
        target_language: Optional[str] = None,
        model: Optional[str] = None,
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

    def embed_texts(
        self, texts: List[str], model: Optional[str] = None
    ) -> List[List[float]]:
        """Embed a batch of texts via the configured embedding model.

        Returns one vector per input text, in order. Raises if the embedding
        model is not configured or the API call fails — callers (e.g. the Qdrant
        sync) need the failure to surface rather than silently produce no points.
        """
        model = model or config.openai_embedding_model
        if not model:
            raise ValueError(
                "No embedding model configured (set OPENAI_EMBEDDING_MODEL)"
            )
        if not texts:
            return []
        response = self.client.embeddings.create(model=model, input=texts)
        # The API preserves input order; sort defensively by index regardless.
        ordered = sorted(response.data, key=lambda d: d.index)
        return [list(item.embedding) for item in ordered]

    def get_models(self) -> List[Dict]:
        """Returns the list of available models from the OpenAI API."""
        try:
            resp = self.client.models.list()
            # resp.data contains model objects; we return a reduced list
            models = [
                {"id": m.id, "object": getattr(m, "object", None)} for m in resp.data
            ]
            return models
        except Exception as e:
            logging.error(f"Failed to list OpenAI models: {e}")
            return []
