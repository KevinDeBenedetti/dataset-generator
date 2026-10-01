"""Authentication routes: local email/password login, logout, current user, and
single sign-on (Infomaniak, GitHub) — login, account linking and callback."""

import logging
from datetime import datetime, timezone
from typing import List
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from server.core.config import config
from server.core.database import get_db
from server.models.user import User
from server.services.auth import (
    authenticate_user,
    end_all_sessions,
    create_access_token,
    get_current_user,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from server.services import audit, platform
from server.services.identities import LoginRefused, resolve_login
from server.services.sso import SsoError, SsoProvider, get_client, list_providers
from server.services.sso import get_provider as get_sso_provider
from server.services.rate_limit import (
    login_rate_limiter,
    refresh_rate_limiter,
    sso_rate_limiter,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    """Client IP for rate-limiting.

    Never read ``X-Forwarded-For`` here: any caller can set it, so a fresh value
    per attempt would bypass the limiter. Uvicorn already rewrites
    ``request.client`` from that header, but only when the direct peer is listed
    in ``FORWARDED_ALLOW_IPS`` — set that to the reverse proxy's address.
    """
    return request.client.host if request.client else "unknown"


def _throttle(limiter, ip: str, detail: str) -> None:
    """Count one request from ``ip`` against ``limiter``; 429 once over budget.

    For the limiters that count every call (refresh, SSO start) rather than
    only failures. Runs the (possibly Redis-backed) limiter — call it from a
    worker thread, see ``RedisRateLimiter``.
    """
    retry_after = limiter.retry_after(ip)
    if retry_after > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    limiter.register_failure(ip)


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Account email")
    password: str = Field(..., min_length=1, description="Account password")


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    provider: str

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(id=user.id, email=user.email, role=user.role, provider=user.provider)


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.auth_cookie_name,
        value=token,
        httponly=True,
        secure=config.auth_cookie_secure,
        samesite="lax",
        max_age=config.auth_token_ttl_seconds,
        path="/",
    )


# The refresh cookie is scoped to "/" (not just /auth/refresh) on purpose: the
# Next.js middleware gates routes on cookie *presence*, and the access cookie
# vanishes when its short max_age lapses — the refresh cookie is what tells the
# middleware the session is still renewable.
def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.auth_refresh_cookie_name,
        value=token,
        httponly=True,
        secure=config.auth_cookie_secure,
        samesite="lax",
        max_age=config.auth_refresh_token_ttl_seconds,
        path="/",
    )


def _set_session_cookies(response: Response, db: Session, user: User) -> None:
    """Issue the access JWT + a fresh refresh-token family for ``user``."""
    _set_auth_cookie(response, create_access_token(user))
    _set_refresh_cookie(response, issue_refresh_token(db, user))


@router.post("/login", response_model=UserResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Validate credentials, set the httpOnly auth cookie, return the user.

    Throttled per client IP: too many failed attempts within the window yield a
    429 (anti-brute-force). A successful login clears the counter.
    """
    if not config.enable_local_login:
        # Production accounts sign in through SSO; there is no password to guess.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Local login is disabled"
        )
    ip = _client_ip(request)
    retry_after = login_rate_limiter.retry_after(ip)
    if retry_after > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    user = authenticate_user(db, body.email, body.password)
    if not user:
        login_rate_limiter.register_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    login_rate_limiter.reset(ip)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    _set_session_cookies(response, db, user)
    return UserResponse.from_user(user)


@router.post("/refresh", response_model=UserResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Exchange the refresh cookie for a new access token + refresh token.

    Rotation: the presented refresh token is revoked and replaced. A missing,
    expired, or replayed token yields a 401 (replay additionally revokes the
    whole token family — see ``rotate_refresh_token``).
    """
    _throttle(refresh_rate_limiter, _client_ip(request), "Too many refresh attempts.")
    raw = request.cookies.get(config.auth_refresh_cookie_name)
    rotated = rotate_refresh_token(db, raw) if raw else None
    if not rotated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    user, new_refresh = rotated
    _set_auth_cookie(response, create_access_token(user))
    _set_refresh_cookie(response, new_refresh)
    return UserResponse.from_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Response:
    """Revoke the refresh-token family and clear both auth cookies."""
    raw = request.cookies.get(config.auth_refresh_cookie_name)
    if raw:
        revoke_refresh_token(db, raw)
    for cookie_name in (config.auth_cookie_name, config.auth_refresh_cookie_name):
        response.delete_cookie(
            key=cookie_name,
            path="/",
            httponly=True,
            secure=config.auth_cookie_secure,
            samesite="lax",
        )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the currently authenticated user."""
    return UserResponse.from_user(current_user)


class ProviderInfo(BaseModel):
    name: str
    label: str
    configured: bool


class ProvidersResponse(BaseModel):
    """What the login page can offer — no secrets, just switches."""

    providers: List[ProviderInfo]
    local_login: bool
    signup_open: bool


@router.get("/providers", response_model=ProvidersResponse)
def providers() -> ProvidersResponse:
    """The sign-in methods this deployment offers."""
    return ProvidersResponse(
        providers=[ProviderInfo(**p) for p in list_providers()],
        local_login=config.enable_local_login,
        signup_open=platform.allow_signup(),
    )


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Sign out on every device: all refresh tokens revoked, all access tokens
    issued so far refused."""
    end_all_sessions(db, current_user)
    audit.record(
        db,
        "sessions.ended",
        actor=current_user,
        target=current_user,
        ip=_client_ip(request),
    )
    return logout(request, response, db)


_LINK_SESSION_KEY = "sso_link_user"


def _provider_or_404(name: str) -> SsoProvider:
    provider = get_sso_provider(name)
    if provider is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown sign-in provider '{name}'"
        )
    if not provider.configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider.label} sign-in is not configured on this server.",
        )
    return provider


def _front(path: str, **params: str) -> RedirectResponse:
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(
        url=f"{config.frontend_url.rstrip('/')}{path}{query}", status_code=302
    )


async def _start(request: Request, provider: SsoProvider) -> Response:
    await run_in_threadpool(
        _throttle, sso_rate_limiter, _client_ip(request), "Too many sign-in attempts."
    )
    client = get_client(provider)
    return await client.authorize_redirect(request, provider.redirect_uri())


# The Infomaniak routes registered before GitHub existed — kept so an already
# configured OIDC_REDIRECT_URI keeps working. Declared before the
# /{provider_name}/… routes, which would otherwise capture "oidc".
@router.get("/oidc/login", include_in_schema=False)
async def oidc_login(request: Request):
    return await sso_login("infomaniak", request)


@router.get("/oidc/callback", include_in_schema=False)
async def oidc_callback(request: Request, db: Session = Depends(get_db)):
    return await sso_callback("infomaniak", request, db)


@router.get("/{provider_name}/login")
async def sso_login(provider_name: str, request: Request):
    """Send the browser to the provider (state + PKCE kept in the session cookie)."""
    provider = _provider_or_404(provider_name)
    request.session.pop(_LINK_SESSION_KEY, None)
    return await _start(request, provider)


@router.get("/{provider_name}/link")
async def sso_link(
    provider_name: str, request: Request, current_user: User = Depends(get_current_user)
):
    """Like login, but the identity is added to the signed-in account."""
    provider = _provider_or_404(provider_name)
    request.session[_LINK_SESSION_KEY] = current_user.id
    return await _start(request, provider)


async def _callback(request: Request, provider: SsoProvider, db: Session) -> Response:
    link_user_id = request.session.pop(_LINK_SESSION_KEY, None)
    error_page = "/settings" if link_user_id else "/login"
    client = get_client(provider)
    try:
        token = await client.authorize_access_token(request)
        ext = await provider.identity(client, token)
    except SsoError as exc:
        return _front(error_page, error=exc.code)
    except Exception as exc:  # noqa: BLE001 — a bad/replayed/forged flow
        logging.warning("%s sign-in failed: %s", provider.name, type(exc).__name__)
        return _front(error_page, error="sso_failed")

    link_to = db.get(User, link_user_id) if link_user_id else None
    if link_user_id and (link_to is None or not link_to.is_active):
        return _front("/login", error="session_expired")
    try:
        user = resolve_login(db, ext, link_to=link_to, ip=_client_ip(request))
    except LoginRefused as exc:
        return _front(error_page, error=exc.code)

    redirect = (
        _front("/settings", linked=provider.name) if link_to else _front("/dashboard")
    )
    _set_session_cookies(redirect, db, user)
    return redirect


@router.get("/{provider_name}/callback")
async def sso_callback(
    provider_name: str, request: Request, db: Session = Depends(get_db)
):
    """The provider's redirect: resolve the account (services/identities.py),
    set the session cookies, go back to the app."""
    return await _callback(request, _provider_or_404(provider_name), db)
