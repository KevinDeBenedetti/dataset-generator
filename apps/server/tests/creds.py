"""Credentials for tests: explicit objects instead of env vars and config attributes."""

from dataclasses import replace
from typing import Any

from pydantic import SecretStr

from server.services.credentials import SECRET_KINDS, Credentials


def make_creds(**values: Any) -> Credentials:
    """A ``Credentials`` from plain strings (secret kinds are wrapped as SecretStr)."""
    wrapped = {
        k: SecretStr(v) if k in SECRET_KINDS and isinstance(v, str) else v
        for k, v in values.items()
    }
    return Credentials(**wrapped)  # ty: ignore[invalid-argument-type]


# Everything configured, the operator's endpoint (so no SSRF pinning in unit tests).
FULL = make_creds(
    openai_api_key="test-openai-key",
    claude_token="sk-ant-oat01-test-token",
    hf_token="hf_test_token",
    github_token="ghp_testtoken",
    github_username="kevin",
    hf_qa_repo="kevin/github-qa",
    hf_corpus_repo="kevin/corpus",
    base_url_trusted=True,
)
NONE = Credentials()

__all__ = ["FULL", "NONE", "make_creds", "replace"]
