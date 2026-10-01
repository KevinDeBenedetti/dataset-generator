"""Outbound-request guard (SSRF) for every URL a user can influence.

The server calls addresses chosen by users — a page to mine, an OpenAI-compatible
base URL — from inside a cluster where the interesting targets (cloud metadata,
the database, other pods) sit on private addresses. This module is the one place
that decides whether a destination is acceptable:

* only ``https`` (``http`` opt-in, for the page fetcher only);
* the host must resolve to **public** addresses only — loopback, RFC 1918,
  link-local (cloud metadata), CGNAT, ULA, multicast and IPv4-mapped forms of
  those are refused, as are ``localhost``/``*.internal``/``*.local``/cluster
  names before any DNS lookup;
* the connection is **pinned** to the address that was checked, so a DNS answer
  that changes between check and connect (rebinding) cannot redirect it;
* redirects are never followed by the transport — callers re-validate each hop.

Use :class:`PinnedTransport` for any ``httpx`` client, including the one handed
to the OpenAI SDK.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

import httpx

_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home.arpa",
    ".cluster.local",
    ".svc",
)


class UnsafeURLError(ValueError):
    """The destination is not allowed; the message is safe to show to the user."""


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    addresses: List[str]


async def resolve(host: str, port: int) -> List[str]:
    """Every address ``host`` resolves to (a module function so tests can stub DNS)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def resolve_sync(host: str, port: int) -> List[str]:
    return list(dict.fromkeys(str(i[4][0]) for i in socket.getaddrinfo(host, port)))


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:  # ::ffff:10.0.0.1 is 10.0.0.1
        ip = mapped
    return ip.is_global and not ip.is_multicast


def _bare_host(host: str) -> str:
    return host.strip().rstrip(".").lower()


def _prepare(
    host: Optional[str],
    scheme: str,
    allow_http: bool,
    allowed_hosts: Optional[Iterable[str]],
) -> tuple[str, Optional[List[str]]]:
    """The checks that need no DNS. Returns ``(name, literal_addresses_or_None)``."""
    if scheme not in (("https", "http") if allow_http else ("https",)):
        raise UnsafeURLError(
            "Only http(s) URLs are allowed"
            if allow_http
            else "Only https URLs are allowed"
        )
    if not host:
        raise UnsafeURLError("The URL has no host")
    name = _bare_host(host).strip("[]")
    if allowed_hosts is not None and name not in {h.lower() for h in allowed_hosts}:
        raise UnsafeURLError(f"{name} is not an allowed host")
    if name == "localhost" or name.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURLError(f"{name} is a non-public address — refusing to use it")
    try:
        ipaddress.ip_address(name)
        return name, [name]
    except ValueError:
        return name, None


def _finish(name: str, port: int, addresses: List[str]) -> Target:
    if not addresses:
        raise UnsafeURLError(f"Could not resolve {name}")
    if not all(is_public_address(a) for a in addresses):
        raise UnsafeURLError(
            f"{name} resolves to a non-public address — refusing to use it"
        )
    return Target(host=name, port=port, addresses=addresses)


async def check_target(
    host: Optional[str],
    port: int,
    scheme: str,
    *,
    allow_http: bool = False,
    allowed_hosts: Optional[Iterable[str]] = None,
) -> Target:
    """Validate ``scheme://host:port``; returns the resolved, all-public target."""
    name, literal = _prepare(host, scheme, allow_http, allowed_hosts)
    try:
        addresses = literal if literal is not None else await resolve(name, port)
    except OSError as exc:
        raise UnsafeURLError(f"Could not resolve {name}") from exc
    return _finish(name, port, addresses)


def check_target_sync(
    host: Optional[str],
    port: int,
    scheme: str,
    *,
    allow_http: bool = False,
    allowed_hosts: Optional[Iterable[str]] = None,
) -> Target:
    """:func:`check_target` for synchronous callers (embeddings run in threads)."""
    name, literal = _prepare(host, scheme, allow_http, allowed_hosts)
    try:
        addresses = literal if literal is not None else resolve_sync(name, port)
    except OSError as exc:
        raise UnsafeURLError(f"Could not resolve {name}") from exc
    return _finish(name, port, addresses)


async def check_url(
    url: str,
    *,
    allow_http: bool = False,
    allowed_hosts: Optional[Iterable[str]] = None,
) -> Target:
    parts = urlsplit(url.strip())
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("The URL has an invalid port") from exc
    scheme = parts.scheme.lower()
    return await check_target(
        parts.hostname,
        port or (443 if scheme == "https" else 80),
        scheme,
        allow_http=allow_http,
        allowed_hosts=allowed_hosts,
    )


class PinnedTransport(httpx.AsyncBaseTransport):
    """An httpx transport that only talks to a validated public address.

    Per request: resolve + validate the host, then connect to *that address*
    (Host header and TLS server name stay the original host, so certificates
    still verify). Redirects are the caller's business — build the client with
    ``follow_redirects=False`` and validate each hop through here.
    """

    def __init__(
        self,
        *,
        allow_http: bool = False,
        allowed_hosts: Optional[Iterable[str]] = None,
        inner: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._allow_http = allow_http
        self._allowed_hosts = list(allowed_hosts) if allowed_hosts is not None else None
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        try:
            target = await check_target(
                url.host,
                url.port or (443 if url.scheme == "https" else 80),
                url.scheme,
                allow_http=self._allow_http,
                allowed_hosts=self._allowed_hosts,
            )
        except UnsafeURLError as exc:
            # Surfaces through httpx as a transport error the callers already handle.
            raise httpx.ConnectError(str(exc), request=request) from exc
        request.url = url.copy_with(host=target.addresses[0])
        request.extensions = {**request.extensions, "sni_hostname": target.host}
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def pinned_client(
    *,
    timeout: float = 30.0,
    allow_http: bool = False,
    allowed_hosts: Optional[Iterable[str]] = None,
    headers: Optional[dict] = None,
) -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` behind :class:`PinnedTransport`, redirects off."""
    return httpx.AsyncClient(
        transport=PinnedTransport(allow_http=allow_http, allowed_hosts=allowed_hosts),
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
        trust_env=False,
    )


class SyncPinnedTransport(httpx.BaseTransport):
    """:class:`PinnedTransport` for a synchronous ``httpx.Client``."""

    def __init__(
        self,
        *,
        allow_http: bool = False,
        allowed_hosts: Optional[Iterable[str]] = None,
        inner: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._allow_http = allow_http
        self._allowed_hosts = list(allowed_hosts) if allowed_hosts is not None else None
        self._inner = inner or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        try:
            target = check_target_sync(
                url.host,
                url.port or (443 if url.scheme == "https" else 80),
                url.scheme,
                allow_http=self._allow_http,
                allowed_hosts=self._allowed_hosts,
            )
        except UnsafeURLError as exc:
            raise httpx.ConnectError(str(exc), request=request) from exc
        request.url = url.copy_with(host=target.addresses[0])
        request.extensions = {**request.extensions, "sni_hostname": target.host}
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def pinned_sync_client(
    *,
    timeout: float = 30.0,
    allow_http: bool = False,
    allowed_hosts: Optional[Iterable[str]] = None,
) -> httpx.Client:
    return httpx.Client(
        transport=SyncPinnedTransport(
            allow_http=allow_http, allowed_hosts=allowed_hosts
        ),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    )
