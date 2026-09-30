"""
Tests for LLM service (cleaning and transcription go through the provider registry).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.services.llm import LLMService, PromptManager
from server.services.providers import CompletionResult, ProviderError


def test_prompt_manager_cleaning_prompt():
    assert "expert text cleaner" in PromptManager.CLEANING_PROMPT.lower()


def test_extraction_prompt_defined():
    assert "transcrib" in PromptManager.EXTRACTION_PROMPT.lower()


@patch("server.services.llm.openai.OpenAI")
def test_llm_service_initialization(mock_openai):
    service = LLMService()
    assert service.client is not None
    assert service.prompt_manager is not None


async def test_clean_text_calls_the_given_model():
    with patch(
        "server.services.llm.complete",
        new=AsyncMock(return_value=CompletionResult("Cleaned text content")),
    ) as complete:
        result = await LLMService().clean_text("Dirty text", "claude:claude-sonnet-5")

    assert result == "Cleaned text content"
    ref, req = complete.call_args.args
    assert ref == "claude:claude-sonnet-5"
    assert req.system == PromptManager.CLEANING_PROMPT
    assert req.user == "Dirty text"


async def test_clean_text_failure_returns_original():
    with patch(
        "server.services.llm.complete",
        new=AsyncMock(side_effect=ProviderError("down")),
    ):
        assert (
            await LLMService().clean_text("Original text", "openai:m")
            == "Original text"
        )


async def test_extract_text_from_image_sends_the_image():
    with patch(
        "server.services.llm.complete",
        new=AsyncMock(return_value=CompletionResult("Transcribed text")),
    ) as complete:
        result = await LLMService().extract_text_from_image(
            b"image-bytes", mime_type="image/png", model="openai:vlm-x"
        )

    assert result == "Transcribed text"
    ref, req = complete.call_args.args
    assert ref == "openai:vlm-x"
    assert req.images == [(b"image-bytes", "image/png")]
    assert req.user == PromptManager.EXTRACTION_PROMPT


async def test_extract_text_from_image_failure_returns_empty():
    with patch(
        "server.services.llm.complete",
        new=AsyncMock(side_effect=ProviderError("down")),
    ):
        assert await LLMService().extract_text_from_image(b"x", model="openai:m") == ""


async def test_extract_text_from_image_requires_a_model():
    with pytest.raises(ValueError, match="vision model"):
        await LLMService().extract_text_from_image(b"x", model="")


@patch("server.services.llm.openai.OpenAI")
def test_embed_texts_orders_by_index(mock_openai_class, monkeypatch):
    from server.core.config import config

    monkeypatch.setattr(config, "openai_embedding_model", "emb")
    client = MagicMock()
    mock_openai_class.return_value = client
    client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(index=1, embedding=[2.0]), MagicMock(index=0, embedding=[1.0])]
    )
    assert LLMService().embed_texts(["a", "b"]) == [[1.0], [2.0]]
