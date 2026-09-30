import functools
import logging
from typing import List, Optional

import openai

from server.core.config import config
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
    """Text cleaning, page transcription and embeddings.

    Cleaning and transcription take a model reference (``"<provider>:<model>"``,
    see services/providers) and run on either provider; embeddings stay on the
    OpenAI-compatible endpoint (the Qdrant sync needs its vector space).
    """

    def __init__(self):
        self.prompt_manager = PromptManager()

    @functools.cached_property
    def client(self) -> openai.OpenAI:
        # Lazy: building the real client touches SSL/certifi at construction
        # time, which some sandboxes block. Deferring it to first use means
        # instantiating LLMService is always safe, even when every method
        # that would touch the client is mocked out (as most tests do).
        return openai.OpenAI(
            api_key=config.openai_api_key, base_url=config.openai_base_url
        )

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
            )
            return result.text
        except Exception as e:
            logging.error(f"VLM text extraction failed: {e}")
            return ""

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
