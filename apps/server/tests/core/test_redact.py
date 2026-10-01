import logging

import pytest

from server.core.redact import MASK, RedactingFilter, redact

TOKENS = [
    "sk-proj-abcdefghijklmnopqrstuvwxyz012345",
    "sk-abcdefghijklmnopqrstuvwx",
    "sk-ant-api03-abcdefghijklmnop_qrstuv-wxyz",
    "sk-ant-oat01-abcdefghijklmnopqrstuvwxyz",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz",
    "hf_abcdefghijklmnopqrstuvwxyz0123",
]


@pytest.mark.parametrize("token", TOKENS)
def test_known_token_shapes_are_masked(token):
    out = redact(f"upstream said: Incorrect API key provided: {token}. Try again")
    assert token not in out and MASK in out
    assert out.startswith("upstream said")


def test_authorization_headers_and_key_values_are_masked():
    text = (
        "headers={'Authorization': 'Bearer abcdef0123456789xyz', "
        "'x-api-key': 'secretvalue123456'} password=hunter2hunter2 api_key: abc123abc123"
    )
    out = redact(text)
    for leaked in (
        "abcdef0123456789xyz",
        "secretvalue123456",
        "hunter2hunter2",
        "abc123abc123",
    ):
        assert leaked not in out
    assert "headers=" in out


def test_ordinary_text_is_untouched():
    text = (
        "Generated 12 pairs from https://example.com/docs in 3.4s (model gpt-4o-mini)"
    )
    assert redact(text) == text
    assert redact("") == ""


def test_the_log_filter_masks_message_args_and_tracebacks(caplog):
    logger = logging.getLogger("redact-test")
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    caplog.handler.addFilter(RedactingFilter())
    try:
        with caplog.at_level(logging.INFO, logger="redact-test"):
            logger.info("calling with key %s", TOKENS[0])
            try:
                raise RuntimeError(f"boom {TOKENS[4]}")
            except RuntimeError:
                logger.exception("failed")
    finally:
        logger.removeHandler(handler)

    assert TOKENS[0] not in caplog.text
    assert TOKENS[4] not in caplog.text
    assert "calling with key" in caplog.text and "failed" in caplog.text
