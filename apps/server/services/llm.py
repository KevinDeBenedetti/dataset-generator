import logging
from typing import Optional

from server.core.config import config
from server.services.credentials import Credentials
from server.services.providers import CompletionRequest, complete


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


class LLMService:
    """Text cleaning and page transcription.

    Both take a model reference (``"<provider>:<model>"``, see
    services/providers) and run on either provider.
    """

    def __init__(self, creds: Credentials):
        self.creds = creds
        self.prompt_manager = PromptManager()

    async def clean_text(self, text: str, model: str) -> str:
        """Clean ``text`` with the ``model`` reference; the raw text on failure."""
        try:
            result = await complete(
                model,
                CompletionRequest(
                    system=self.prompt_manager.CLEANING_PROMPT,
                    user=text[:10000],
                    max_tokens=config.max_tokens_cleaning,
                ),
                self.creds,
            )
            return result.text or text.strip()
        except Exception as e:
            logging.error(f"Text cleaning failed: {e}")
            return text

    async def extract_text_from_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        model: Optional[str] = None,
    ) -> str:
        """Transcribe an image (or rendered PDF page) to text with a vision model.

        Returns the transcribed text, or an empty string if the call fails or
        the page has no readable text. Raises ``ValueError`` if no vision model
        is given.
        """
        if not model:
            raise ValueError("No vision model configured (set it on /models)")
        try:
            result = await complete(
                model,
                CompletionRequest(
                    user=self.prompt_manager.EXTRACTION_PROMPT,
                    images=[(image_bytes, mime_type)],
                    max_tokens=config.max_tokens_cleaning,
                ),
                self.creds,
            )
            return result.text
        except Exception as e:
            logging.error(f"VLM text extraction failed: {e}")
            return ""
