"""The reader's language, and the French of the texts the API serves.

The interface is in English and French (apps/next/i18n). Texts the server
holds itself — a job's title, description and options, what a job is missing,
the platform switches — are served in the reader's language: the one their
``dg-locale`` cookie names (the language switch writes it), else the first
their browser asks for that the interface has, else English.

English stays in the code, where each text is written; ``core/locales/fr.json``
holds the French, by key. A key without French falls back to the English.
"""

import json
import re
from string import Formatter
from contextvars import ContextVar, Token
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from fastapi import Request

LOCALES = ("en", "fr")
DEFAULT_LOCALE = "en"
# Written by the front end's language switch (apps/next/i18n/config.ts).
LOCALE_COOKIE = "dg-locale"

_CATALOGS = Path(__file__).parent / "locales"
# The only files ever opened: one per language that has a catalog. A language
# is looked up here, never made into a path — it comes from the request.
_CATALOG_FILES: Dict[str, Path] = {
    locale: _CATALOGS / f"{locale}.json"
    for locale in LOCALES
    if locale != DEFAULT_LOCALE
}


def _read_catalog(locale: str) -> Dict[str, Any]:
    """The catalog file of one of our languages; empty for any other name."""
    path = _CATALOG_FILES.get(locale)
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def pick_locale(cookie: Optional[str], accept_language: Optional[str]) -> str:
    """The reader's pick, else their browser's best language we have, else English."""
    if cookie in LOCALES:
        return cookie  # type: ignore[return-value]
    wanted = []
    for part in (accept_language or "").split(","):
        tag, _, params = part.strip().partition(";")
        weight = 1.0
        for param in params.split(";"):
            name, _, value = param.strip().partition("=")
            if name == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        if tag and weight > 0:
            wanted.append((weight, tag.strip().lower().split("-")[0]))
    for _, base in sorted(wanted, key=lambda item: -item[0]):
        if base in LOCALES:
            return base
    return DEFAULT_LOCALE


def request_locale(request: Request) -> str:
    """FastAPI dependency: the language of the request."""
    return pick_locale(
        request.cookies.get(LOCALE_COOKIE), request.headers.get("accept-language")
    )


def _flatten(tree: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
    flat: Dict[str, str] = {}
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = str(value)
    return flat


@lru_cache(maxsize=None)
def catalog(locale: str) -> Dict[str, str]:
    """The flat ``key -> text`` catalog of a language (none for English)."""
    return _flatten(_read_catalog(locale))


def tr(locale: str, key: str, english: str, **values: Any) -> str:
    """``english`` in ``locale``: its catalog entry for ``key``, else the English."""
    text = catalog(locale).get(key, english)
    return text.format(**values) if values else text


# The language of the request being served, set by main.py's middleware: code
# deep in a service (a run's metrics, services/jobs.py) reads it from here.
_current: ContextVar[str] = ContextVar("locale", default=DEFAULT_LOCALE)


def current_locale() -> str:
    return _current.get()


def set_locale(locale: str) -> Token[str]:
    """Make ``locale`` the current one, until :func:`reset_locale` with the token."""
    return _current.set(locale if locale in LOCALES else DEFAULT_LOCALE)


def reset_locale(token: Token[str]) -> None:
    _current.reset(token)


async def bind_locale(request: Request, call_next):
    """HTTP middleware: the request's language is the current one while it is
    served (sync routes too: their thread gets a copy of the context)."""
    token = set_locale(request_locale(request))
    try:
        return await call_next(request)
    finally:
        reset_locale(token)


# The embedding-check summary a run stores (jobs/qa_build.py embedding_summary):
# counts in a sentence, translated part by part.
_SUMMARY_PARTS = (
    (
        re.compile(r"^(\d+) new pair\(s\) checked for rephrasings and grounding$"),
        "checked",
    ),
    (
        re.compile(r"^(\d+) changed pair\(s\) re-checked against their source$"),
        "rechecked",
    ),
)


def _metric_value(locale: str, value: Any) -> Any:
    if not isinstance(value, str) or locale == DEFAULT_LOCALE:
        return value
    known = catalog(locale).get(f"metric_values.{value}")
    if known is not None:
        return known
    parts = value.split(", ")
    out = []
    for part in parts:
        for pattern, key in _SUMMARY_PARTS:
            match = pattern.match(part)
            if match:
                count = int(match.group(1))
                out.append(
                    tr(locale, f"metric_values.summary.{key}", part, count=count)
                )
                break
        else:
            return value  # a sentence we don't know: as it was stored
    return ", ".join(out)


def metrics_display(
    metrics: Sequence[Sequence[Any]], locale: Optional[str] = None
) -> List[List[Any]]:
    """A run's ``(label, value)`` metrics, stored in English, in ``locale``
    (the request's when left out): same order, labels and known values
    translated, the rest as stored."""
    locale = locale or current_locale()
    shown = []
    for item in metrics:
        if len(item) != 2:
            continue
        label, value = item
        shown.append(
            [tr(locale, f"metrics.{label}", str(label)), _metric_value(locale, value)]
        )
    return shown


@lru_cache(maxsize=None)
def _templates(locale: str) -> List[tuple]:
    """``(pattern, french)`` for every message template of a language: the
    server's own errors and skip reasons, matched whole, placeholders captured."""
    messages = _read_catalog(locale).get("messages", {})
    compiled = []
    for english, translated in messages.items():
        pattern = ""
        for literal, name, _, _ in Formatter().parse(english):
            pattern += re.escape(literal)
            if name:
                pattern += f"(?P<{name}>.+?)"
        fields = sum(1 for _, name, _, _ in Formatter().parse(english) if name)
        compiled.append((fields, re.compile(f"^{pattern}$", re.DOTALL), translated))
    # Fixed sentences first: "Deleting the dataset" before "Deleting {name}".
    compiled.sort(key=lambda item: item[0])
    return [(pattern, translated) for _, pattern, translated in compiled]


def _label(locale: str, value: str) -> str:
    """A captured value that is a known label ("your Hugging Face token", or
    several joined with " or ") in ``locale``; else as it was."""
    labels = catalog(locale)
    parts = value.split(" or ")
    if all(f"missing.{part}" in labels for part in parts):
        joiner = " ou " if locale == "fr" else " or "
        return joiner.join(labels[f"missing.{part}"] for part in parts)
    return value


def translate_message(
    text: Optional[str], locale: Optional[str] = None, depth: int = 0
) -> Optional[str]:
    """One of the server's own messages, stored in English (a run's error, why
    a schedule skipped), in ``locale`` (the request's when left out). A message
    it doesn't know — an upstream error, say — stays as it was stored."""
    locale = locale or current_locale()
    if not text or locale == DEFAULT_LOCALE:
        return text
    for pattern, translated in _templates(locale):
        match = pattern.match(text)
        if match:
            values = {k: _value(locale, v, depth) for k, v in match.groupdict().items()}
            return translated.format(**values)
    return text


def _value(locale: str, value: str, depth: int) -> str:
    """A value a message names: a known label, or one of the server's own
    phrases ("Deleting the dataset" in "… failed. Try again"), in ``locale``."""
    label = _label(locale, value)
    if label != value or depth >= 1:
        return label
    return translate_message(value, locale, depth + 1) or value
