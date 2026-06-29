"""Tests for the QA generation agent service (direct OpenAI SDK)."""

from unittest.mock import AsyncMock, patch

from server.services.agent import QAAgentService, _parse_qa_list


VALID_PAYLOAD = (
    '{"items": [{'
    '"question": "What is the capital of France?", '
    '"answer": "The capital of France is Paris, the largest city in the country.", '
    '"context": "France is a country in Western Europe whose capital is Paris."'
    "}]}"
)


class TestParseQaList:
    def test_parse_object_payload(self):
        items = _parse_qa_list(VALID_PAYLOAD)
        assert len(items) == 1
        assert items[0].question.endswith("?")

    def test_parse_fenced_bare_array(self):
        fenced = (
            "```json\n"
            '[{"question": "Who painted the Mona Lisa", '
            '"answer": "The Mona Lisa was painted by Leonardo da Vinci.", '
            '"context": "The Mona Lisa is a painting by Leonardo da Vinci, an Italian artist."}]'
            "\n```"
        )
        items = _parse_qa_list(fenced)
        assert len(items) == 1
        assert items[0].question == "Who painted the Mona Lisa?"

    def test_parse_empty_returns_empty(self):
        assert _parse_qa_list("") == []
        assert _parse_qa_list("   \n  ") == []
        assert _parse_qa_list("Sorry, I cannot help.") == []

    def test_parse_json_wrapped_in_prose(self):
        wrapped = "Sure, here you go: " + VALID_PAYLOAD + " Hope this helps."
        items = _parse_qa_list(wrapped)
        assert len(items) == 1

    def test_valid_object_recovered_after_invalid_array(self):
        # An array appears first but all its items fail validation (too short);
        # a valid QA object follows. The parser must not short-circuit on the
        # invalid array and lose the valid object.
        payload = (
            '[{"question": "hi?", "answer": "no", "context": "short"}] '
            "then: " + VALID_PAYLOAD
        )
        items = _parse_qa_list(payload)
        assert len(items) == 1
        assert items[0].question == "What is the capital of France?"

    def test_salvage_truncated_response_with_braces_in_values(self):
        # Outer JSON is cut off mid-array (unparseable) and an answer contains
        # literal braces — the salvage must still recover the complete item.
        truncated = (
            '{"items": [{'
            '"question": "What does the snippet print?", '
            '"answer": "It prints {\\"ok\\": true} as a JSON object to stdout.", '
            '"context": "The example calls print(json.dumps({\\"ok\\": True})) on a line."'
            '}, {"question": "What is in'
        )
        items = _parse_qa_list(truncated)
        assert len(items) == 1
        assert items[0].question == "What does the snippet print?"
        assert "{" in items[0].answer


def _service_with_run(return_value=None, side_effect=None):
    """A QAAgentService whose model call (_run) is mocked, no network."""
    service = QAAgentService()
    run = AsyncMock(return_value=return_value, side_effect=side_effect)
    return service, run


class TestQAAgentService:
    async def test_generate_qa_success(self):
        service, run = _service_with_run(return_value=VALID_PAYLOAD)
        with patch.object(service, "_run", run):
            result = await service.generate_qa("Some text about France.", "en", "m")
        assert len(result) == 1
        assert result[0].question == "What is the capital of France?"

    async def test_generate_qa_empty_content_returns_empty(self):
        service, run = _service_with_run(return_value="")
        with patch.object(service, "_run", run):
            result = await service.generate_qa("text", "en", "m")
        assert result == []

    async def test_generate_qa_invalid_payload_returns_empty(self):
        service, run = _service_with_run(return_value="not json at all")
        with patch.object(service, "_run", run):
            result = await service.generate_qa("text", "en", "m")
        assert result == []

    async def test_generate_qa_exception_returns_empty(self):
        service, run = _service_with_run(side_effect=RuntimeError("boom"))
        with patch.object(service, "_run", run):
            result = await service.generate_qa("text", "en", "m")
        assert result == []

    async def test_generate_qa_debug_reports_diagnostics(self):
        service, run = _service_with_run(return_value=VALID_PAYLOAD)
        with patch.object(service, "_run", run):
            info = await service.generate_qa_debug("text", "en", "gpt-x")
        assert info["count"] == 1
        assert info["model"] == "gpt-x"
        assert info["raw_length"] == len(VALID_PAYLOAD)
        assert info["error"] is None
        assert info["qa_pairs"][0]["question"].endswith("?")
