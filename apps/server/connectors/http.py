"""HTTP for the connectors: JSON and file downloads through the outbound guard.

Every request goes through ``core/net.py``'s pinned client (https, public
addresses only, no redirect followed blindly). A redirect is followed by hand,
each hop checked again, at most ``MAX_REDIRECTS``, and only to the hosts a
connector allows. A download is streamed to disk and stopped at its byte
limit. Rate limits (429) are retried after ``Retry-After`` (bounded), then
reported; an unreachable server becomes a :class:`ConnectorError` the user
can act on.
"""

import asyncio
import email.utils
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx2

from server.connectors.base import ConnectorError
from server.core.net import pinned_client

MAX_REDIRECTS = 5
MAX_RETRIES = 3
# The longest Retry-After honoured before giving up.
MAX_WAIT_S = 30.0
USER_AGENT = (
    "dataset-generator (+https://github.com/KevinDeBenedetti/dataset-generator)"
)

# Builds the client; tests swap it for one on an httpx2.MockTransport.
ClientFactory = Callable[[Optional[Iterable[str]]], httpx2.AsyncClient]


def _default_factory(allowed_hosts: Optional[Iterable[str]]) -> httpx2.AsyncClient:
    return pinned_client(
        timeout=60.0,
        allowed_hosts=allowed_hosts,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )


client_factory: ClientFactory = _default_factory


def _retry_after(response: httpx2.Response, attempt: int) -> float:
    raw = response.headers.get("Retry-After", "")
    wait: Optional[float] = None
    if raw.isdigit():
        wait = float(raw)
    elif raw:
        try:
            when = email.utils.parsedate_to_datetime(raw)
            wait = when.timestamp() - time.time()
        except (TypeError, ValueError):
            wait = None
    if wait is None:
        wait = 2.0**attempt
    return max(0.0, wait)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


async def _send(
    client: httpx2.AsyncClient,
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    allowed_hosts: Optional[Iterable[str]] = None,
    redirect_ok: Optional[Callable[[str, str], bool]] = None,
    stream: bool = False,
    what: str = "the server",
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> httpx2.Response:
    """One request, its redirects and its rate-limit retries. A redirect goes
    to ``allowed_hosts`` only, or where ``redirect_ok(from_url, to_url)`` says."""
    allowed = {h.lower() for h in allowed_hosts} if allowed_hosts is not None else None
    current, query = url, params
    for attempt in range(MAX_RETRIES + 1):
        hops = 0
        while True:
            if allowed is not None and _host(current) not in allowed:
                raise ConnectorError(
                    f"{_host(current) or current} is not a host this data source may "
                    "reach"
                )
            try:
                request = client.build_request(
                    method, current, params=query, headers=headers
                )
                response = await client.send(request, stream=stream)
            except httpx2.TimeoutException:
                raise ConnectorError(f"{what} took too long to answer") from None
            except httpx2.ConnectError as exc:
                reason = str(exc)
                # The outbound guard's own refusals say why: pass them on.
                if any(
                    word in reason
                    for word in ("non-public", "not an allowed host", "Only https")
                ):
                    raise ConnectorError(reason) from None
                raise ConnectorError(
                    f"{what} could not be reached ({exc.__class__.__name__})"
                ) from None
            except httpx2.HTTPError as exc:
                raise ConnectorError(
                    f"{what} could not be reached ({exc.__class__.__name__})"
                ) from None
            if response.is_redirect and response.headers.get("Location"):
                hops += 1
                if hops > MAX_REDIRECTS:
                    await response.aclose()
                    raise ConnectorError(f"{what} redirected too many times")
                target = urljoin(current, response.headers["Location"])
                await response.aclose()
                if redirect_ok is not None and not redirect_ok(current, target):
                    raise ConnectorError(
                        f"{what} redirected to {_host(target) or target}, another site: "
                        "refusing to follow"
                    )
                current, query = target, None
                continue
            break
        if response.status_code in (429, 503) and attempt < MAX_RETRIES:
            wait = _retry_after(response, attempt)
            await response.aclose()
            if wait > MAX_WAIT_S:
                raise ConnectorError(
                    f"{what} limits how often it is asked: try again in {int(wait)} s"
                )
            await sleep(wait)
            current, query = url, params
            continue
        if response.status_code in (429, 503):
            await response.aclose()
            raise ConnectorError(
                f"{what} limits how often it is asked: try again later"
            )
        if response.status_code >= 500 and attempt < 1:
            await response.aclose()
            await sleep(1.0)
            current, query = url, params
            continue
        return response
    raise ConnectorError(f"{what} could not be reached")  # pragma: no cover


async def get_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    allowed_hosts: Optional[Iterable[str]] = None,
    what: str = "the server",
    max_bytes: int = 20 * 1024 * 1024,
    redirect_ok: Optional[Callable[[str, str], bool]] = None,
) -> Tuple[Any, httpx2.Headers]:
    """A JSON document and the response's headers."""
    async with client_factory(allowed_hosts) as client:
        response = await _send(
            client,
            "GET",
            url,
            params=params,
            headers={"Accept": "application/json", **(headers or {})},
            allowed_hosts=allowed_hosts,
            redirect_ok=redirect_ok,
            what=what,
        )
        if response.status_code == 404:
            raise ConnectorError(f"{what} has no such resource (404)")
        if response.status_code in (401, 403):
            raise ConnectorError(f"{what} refused the request ({response.status_code})")
        if response.status_code >= 400:
            raise ConnectorError(f"{what} answered HTTP {response.status_code}")
        body = response.content
        if len(body) > max_bytes:
            raise ConnectorError(f"{what} answered more than {max_bytes // 1024**2} MB")
        try:
            return response.json(), response.headers
        except ValueError:
            raise ConnectorError(f"{what} did not answer JSON") from None


async def download(
    url: str,
    dest: Path,
    *,
    max_bytes: int,
    headers: Optional[Dict[str, str]] = None,
    allowed_hosts: Optional[Iterable[str]] = None,
    what: str = "the server",
    redirect_ok: Optional[Callable[[str, str], bool]] = None,
) -> Tuple[Path, httpx2.Headers]:
    """Stream ``url`` into ``dest``; stops (and removes it) past ``max_bytes``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with client_factory(allowed_hosts) as client:
        response = await _send(
            client,
            "GET",
            url,
            headers=headers,
            allowed_hosts=allowed_hosts,
            redirect_ok=redirect_ok,
            stream=True,
            what=what,
        )
        try:
            if response.status_code == 404:
                raise ConnectorError(f"{what}: the file is gone (404)")
            if response.status_code >= 400:
                raise ConnectorError(f"{what} answered HTTP {response.status_code}")
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise ConnectorError(
                    f"The file is larger than {max_bytes // 1024**2} MB"
                )
            written = 0
            with dest.open("wb") as out:
                async for chunk in response.aiter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        raise ConnectorError(
                            f"The file is larger than {max_bytes // 1024**2} MB"
                        )
                    out.write(chunk)
        except BaseException:
            await asyncio.to_thread(dest.unlink, missing_ok=True)
            raise
        finally:
            await response.aclose()
        return dest, response.headers


async def head(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    what: str = "the server",
    redirect_ok: Optional[Callable[[str, str], bool]] = None,
) -> Tuple[int, httpx2.Headers]:
    """A HEAD request's status and headers (a conditional one when ``headers``
    carry ``If-None-Match`` / ``If-Modified-Since``)."""
    async with client_factory(None) as client:
        response = await _send(
            client, "HEAD", url, headers=headers, redirect_ok=redirect_ok, what=what
        )
        await response.aclose()
        return response.status_code, response.headers


# Two-level public suffixes: a host under one belongs to its third label.
_MULTI_SUFFIXES = {
    "gouv.fr",
    "asso.fr",
    "com.fr",
    "nom.fr",
    "presse.fr",
    "tm.fr",
    "co.uk",
    "org.uk",
    "gov.uk",
    "ac.uk",
    "com.au",
    "gov.au",
    "co.jp",
    "europa.eu",
}


def registrable_domain(host: str) -> str:
    """``data.example.gouv.fr`` → ``example.gouv.fr``; ``a.b.example.org`` →
    ``example.org`` (a short list of two-level suffixes, not the whole PSL)."""
    labels = [label for label in host.lower().rstrip(".").split(".") if label]
    if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTI_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_site(from_url: str, to_url: str) -> bool:
    """A redirect that stays on https and on the same registrable domain."""
    if urlsplit(to_url).scheme.lower() != "https":
        return False
    return registrable_domain(_host(from_url)) == registrable_domain(_host(to_url))
