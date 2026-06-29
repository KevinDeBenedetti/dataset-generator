"""
Tests for LLM service.
"""

import pytest
from unittest.mock import MagicMock, patch
from server.services.llm import LLMService, PromptManager
from server.core.config import config


def test_prompt_manager_cleaning_prompt():
    """Test that cleaning prompt is defined."""
    assert PromptManager.CLEANING_PROMPT is not None
    assert "expert text cleaner" in PromptManager.CLEANING_PROMPT.lower()


def test_prompt_manager_qa_prompt_default_language():
    """Test QA prompt generation with default language."""
    prompt = PromptManager.get_qa_prompt("Sample context text")
    assert "Sample context text" in prompt
    assert "question-answer pairs" in prompt.lower()


def test_prompt_manager_qa_prompt_custom_language():
    """Test QA prompt generation with custom language."""
    prompt = PromptManager.get_qa_prompt("Sample context", target_language="fr")
    assert "fr" in prompt
    assert "Sample context" in prompt


@patch("server.services.llm.openai.OpenAI")
@patch("server.services.llm.instructor.from_openai")
def test_llm_service_initialization(mock_instructor, mock_openai):
    """Test LLMService initialization."""
    service = LLMService()
    assert service.client is not None
    assert service.instructor_client is not None
    assert service.prompt_manager is not None


@patch("server.services.llm.openai.OpenAI")
def test_clean_text_success(mock_openai_class):
    """Test successful text cleaning."""
    # Setup mock
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Cleaned text content"
    mock_client.chat.completions.create.return_value = mock_response

    with patch("server.services.llm.instructor.from_openai"):
        service = LLMService()
        result = service.clean_text("Dirty text with ads and navigation")

    assert result == "Cleaned text content"
    mock_client.chat.completions.create.assert_called_once()


@patch("server.services.llm.openai.OpenAI")
def test_clean_text_failure_returns_original(mock_openai_class):
    """Test that clean_text returns original text on failure."""
    # Setup mock to raise exception
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("API Error")

    with patch("server.services.llm.instructor.from_openai"):
        service = LLMService()
        original_text = "Original text"
        result = service.clean_text(original_text)

    assert result == original_text


@patch("server.services.llm.openai.OpenAI")
@patch("server.services.llm.instructor.from_openai")
def test_generate_qa_success(mock_instructor_from, mock_openai_class):
    """Test successful QA generation."""
    # Setup mocks
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_instructor_client = MagicMock()
    mock_instructor_from.return_value = mock_instructor_client

    # Mock QA response
    mock_qa = MagicMock()
    mock_qa.question = "Test question?"
    mock_qa.answer = "Test answer"
    mock_instructor_client.chat.completions.create.return_value = [mock_qa]

    service = LLMService()
    result = service.generate_qa("Sample text for QA generation")

    assert len(result) == 1
    assert result[0].question == "Test question?"
    assert result[0].answer == "Test answer"


@patch("server.services.llm.openai.OpenAI")
@patch("server.services.llm.instructor.from_openai")
def test_generate_qa_failure_returns_empty(mock_instructor_from, mock_openai_class):
    """Test that generate_qa returns empty list on failure."""
    # Setup mocks
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_instructor_client = MagicMock()
    mock_instructor_from.return_value = mock_instructor_client
    mock_instructor_client.chat.completions.create.side_effect = Exception("API Error")

    service = LLMService()
    result = service.generate_qa("Sample text")

    assert result == []


@patch("server.services.llm.openai.OpenAI")
def test_get_models_success(mock_openai_class):
    """Test successful model listing."""
    # Setup mock
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_model1 = MagicMock()
    mock_model1.id = "gpt-4"
    mock_model1.object = "model"

    mock_model2 = MagicMock()
    mock_model2.id = "gpt-3.5-turbo"
    mock_model2.object = "model"

    mock_response = MagicMock()
    mock_response.data = [mock_model1, mock_model2]
    mock_client.models.list.return_value = mock_response

    with patch("server.services.llm.instructor.from_openai"):
        service = LLMService()
        result = service.get_models()

    assert len(result) == 2
    assert result[0]["id"] == "gpt-4"
    assert result[1]["id"] == "gpt-3.5-turbo"


@patch("server.services.llm.openai.OpenAI")
def test_get_models_failure_returns_empty(mock_openai_class):
    """Test that get_models returns empty list on failure."""
    # Setup mock to raise exception
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    mock_client.models.list.side_effect = Exception("API Error")

    with patch("server.services.llm.instructor.from_openai"):
        service = LLMService()
        result = service.get_models()

    assert result == []


def test_extraction_prompt_defined():
    assert PromptManager.EXTRACTION_PROMPT is not None
    assert "transcrib" in PromptManager.EXTRACTION_PROMPT.lower()


@patch("server.services.llm.openai.OpenAI")
def test_extract_text_from_image_success(mock_openai_class):
    """A vision message with an image_url is sent and the text is returned."""
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "  Transcribed text  "
    mock_client.chat.completions.create.return_value = mock_response

    with patch("server.services.llm.instructor.from_openai"):
        service = LLMService()
        result = service.extract_text_from_image(
            b"image-bytes", mime_type="image/png", model="vlm-x"
        )

    assert result == "Transcribed text"  # stripped
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "vlm-x"
    content = kwargs["messages"][0]["content"]
    assert any(part.get("type") == "image_url" for part in content)
    image_part = next(p for p in content if p.get("type") == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


@patch("server.services.llm.openai.OpenAI")
def test_extract_text_from_image_failure_returns_empty(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("API Error")

    with patch("server.services.llm.instructor.from_openai"):
        service = LLMService()
        assert service.extract_text_from_image(b"x", model="vlm-x") == ""


@patch("server.services.llm.openai.OpenAI")
def test_extract_text_from_image_requires_vlm_model(mock_openai_class, monkeypatch):
    monkeypatch.setattr(config, "openai_vlm_model", "")
    with patch("server.services.llm.instructor.from_openai"):
        service = LLMService()
        with pytest.raises(ValueError, match="vision model"):
            service.extract_text_from_image(b"x")
