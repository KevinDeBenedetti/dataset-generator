"""Scrub credentials out of text before it is logged or stored.

Provider SDKs and HTTP libraries sometimes echo a key back inside an error
message ("Incorrect API key provided: sk-…", a request dump with its
Authorization header). :func:`redact` masks the well-known token shapes, and
:class:`RedactingFilter` applies it to every log record; job errors go through it
before they are saved on a run.
"""

import logging
import re

MASK = "[redacted]"

_PATTERNS = [
    # Anthropic before the generic sk- rule, so the whole token goes.
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]{12,}"),
    re.compile(
        r"(?i)((?:authorization|x-api-key|api[_-]?key|token|secret|password)"
        r"[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&]{8,}"
    ),
]


def redact(text: str) -> str:
    """``text`` with tokens, bearer credentials and key/value secrets masked."""
    if not text:
        return text
    out = text
    for pattern in _PATTERNS:
        if pattern.groups:
            out = pattern.sub(lambda m: m.group(1) + MASK, out)
        else:
            out = pattern.sub(MASK, out)
    return out


class RedactingFilter(logging.Filter):
    """Masks secrets in a record's message and traceback text."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — a bad format string is not ours to fix
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True
