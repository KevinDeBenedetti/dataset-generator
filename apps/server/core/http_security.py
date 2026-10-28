"""HTTP hardening middlewares: security headers, a CSRF Origin check and a
request body ceiling.

Pure ASGI (not ``BaseHTTPMiddleware``) so streamed responses — the dev log
console's SSE — pass through untouched.
"""

import json
import re
from typing import Any, Awaitable, Callable, Iterable, Optional
from urllib.parse import urlsplit

from starlette.exceptions import HTTPException

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _header(scope: Scope, name: bytes) -> Optional[str]:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


async def _send_json(send: Send, status: int, payload: dict) -> None:
    """A complete JSON answer, for a middleware that refuses the request."""
    body = json.dumps(payload).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    """Adds the response headers every API answer should carry.

    ``Cache-Control: no-store`` on ``/auth/*`` and ``/me/*`` keeps sessions and
    secrets-adjacent answers out of shared caches. Existing headers are never
    overwritten, so a route can opt out.
    """

    def __init__(self, app: Any, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        no_store = path.startswith(("/auth", "/me"))

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"content-security-policy", b"frame-ancestors 'none'"),
                ]
                if self.hsts:
                    extra.append(
                        (
                            b"strict-transport-security",
                            b"max-age=63072000; includeSubDomains",
                        )
                    )
                if no_store:
                    extra.append((b"cache-control", b"no-store"))
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        *[h for h in extra if h[0] not in present],
                    ],
                }
            await send(message)

        await self.app(scope, receive, send_with_headers)


class OriginCheckMiddleware:
    """Rejects state-changing requests that come from a foreign browser origin.

    Cookie auth means a page on another site can make the browser send the
    session with a form or fetch; ``SameSite=Lax`` already blocks most of that
    and this closes the rest (same-site sibling hosts, ``Origin: null`` from
    sandboxed frames). Browsers always attach ``Origin`` to cross-origin and to
    unsafe same-origin requests, so a request carrying one is allowed only when
    it names an allowed origin or the host being addressed. A request without
    ``Origin`` (curl, the CI, server-to-server with a Bearer token) is not a
    browser-driven CSRF vector and passes.
    """

    def __init__(
        self,
        app: Any,
        allowed_origins: Iterable[str] = (),
        allowed_origin_regex: Optional[str] = None,
    ) -> None:
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in allowed_origins if o}
        self.regex = re.compile(allowed_origin_regex) if allowed_origin_regex else None

    def _allowed(self, origin: str, host: Optional[str]) -> bool:
        normalized = origin.rstrip("/").lower()
        if normalized in self.allowed:
            return True
        if self.regex and self.regex.fullmatch(origin):
            return True
        # Same origin: the page was served by the very host being addressed.
        # (Behind a proxy the Host header is preserved by the ingress.)
        return bool(host) and urlsplit(origin).netloc.lower() == (host or "").lower()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            origin = _header(scope, b"origin")
            if origin is not None and not self._allowed(
                origin, _header(scope, b"host")
            ):
                await _send_json(send, 403, {"detail": "Origin not allowed"})
                return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Refuses request bodies larger than ``max_body_bytes`` with a 413.

    Uvicorn accepts a body of any size, so without this one request could fill
    the memory (an upload is read whole) or the disk (multipart spooling). A
    declared ``Content-Length`` over the limit is answered before the app
    runs; a body sent without one (chunked) is counted as it arrives and
    ``receive()`` raises a 413 ``HTTPException`` at the limit, which FastAPI
    re-raises from body parsing and turns into the response.
    """

    def __init__(self, app: Any, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self._detail = f"Request body too large (over {max_body_bytes} bytes)"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _header(scope, b"content-length")
        if declared is not None and declared.isdigit():
            if int(declared) > self.max_body_bytes:
                await _send_json(send, 413, {"detail": self._detail})
                return

        received = 0

        async def limited_receive() -> dict:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise HTTPException(status_code=413, detail=self._detail)
            return message

        await self.app(scope, limited_receive, send)
