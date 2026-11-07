"""
Tests for LLM service (cleaning and transcription go through the provider registry).
"""

from unittest.mock import AsyncMock, patch

import pytest

from server.services.llm import LLMService, PromptManager
from server.tests.creds import FULL
from server.services.providers import CompletionResult, ProviderError


def test_prompt_manager_cleaning_prompt():
    assert "expert text cleaner" in PromptManager.CLEANING_PROMPT.lower()


def test_extraction_prompt_defined():
    assert "transcrib" in PromptManager.EXTRACTION_PROMPT.lower()


def test_llm_service_initialization():
    service = LLMService(FULL)
    assert service.creds is FULL
    assert service.prompt_manager is not None


async def test_clean_text_calls_the_given_model():
    with patch(
        "server.services.llm.complete",
        new=AsyncMock(return_value=CompletionResult("Cleaned text content")),
    ) as complete:
        result = await LLMService(FULL).clean_text(
            "Dirty text", "claude:claude-sonnet-5-5"
        )

    assert result == "Cleaned text content"
    ref, req, creds = complete.call_args.args
    assert creds is FULL
    assert ref == "claude:claude-sonnet-5-5"
    assert req.system == PromptManager.CLEANING_PROMPT
    assert req.user == "Dirty text"


async def test_clean_text_failure_returns_original():
    with patch(
        "server.services.llm.complete",
        new=AsyncMock(side_effect=ProviderError("down")),
    ):
        assert (
            await LLMService(FULL).clean_text("Original text", "openai:m")
            == "Original text"
        )


async def test_extract_text_from_image_sends_the_image():
    with patch(
        "server.services.llm.complete",
        new=AsyncMock(return_value=CompletionResult("Transcribed text")),
    ) as complete:
        result = await LLMService(FULL).extract_text_from_image(
            b"image-bytes", mime_type="image/png", model="openai:vlm-x"
        )

    assert result == "Transcribed text"
    ref, req, creds = complete.call_args.args
    assert creds is FULL
    assert ref == "openai:vlm-x"
    assert req.images == [(b"image-bytes", "image/png")]
    assert req.user == PromptManager.EXTRACTION_PROMPT


async def test_extract_text_from_image_failure_returns_empty():
    with patch(
        "server.services.llm.complete",
        new=AsyncMock(side_effect=ProviderError("down")),
    ):
        assert (
            await LLMService(FULL).extract_text_from_image(b"x", model="openai:m") == ""
        )


async def test_extract_text_from_image_requires_a_model():
    with pytest.raises(ValueError, match="vision model"):
        await LLMService(FULL).extract_text_from_image(b"x", model="")
