"""Authentication routes: local email/password login, logout, current user, and
single sign-on (Infomaniak, GitHub) — login, account linking and callback."""

import logging
import time
from datetime import datetime, timezone
from typing import Annotated, List, Optional
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from server.core.config import config
from server.core.database import get_db
from server.core.i18n import translate_message
from server.auth import admin_secrets, hf_token
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
from server.services.sso import (
    ExternalIdentity,
    SsoError,
    SsoProvider,
    get_client,
    list_providers,
)
from server.services.sso import get_provider as get_sso_provider
from server.services.rate_limit import (
    admin_login_rate_limiter,
    hf_login_rate_limiter,
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
    email: Optional[str] = None
    name: str = Field(description="The HF username, else the email")
    role: str
    provider: str
    hf_username: Optional[str] = None
    hf_avatar_url: Optional[str] = None

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            name=user.display_name,
            role=user.role,
            provider=user.provider,
            hf_username=user.hf_username,
            hf_avatar_url=user.hf_avatar_url,
        )


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
    """Issue the access JWT + a fresh refresh-token family for ``user``.

    Called by the sign-ins only (password, SSO callback): the access token is
    dated with the sign-in time, which a refresh never copies.
    """
    _set_auth_cookie(response, create_access_token(user, auth_time=int(time.time())))
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


class HfLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=96)
    token: str = Field(..., min_length=1, max_length=hf_token.TOKEN_MAX_CHARS + 16)


class SignInRefusal(BaseModel):
    """Why a sign-in was refused: ``code`` for the login page, ``detail`` in
    the request's language."""

    code: str
    detail: str


def _refused(code: str, detail: str, status_code: int, **headers: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "detail": translate_message(detail)},
        headers=headers or None,
    )


@router.post(
    "/hf",
    response_model=UserResponse,
    responses={
        401: {"model": SignInRefusal},
        403: {"model": SignInRefusal},
        429: {"model": SignInRefusal},
        503: {"model": SignInRefusal},
    },
)
def hf_login(
    body: HfLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse | JSONResponse:
    """Sign in with a Hugging Face username and token (auth/hf_token.py).

    The token is checked with the Hub's ``whoami``: it must belong to that
    username and be able to write to its namespace. The first sign-in creates
    the account (if the sign-up policy allows it); the token is stored
    encrypted, never returned. 10 failures a minute per IP or per username,
    then 429.
    """
    ip = _client_ip(request)
    user_key = "user:" + body.username.strip().lower()
    wait = max(
        hf_login_rate_limiter.retry_after(ip),
        hf_login_rate_limiter.retry_after(user_key),
    )
    if wait > 0:
        return _refused(
            "rate_limited",
            "Too many failed login attempts. Please try again later.",
            status.HTTP_429_TOO_MANY_REQUESTS,
            **{"Retry-After": str(int(wait) + 1)},
        )
    try:
        user = hf_token.sign_in(db, body.username, body.token, ip=ip)
    except hf_token.HubUnavailable:
        return _refused(
            "hub_unavailable",
            "Hugging Face could not be reached. Try again in a moment.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except hf_token.SignInRefused as exc:
        hf_login_rate_limiter.register_failure(ip)
        hf_login_rate_limiter.register_failure(user_key)
        audit.record(db, "user.login.hf_refused", ip=ip, detail={"code": exc.code})
        return _refused(exc.code, exc.message, exc.status)
    hf_login_rate_limiter.reset(ip)
    hf_login_rate_limiter.reset(user_key)
    _set_session_cookies(response, db, user)
    return UserResponse.from_user(user)


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=1024)
    otp: Optional[str] = Field(
        None, max_length=16, description="The authenticator code, when TOTP is on"
    )


# One message for every failure: it must not say which value was wrong.
_ADMIN_LOGIN_FAILED = "Incorrect username, password or code"


@router.post("/admin/login", response_model=UserResponse)
def admin_login(
    body: AdminLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    """The admin's sign-in, checked against the deployment's secrets only
    (auth/admin_secrets.py). 5 failures a minute per client IP, then 429; every
    attempt is audited, never with the submitted values."""
    if not admin_secrets.configured():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin sign-in is not configured",
        )
    ip = _client_ip(request)
    retry_after = admin_login_rate_limiter.retry_after(ip)
    if retry_after > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    if not admin_secrets.verify_admin(body.username, body.password, body.otp):
        admin_login_rate_limiter.register_failure(ip)
        audit.record(db, "admin.login.failure", ip=ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_ADMIN_LOGIN_FAILED
        )
    admin_login_rate_limiter.reset(ip)
    admin = admin_secrets.ensure_admin_account(db)
    if admin is None:  # pragma: no cover — configured() was checked above
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    admin.last_login_at = datetime.now(timezone.utc)
    audit.record(db, "admin.login.success", actor=admin, target=admin, ip=ip)
    _set_session_cookies(response, db, admin)
    return UserResponse.from_user(admin)


def _clear_session_cookies(response: Response) -> None:
    """Delete both auth cookies (sign-out, or a session that can't be renewed)."""
    for cookie_name in (config.auth_cookie_name, config.auth_refresh_cookie_name):
        response.delete_cookie(
            key=cookie_name,
            path="/",
            httponly=True,
            secure=config.auth_cookie_secure,
            samesite="lax",
        )


@router.post("/refresh", response_model=UserResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse | JSONResponse:
    """Exchange the refresh cookie for a new access token + refresh token.

    Rotation: the presented refresh token is revoked and replaced. A missing,
    expired, or replayed token yields a 401 (replay additionally revokes the
    whole token family — see ``rotate_refresh_token``).
    """
    _throttle(refresh_rate_limiter, _client_ip(request), "Too many refresh attempts.")
    raw = request.cookies.get(config.auth_refresh_cookie_name)
    rotated = rotate_refresh_token(db, raw) if raw else None
    if not rotated:
        # The session can't be renewed: drop its cookies, or the browser keeps
        # presenting them and the web app takes it for still signed in.
        refused = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": translate_message("Invalid or expired refresh token")},
        )
        _clear_session_cookies(refused)
        return refused
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
    _clear_session_cookies(response)
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
    admin_totp: bool = Field(
        False, description="The admin sign-in (/admin/login) asks for a TOTP code"
    )


@router.get("/providers", response_model=ProvidersResponse)
def providers() -> ProvidersResponse:
    """The sign-in methods this deployment offers."""
    return ProvidersResponse(
        providers=[ProviderInfo(**p) for p in list_providers()],
        local_login=config.enable_local_login,
        signup_open=platform.signup_possible(),
        admin_totp=admin_secrets.totp_enabled(),
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
# Where a sign-in goes back to: the login page's `?from=`, kept through the
# provider's round trip.
_RETURN_SESSION_KEY = "sso_return_to"
_RETURN_PATH_MAX_CHARS = 2048


def _return_path(value: Optional[str]) -> Optional[str]:
    """``value`` when it is a path on the front-end's own origin, else None.

    The SSO twin of the login page's ``safeRedirectPath``
    (apps/next/lib/safe-redirect.ts): a prefix check is not enough, so the path
    is resolved first and must still start with a single slash (dot segments
    can rebuild a ``//host`` prefix, which a browser reads as a host), and
    backslashes and control characters, which browsers rewrite, are refused
    outright. What comes back is the resolved path.
    """
    if not value or len(value) > _RETURN_PATH_MAX_CHARS or not value.startswith("/"):
        return None
    if "\\" in value or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        return None
    parts = urlsplit(urljoin("https://app.invalid/", value))
    if parts.netloc != "app.invalid" or parts.path.startswith("//"):
        return None
    return urlunsplit(("", "", parts.path, parts.query, parts.fragment))


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


def _failed(error_page: str, code: str, back_to: Optional[str]) -> RedirectResponse:
    """Back to the page that started the flow, saying why — and still headed
    where the sign-in was going, so the next attempt lands there too."""
    params = {"error": code}
    if back_to:
        params["from"] = back_to
    return _front(error_page, **params)


async def _start(request: Request, provider: SsoProvider) -> Response:
    await run_in_threadpool(
        _throttle, sso_rate_limiter, _client_ip(request), "Too many sign-in attempts."
    )
    client = get_client(provider)
    return await client.authorize_redirect(request, provider.redirect_uri())


# The Infomaniak routes registered before GitHub existed — kept so an already
# configured redirect URI (/auth/oidc/callback) keeps working. Declared before the
# /{provider_name}/… routes, which would otherwise capture "oidc".
@router.get("/oidc/login", include_in_schema=False)
async def oidc_login(request: Request):
    return await sso_login("infomaniak", request)


@router.get("/oidc/callback", include_in_schema=False)
async def oidc_callback(request: Request, db: Session = Depends(get_db)):
    return await sso_callback("infomaniak", request, db)


@router.get("/{provider_name}/login")
async def sso_login(
    provider_name: str,
    request: Request,
    from_: Annotated[
        Optional[str],
        Query(
            alias="from",
            description="A path of the app to land on once signed in; anything "
            "else lands on the dashboard",
        ),
    ] = None,
):
    """Send the browser to the provider (state + PKCE kept in the session cookie)."""
    provider = _provider_or_404(provider_name)
    request.session.pop(_LINK_SESSION_KEY, None)
    back_to = _return_path(from_)
    if back_to:
        request.session[_RETURN_SESSION_KEY] = back_to
    else:
        # An earlier, abandoned sign-in's destination never carries over.
        request.session.pop(_RETURN_SESSION_KEY, None)
    return await _start(request, provider)


@router.get("/{provider_name}/link")
async def sso_link(
    provider_name: str, request: Request, current_user: User = Depends(get_current_user)
):
    """Like login, but the identity is added to the signed-in account."""
    provider = _provider_or_404(provider_name)
    request.session[_LINK_SESSION_KEY] = current_user.id
    request.session.pop(_RETURN_SESSION_KEY, None)
    return await _start(request, provider)


def _sign_in(
    db: Session,
    ext: ExternalIdentity,
    link_user_id: Optional[str],
    error_page: str,
    back_to: Optional[str],
    ip: str,
    provider_name: str,
) -> Response:
    """The database half of a callback (account resolution, session rows):
    blocking, so :func:`_callback` runs it in the threadpool."""
    link_to = db.get(User, link_user_id) if link_user_id else None
    if link_user_id and (link_to is None or not link_to.is_active):
        return _front("/login", error="session_expired")
    try:
        user = resolve_login(db, ext, link_to=link_to, ip=ip)
    except LoginRefused as exc:
        return _failed(error_page, exc.code, back_to)

    redirect = (
        _front("/settings", linked=provider_name)
        if link_to
        else _front(back_to or "/dashboard")
    )
    _set_session_cookies(redirect, db, user)
    return redirect


async def _callback(request: Request, provider: SsoProvider, db: Session) -> Response:
    link_user_id = request.session.pop(_LINK_SESSION_KEY, None)
    back_to = _return_path(request.session.pop(_RETURN_SESSION_KEY, None))
    error_page = "/settings" if link_user_id else "/login"
    client = get_client(provider)
    try:
        token = await client.authorize_access_token(request)
        ext = await provider.identity(client, token)
    except SsoError as exc:
        return _failed(error_page, exc.code, back_to)
    except Exception as exc:  # noqa: BLE001 — a bad/replayed/forged flow
        logging.warning("%s sign-in failed: %s", provider.name, type(exc).__name__)
        return _failed(error_page, "sso_failed", back_to)

    return await run_in_threadpool(
        _sign_in,
        db,
        ext,
        link_user_id,
        error_page,
        back_to,
        _client_ip(request),
        provider.name,
    )


@router.get("/{provider_name}/callback")
async def sso_callback(
    provider_name: str, request: Request, db: Session = Depends(get_db)
):
    """The provider's redirect: resolve the account (services/identities.py),
    set the session cookies, go back to the app."""
    return await _callback(request, _provider_or_404(provider_name), db)
