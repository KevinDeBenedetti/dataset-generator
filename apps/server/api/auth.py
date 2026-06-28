"""Authentication routes: local email/password login, logout, current user,
plus the OIDC (Infomaniak) login + callback flow."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from server.core.config import config
from server.core.database import get_db
from server.models.user import User
from server.services.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
)
from server.services.oidc import (
    PROVIDER_NAME,
    get_oauth,
    is_oidc_configured,
    upsert_oidc_user,
)
from server.services.rate_limit import login_rate_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    """Best-effort client IP for rate-limiting.

    Honours the first ``X-Forwarded-For`` hop when present (the app typically
    runs behind a reverse proxy), else falls back to the socket peer.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


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
    token = create_access_token(user)
    _set_auth_cookie(response, token)
    return UserResponse.from_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    """Clear the auth cookie."""
    response.delete_cookie(
        key=config.auth_cookie_name,
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


def _claim_is_true(value: object) -> bool:
    """Coerce an OIDC claim to a bool.

    The spec says ``email_verified`` is a JSON boolean, but some providers send
    the string ``"true"``. Accept both; anything else is treated as not verified.
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1")


def _require_oidc() -> None:
    if not is_oidc_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC is not configured. Set OIDC_ISSUER, OIDC_CLIENT_ID and "
            "OIDC_CLIENT_SECRET in your .env.",
        )


@router.get("/oidc/login")
async def oidc_login(request: Request):
    """Redirect the browser to the Infomaniak authorization endpoint."""
    _require_oidc()
    client = get_oauth().create_client(PROVIDER_NAME)
    return await client.authorize_redirect(request, config.oidc_redirect_uri)


@router.get("/oidc/callback")
async def oidc_callback(request: Request, db: Session = Depends(get_db)):
    """Handle the provider redirect: exchange the code, upsert the user, set
    the auth cookie, then bounce back to the frontend."""
    _require_oidc()
    client = get_oauth().create_client(PROVIDER_NAME)
    try:
        token = await client.authorize_access_token(request)
    except Exception as exc:  # noqa: BLE001 — surface a clean 400 on a bad flow
        logging.warning("OIDC token exchange failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OIDC authentication failed",
        )

    userinfo = token.get("userinfo") or {}
    sub = userinfo.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OIDC response did not include a subject identifier",
        )

    user = upsert_oidc_user(
        db,
        sub=sub,
        email=userinfo.get("email", ""),
        email_verified=_claim_is_true(userinfo.get("email_verified")),
    )
    access_token = create_access_token(user)
    redirect = RedirectResponse(url=config.frontend_url, status_code=302)
    _set_auth_cookie(redirect, access_token)
    return redirect
