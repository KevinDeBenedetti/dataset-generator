"""The signed-in user's own integration keys and settings.

Secrets are write-only: they can be saved, replaced, tested and deleted, but no
route ever returns one. Responses carry ``Cache-Control: no-store``.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.core.database import get_db
from server.models.user import User
from server.schemas.me import (
    IdentitiesResponse,
    IdentityOut,
    SecretCheck,
    SecretPut,
    SecretPutResponse,
    SecretsResponse,
    SecretStatus,
    SettingsResponse,
    SettingsUpdate,
)
from server.services import identities, user_secrets
from server.services.auth import get_current_user
from server.core.config import config
from server.services.credentials import (
    ANTHROPIC_API_KEY,
    CLAUDE_TOKEN,
    SECRET_KINDS,
)
from server.services.providers.openai import check_base_url
from server.services.rate_limit import secrets_rate_limiter
from server.services.secret_validation import check_secret

router = APIRouter(prefix="/me", tags=["me"])
logger = logging.getLogger(__name__)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _available_kinds() -> list[str]:
    """Secret kinds this server can use (no Claude outside development/CI)."""
    if config.claude_provider_available:
        return list(SECRET_KINDS)
    return [k for k in SECRET_KINDS if k not in (CLAUDE_TOKEN, ANTHROPIC_API_KEY)]


def _kind(kind: str) -> str:
    if kind not in _available_kinds():
        raise HTTPException(status_code=404, detail=f"Unknown secret '{kind}'")
    return kind


async def _throttle(user: User) -> None:
    def spend() -> None:
        retry = secrets_rate_limiter.retry_after(user.id)
        if retry > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts — try again shortly.",
                headers={"Retry-After": str(int(retry) + 1)},
            )
        secrets_rate_limiter.register_failure(user.id)

    await run_in_threadpool(spend)


@router.get("/secrets", response_model=SecretsResponse)
async def get_secrets(
    response: Response, user: User = Depends(get_current_user)
) -> SecretsResponse:
    """Which of your keys are saved (with a last-four hint for API keys)."""
    _no_store(response)
    statuses = await run_in_threadpool(user_secrets.secret_statuses, user.id)
    kinds = _available_kinds()
    return SecretsResponse(
        secrets=[SecretStatus(**s) for k, s in statuses.items() if k in kinds]
    )


@router.put("/secrets/{kind}", response_model=SecretPutResponse)
async def put_secret(
    kind: str,
    body: SecretPut,
    response: Response,
    user: User = Depends(get_current_user),
) -> SecretPutResponse:
    """Save a key or token, encrypted. It is checked live first unless ``force``."""
    _no_store(response)
    _kind(kind)
    await _throttle(user)
    settings = await run_in_threadpool(user_secrets.load_credentials, user.id)
    check = await check_secret(kind, body.value.strip(), settings)
    if not check.ok and check.checked and not body.force:
        raise HTTPException(status_code=422, detail=check.message)
    try:
        saved = await run_in_threadpool(
            user_secrets.set_secret, user.id, kind, body.value
        )
    except user_secrets.SecretError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return SecretPutResponse(
        secret=SecretStatus(**saved),
        check=SecretCheck(
            kind=kind, ok=check.ok, checked=check.checked, message=check.message
        ),
    )


@router.post("/secrets/{kind}/test", response_model=SecretCheck)
async def test_secret(
    kind: str, response: Response, user: User = Depends(get_current_user)
) -> SecretCheck:
    """Re-check a saved key against its provider."""
    _no_store(response)
    _kind(kind)
    await _throttle(user)
    creds = await run_in_threadpool(user_secrets.load_credentials, user.id)
    if not creds.has(kind):
        raise HTTPException(status_code=404, detail="That key is not saved")
    check = await check_secret(kind, creds.secret(kind), creds)
    return SecretCheck(
        kind=kind, ok=check.ok, checked=check.checked, message=check.message
    )


@router.delete("/secrets/{kind}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(kind: str, user: User = Depends(get_current_user)) -> None:
    """Forget a saved key."""
    _kind(kind)
    await run_in_threadpool(user_secrets.delete_secret, user.id, kind)


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    response: Response, user: User = Depends(get_current_user)
) -> SettingsResponse:
    """Your non-secret integration settings (endpoint, namespace, repos, username)."""
    _no_store(response)
    return SettingsResponse(
        settings=await run_in_threadpool(user_secrets.get_settings, user.id)
    )


@router.put("/settings", response_model=SettingsResponse)
async def put_settings(
    body: SettingsUpdate, response: Response, user: User = Depends(get_current_user)
) -> SettingsResponse:
    """Change some settings; a blank value clears one."""
    _no_store(response)
    changes = dict(body.settings)
    try:
        if changes.get("openai_base_url"):
            changes["openai_base_url"] = check_base_url(
                changes["openai_base_url"] or ""
            )
        saved = await run_in_threadpool(user_secrets.update_settings, user.id, changes)
    except (user_secrets.SecretError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return SettingsResponse(settings=saved)


@router.get("/identities", response_model=IdentitiesResponse)
def get_identities(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> IdentitiesResponse:
    """The sign-in methods linked to your account."""
    return IdentitiesResponse(
        identities=[IdentityOut(**i) for i in identities.list_identities(db, user)],
        has_password=bool(user.hashed_password),
        locked_admin=identities.is_locked_admin(user),
    )


@router.delete("/identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_identity(
    identity_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Unlink one sign-in method — never the last one."""
    ip = request.client.host if request.client else None
    try:
        identities.unlink_identity(db, user, identity_id, ip=ip)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown identity")
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/export", response_class=Response)
async def export_account(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    """A zip of everything you own (datasets, settings) — never your keys."""
    from server.services.export import build_export

    data = await run_in_threadpool(build_export, db, user)
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="datasetgen-export.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Delete your account and everything you own. Your Hugging Face repos stay."""
    from server.api.auth import logout
    from server.services.admin import AdminError, delete_account

    ip = request.client.host if request.client else None
    try:
        delete_account(db, user, ip=ip)
    except AdminError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    return logout(request, response, db)
