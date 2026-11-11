"""Your resumes on Reactive Resume (https://rxresu.me, or a self-hosted one).

Read-only, through the instance's OpenAPI routes (``/api/openapi``), with two
server secrets: REACTIVE_RESUME_URL, the root of the instance (blank: the
hosted one), and REACTIVE_RESUME_API_KEY, a key of the operator's account sent
as ``x-api-key``. The list is every resume that key can read; a resume is then
fetched by its id. The key is the operator's, never a user's, so only admins
reach this (api/resumes.py).

A resume is answered as text, never as the instance's HTML: its rich text
(summary, descriptions) is turned into lines, hidden sections and items are
left out, and only http(s) links are kept. Field names follow Reactive Resume
v5 and v6, read as the portfolio's indexer reads them (portfolio-next,
``src/lib/rag/resume.ts``).
"""

import html
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin, urlsplit

import httpx

from server.core.config import config

DEFAULT_URL = "https://rxresu.me"
TIMEOUT_SECONDS = 15.0

# A resume id as Reactive Resume makes them (UUIDs, cuid2): anything else is
# refused before a request, so it can't steer the path.
_RESUME_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ResumeNotConfiguredError(RuntimeError):
    """No REACTIVE_RESUME_API_KEY on the server."""


class ResumeNotFoundError(LookupError):
    """No such resume for the key's account."""


class ResumeUnavailableError(RuntimeError):
    """The instance refused the key, redirected, failed or answered no resume."""


def configured() -> bool:
    return bool(config.reactive_resume_api_key.strip())


def instance_url() -> str:
    """The instance's root, without a trailing slash."""
    return (config.reactive_resume_url.strip() or DEFAULT_URL).rstrip("/")


def instance_origin() -> str:
    """The instance as shown in messages: scheme, host and port only."""
    parts = urlsplit(instance_url())
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname or ''}{port}"


def _https_upgrade(request_url: str, location: str) -> Optional[str]:
    """The https address of the instance when ``location`` only moves the
    request to https on the same host and path (an ingress enforcing TLS),
    else None: any other redirect is the operator's to look into."""
    root = urlsplit(instance_url())
    if root.scheme != "http" or not location:
        return None
    target = urlsplit(urljoin(request_url, location))
    asked = urlsplit(request_url)
    if (target.scheme, target.hostname, target.path) != (
        "https",
        asked.hostname,
        asked.path,
    ) or target.port not in (None, 443):
        return None
    # On https's own port: an http port given in REACTIVE_RESUME_URL goes.
    return f"https://{target.netloc.rsplit(':443', 1)[0]}{root.path}"


def _not_an_instance() -> ResumeUnavailableError:
    return ResumeUnavailableError(
        f"{instance_origin()} answered no resume: REACTIVE_RESUME_URL must be the "
        "root of a Reactive Resume instance (v5 or later)"
    )


async def _get(
    path: str,
    params: Optional[Dict[str, str]] = None,
    missing: Optional[Exception] = None,
) -> Any:
    """The JSON an OpenAPI route of the instance answers, read with the key.
    ``missing`` is what a 404 raises (default: no such resume)."""
    key = config.reactive_resume_api_key.strip()
    if not key:
        raise ResumeNotConfiguredError(
            "Reactive Resume isn't set up: set REACTIVE_RESUME_API_KEY on the "
            "server (and REACTIVE_RESUME_URL for a self-hosted instance)"
        )
    try:
        # Redirects are not followed: the key opens the whole account, and the
        # client would send it on to wherever a redirect points.
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            response = await client.get(
                f"{instance_url()}/api/openapi{path}",
                params=params,
                headers={
                    "x-api-key": key,
                    "Accept": "application/json",
                    "User-Agent": "dataset-generator",
                },
            )
    except httpx.TimeoutException:
        raise ResumeUnavailableError(
            f"{instance_origin()} did not answer within {TIMEOUT_SECONDS:.0f} s"
        ) from None
    except httpx.HTTPError as exc:
        raise ResumeUnavailableError(
            f"{instance_origin()} can't be reached ({type(exc).__name__}): "
            "check REACTIVE_RESUME_URL"
        ) from None

    status = response.status_code
    if 300 <= status < 400:
        https = _https_upgrade(
            str(response.request.url), response.headers.get("location", "")
        )
        if https:
            raise ResumeUnavailableError(
                f"{instance_origin()} only answers over https: set "
                f"REACTIVE_RESUME_URL={https}, so the key travels encrypted"
            )
        raise ResumeUnavailableError(
            f"{instance_origin()} redirects ({status}): set REACTIVE_RESUME_URL "
            "to the instance's final address"
        )
    if status == 401:
        raise ResumeUnavailableError(
            "The instance doesn't know REACTIVE_RESUME_API_KEY (mistyped, "
            "expired, revoked, or a key of another instance)"
        )
    if status == 403:
        raise ResumeUnavailableError("REACTIVE_RESUME_API_KEY has no read access")
    if status == 404:
        raise missing or ResumeNotFoundError("No such resume in the API key's account")
    if status >= 400:
        raise ResumeUnavailableError(f"{instance_origin()} answered {status}")
    try:
        return response.json()
    except ValueError:
        raise _not_an_instance() from None


# --- reading -------------------------------------------------------------------


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


async def list_resumes() -> Dict[str, Any]:
    """Every resume the key's account holds, most recently updated first."""
    body = await _get("/resumes", {"sort": "lastUpdatedAt"}, missing=_not_an_instance())
    if not isinstance(body, list):
        raise _not_an_instance()
    resumes = [
        {
            "id": _text(r.get("id")),
            "name": _text(r.get("name")) or _text(r.get("slug")) or "Untitled",
            "slug": _text(r.get("slug")),
            "tags": [t for t in r.get("tags") or [] if isinstance(t, str)],
            "is_public": bool(r.get("isPublic")),
            "is_locked": bool(r.get("isLocked")),
            "updated_at": _text(r.get("updatedAt")) or None,
        }
        for r in body
        if isinstance(r, dict) and _text(r.get("id"))
    ]
    return {"instance": instance_origin(), "resumes": resumes}


async def get_resume(resume_id: str) -> Dict[str, Any]:
    """One resume of the key's account, as text (see :func:`resume_view`)."""
    if not _RESUME_ID.match(resume_id or ""):
        raise ResumeNotFoundError("No such resume in the API key's account")
    body = await _get(f"/resumes/{quote(resume_id, safe='')}")
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise _not_an_instance()
    return resume_view(body)


# --- a resume as text ------------------------------------------------------------


def html_to_text(value: Any) -> str:
    """The text of Reactive Resume's rich text (v5+, the summary and every
    description): list items become "- " lines, blocks become lines, the rest
    of the markup goes. Text without markup comes back as written."""
    if not isinstance(value, str):
        return ""
    if "<" in value or "&" in value:
        value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
        value = re.sub(r"<li\b[^>]*>", "\n- ", value, flags=re.I)
        value = re.sub(
            r"</(?:p|div|li|h[1-6]|blockquote|pre|tr)\s*>", "\n", value, flags=re.I
        )
        value = html.unescape(re.sub(r"<[^>]*>", "", value))
    lines = (line.strip() for line in value.split("\n"))
    return "\n".join(line for line in lines if line)


def _safe_url(value: Any) -> str:
    """A link worth showing: http(s) only, so nothing like ``javascript:``."""
    url = _text(value.get("url")) if isinstance(value, dict) else _text(value)
    return url if urlsplit(url).scheme in ("http", "https") else ""


def _dates(value: Any) -> str:
    """Structured dates (v6) as text: "2020 – 2022", "2021-03 – Present"."""
    if not isinstance(value, dict):
        return ""
    if _text(value.get("raw")):
        return _text(value.get("raw"))
    start = _text(value.get("start"))
    if not start:
        return ""
    if value.get("present"):
        return f"{start} – Present"
    end = _text(value.get("end"))
    return f"{start} – {end}" if end and end != start else start


def _period(item: Dict[str, Any]) -> str:
    """An item's period: its text (Reactive Resume writes it from the
    structured dates on every save), else those dates."""
    return (
        _text(item.get("period"))
        or _text(item.get("date"))
        or _dates(item.get("dates"))
    )


def _level(item: Dict[str, Any]) -> str:
    """A skill's or a language's level: as written, else v6's scale as "4/5"."""
    written = _text(item.get("proficiency")) or _text(item.get("fluency"))
    if written:
        return written
    level = item.get("level")
    if isinstance(level, (int, float)) and not isinstance(level, bool):
        return f"{int(level)}/5" if level > 0 else ""
    return "" if _text(level) in ("", "0") else _text(level)


# What heads an item and what qualifies it, by section (or custom section type).
_FIELDS: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "experience": (("position",), ("company",)),
    "education": (("degree", "studyType"), ("school", "institution")),
    "volunteer": (("position",), ("organization",)),
    "volunteering": (("position",), ("organization",)),
    "references": (("name",), ("position",)),
    "profiles": (("network",), ("username",)),
    "languages": (("language", "name"), ()),
    "certifications": (("title", "name"), ("issuer",)),
    "certificates": (("title", "name"), ("issuer",)),
    "awards": (("title", "name"), ("awarder",)),
    "publications": (("title", "name"), ("publisher",)),
    "cover-letter": (("recipient",), ()),
}
_DEFAULT_FIELDS: Tuple[Tuple[str, ...], Tuple[str, ...]] = (("name", "title"), ())


def _first(item: Dict[str, Any], keys: Sequence[str]) -> str:
    return next((_text(item.get(k)) for k in keys if _text(item.get(k))), "")


def _item(item: Dict[str, Any], kind: str, key: str) -> Optional[Dict[str, Any]]:
    """One visible item as text; ``key`` names it when Reactive Resume didn't."""
    heads, qualifiers = _FIELDS.get(kind, _DEFAULT_FIELDS)
    roles = [r for r in item.get("roles") or [] if isinstance(r, dict)]
    title = _first(item, heads)
    if kind == "experience" and not title:
        title = _first(roles[0], ("position",)) if roles else ""
    if kind == "education" and _text(item.get("area")):
        title = " · ".join(p for p in (title, _text(item.get("area"))) if p)
    subtitle = " · ".join(
        p
        for p in (_first(item, qualifiers), _text(item.get("location")), _level(item))
        if p
    )

    lines: List[str] = []
    text = (
        html_to_text(item.get("description"))
        or html_to_text(item.get("summary"))
        or html_to_text(item.get("content"))
    )
    if text:
        lines.append(text)
    lines.extend(f"- {_text(h)}" for h in item.get("highlights") or [] if _text(h))
    for role in roles:
        position, role_text = (
            _text(role.get("position")),
            html_to_text(role.get("description")),
        )
        if position or role_text:
            period = _period(role)
            lines.append(f"Role: {position}" + (f" ({period})" if period else ""))
            if role_text:
                lines.append(role_text)
    grade = _text(item.get("grade")) or _text(item.get("score"))
    if grade:
        lines.append(f"Grade: {grade}")
    # Each keyword once, in order: it is its own key on the page.
    keywords = list(
        dict.fromkeys(_text(k) for k in item.get("keywords") or [] if _text(k))
    )

    if not (title or lines or keywords):
        return None
    return {
        "id": _text(item.get("id")) or key,
        "title": title or "Untitled",
        "subtitle": subtitle,
        "period": _period(item),
        "text": "\n".join(lines),
        "keywords": keywords,
        "url": _safe_url(item.get("website")) or _safe_url(item.get("url")),
    }


def _section(key: str, section: Any, kind: str) -> Optional[Dict[str, Any]]:
    """A visible section with its visible items, or None."""
    if not isinstance(section, dict) or section.get("hidden"):
        return None
    items = [
        shown
        for i, it in enumerate(section.get("items") or [])
        if isinstance(it, dict) and not it.get("hidden")
        for shown in [_item(it, kind, f"{key}-{i}")]
        if shown
    ]
    if not items:
        return None
    # Ids must tell the items apart on the page: a repeated one gets its rank.
    seen: set = set()
    for i, shown in enumerate(items):
        if shown["id"] in seen:
            shown["id"] = f"{shown['id']}-{i}"
        seen.add(shown["id"])
    title = _text(section.get("title")) or key.replace("-", " ").capitalize()
    return {"key": key, "title": title, "items": items}


def _basics(data: Dict[str, Any]) -> Dict[str, Any]:
    basics = data.get("basics")
    # One schema of the API reference wraps the basics in a section of one item.
    if isinstance(basics, dict) and isinstance(basics.get("items"), list):
        basics = next((i for i in basics["items"] if isinstance(i, dict)), {})
    if not isinstance(basics, dict):
        basics = {}
    facts: List[str] = []
    links: List[Dict[str, str]] = []
    for custom in basics.get("customFields") or []:
        if not isinstance(custom, dict):
            continue
        text = _text(custom.get("text")) or _text(custom.get("value"))
        label = _text(custom.get("label"))
        link = _safe_url(custom.get("link"))
        # Each once (the page keys them by their URL and their text).
        if link:
            if all(known["url"] != link for known in links):
                links.append({"label": text or label or link, "url": link})
        elif text or label:
            fact = f"{label}: {text}" if label and text else text or label
            if fact not in facts:
                facts.append(fact)
    return {
        "name": _text(basics.get("name")) or _text(basics.get("fullName")),
        "headline": _text(basics.get("headline")),
        "email": _text(basics.get("email")),
        "phone": _text(basics.get("phone")),
        "location": _text(basics.get("location")),
        "website": _safe_url(basics.get("website")),
        "facts": facts,
        "links": links,
    }


# A resume's usual reading order (the portfolio's); other sections follow it
# as the resume lists them, then the custom ones.
_SECTION_ORDER = (
    "experience",
    "education",
    "skills",
    "languages",
    "certifications",
    "certificates",
    "projects",
    "volunteer",
    "volunteering",
    "awards",
    "publications",
    "references",
    "interests",
    "profiles",
)


def resume_view(resume: Dict[str, Any]) -> Dict[str, Any]:
    """A resume as the page shows it: basics, summary, visible sections."""
    data: Dict[str, Any] = resume.get("data") or {}
    raw_sections = data.get("sections")
    sections_in: Dict[str, Any] = raw_sections if isinstance(raw_sections, dict) else {}
    summary = data.get("summary")
    if not isinstance(summary, dict):
        summary = sections_in.get("summary")  # where v4 kept it
    summary_text = (
        html_to_text(summary.get("content"))
        if isinstance(summary, dict) and not summary.get("hidden")
        else ""
    )

    keys = [k for k in _SECTION_ORDER if k in sections_in] + [
        k for k in sections_in if k not in _SECTION_ORDER and k != "summary"
    ]
    sections = [s for s in (_section(k, sections_in[k], k) for k in keys) if s]
    for i, custom in enumerate(data.get("customSections") or []):
        if isinstance(custom, dict):
            key = f"custom:{_text(custom.get('id')) or i}"
            shown = _section(key, custom, _text(custom.get("type")))
            if shown:
                sections.append(shown)

    return {
        "id": _text(resume.get("id")),
        "name": _text(resume.get("name")) or _text(resume.get("slug")) or "Untitled",
        "slug": _text(resume.get("slug")),
        "updated_at": _text(resume.get("updatedAt")) or None,
        "is_public": bool(resume.get("isPublic")),
        "basics": _basics(data),
        "summary": summary_text,
        "sections": sections,
    }
