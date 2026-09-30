"""Fetch one web page and reduce it to text — the URL source of /generate.

Single page, no crawling. The server fetches a URL chosen by the user, so the
fetch refuses anything that resolves to a loopback, private, link-local or
otherwise non-public address (SSRF) — re-checked on every redirect hop — and
caps both the wait and the body size.
"""

import asyncio
import ipaddress
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urljoin, urlsplit

import httpx

TIMEOUT_S = 15.0
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/markdown")
_USER_AGENT = "DatasetGen/1.0 (+single-page fetch for Q&A dataset generation)"


class WebFetchError(ValueError):
    """The URL can't or mustn't be fetched; the message is safe to show."""


@dataclass
class Page:
    url: str
    body: str
    content_type: str

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type


async def _resolve(host: str, port: int) -> List[str]:
    """Every address ``host`` resolves to (a module function so tests can stub DNS)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port)
    return [str(info[4][0]) for info in infos]


async def _check_public(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise WebFetchError("Only http(s) URLs can be fetched")
    host = parts.hostname
    if not host:
        raise WebFetchError("The URL has no host")
    try:
        addresses = await _resolve(
            host, parts.port or (443 if parts.scheme == "https" else 80)
        )
    except OSError as exc:
        raise WebFetchError(f"Could not resolve {host}") from exc
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise WebFetchError(
                f"{host} resolves to a non-public address — refusing to fetch it"
            )


async def fetch_page(url: str, client: Optional[httpx.AsyncClient] = None) -> Page:
    """GET ``url`` (following up to :data:`MAX_REDIRECTS` checked redirects).

    Raises :class:`WebFetchError` for a refused/unreachable URL, a non-text
    content type, an HTTP error status or a body over :data:`MAX_BYTES`.
    """
    own = client is None
    client = client or httpx.AsyncClient(
        timeout=TIMEOUT_S, headers={"User-Agent": _USER_AGENT}
    )
    try:
        current = url.strip()
        for _ in range(MAX_REDIRECTS + 1):
            await _check_public(current)
            try:
                async with client.stream(
                    "GET", current, follow_redirects=False
                ) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        current = urljoin(current, resp.headers["location"])
                        continue
                    if resp.status_code >= 400:
                        raise WebFetchError(
                            f"{current} answered HTTP {resp.status_code}"
                        )
                    content_type = resp.headers.get("content-type", "").lower()
                    if not any(t in content_type for t in _TEXT_TYPES):
                        raise WebFetchError(
                            f"Unsupported content type '{content_type or 'unknown'}' "
                            "— only HTML and text pages can be used"
                        )
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise WebFetchError(
                                f"The page is larger than {MAX_BYTES // (1024 * 1024)} MB"
                            )
                    text = bytes(body).decode(
                        resp.encoding or "utf-8", errors="replace"
                    )
                    return Page(url=current, body=text, content_type=content_type)
            except httpx.HTTPError as exc:
                raise WebFetchError(f"Could not fetch {current}: {exc}") from exc
        raise WebFetchError(f"Too many redirects (over {MAX_REDIRECTS})")
    finally:
        if own:
            await client.aclose()


class _TextExtractor(HTMLParser):
    """Visible text of a page, headings kept as markdown ``#`` lines."""

    SKIP = {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
    }
    BLOCK = {
        "p",
        "div",
        "section",
        "article",
        "main",
        "li",
        "tr",
        "br",
        "pre",
        "blockquote",
        "dd",
        "dt",
        "table",
    }
    HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.HEADINGS and not self._skip:
            self.parts.append("\n\n" + "#" * self.HEADINGS[tag] + " ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.HEADINGS or tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Strip markup, scripts and page chrome; collapse whitespace."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
