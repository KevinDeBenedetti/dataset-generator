"""The backoffice API — every route requires an admin (router-level dependency)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from server.core.database import get_db
from server.models.user import User
from server.schemas.admin import (
    AdminUser,
    AdminUsersResponse,
    AdminUserUpdate,
    AuditResponse,
    PlatformResponse,
    PlatformUpdate,
    UsageResponse,
)
from server.services import admin, platform
from server.services.auth import require_admin

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


def _ip(request: Request):
    return request.client.host if request.client else None


@router.get("/users", response_model=AdminUsersResponse)
def list_users(
    q: str = Query("", max_length=200, description="Filter on the email"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> AdminUsersResponse:
    """Accounts with counts and configured-key booleans — no content."""
    return AdminUsersResponse(**admin.list_users(db, q, limit, offset))


@router.get("/users/{user_id}", response_model=AdminUser)
def get_user(user_id: str, db: Session = Depends(get_db)) -> AdminUser:
    try:
        return AdminUser(**admin.get_user(db, user_id))
    except admin.NotFound:
        raise HTTPException(status_code=404, detail="Unknown user")


@router.patch("/users/{user_id}", response_model=AdminUser)
def update_user(
    user_id: str,
    body: AdminUserUpdate,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUser:
    """Change a role or (de)activate — never the last admin, never ADMIN_EMAILS."""
    try:
        return AdminUser(
            **admin.update_user(
                db,
                actor,
                user_id,
                role=body.role,
                is_active=body.is_active,
                ip=_ip(request),
            )
        )
    except admin.NotFound:
        raise HTTPException(status_code=404, detail="Unknown user")
    except admin.AdminError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Delete an account and everything it owns (Hugging Face repos stay)."""
    try:
        admin.delete_user(db, actor, user_id, ip=_ip(request))
    except admin.NotFound:
        raise HTTPException(status_code=404, detail="Unknown user")
    except admin.AdminError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/audit", response_model=AuditResponse)
def list_audit(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str = Query("", max_length=100),
    user_id: str = Query("", max_length=100),
    db: Session = Depends(get_db),
) -> AuditResponse:
    return AuditResponse(**admin.list_audit(db, limit, offset, action, user_id))


@router.get("/usage", response_model=UsageResponse)
def usage(db: Session = Depends(get_db)) -> UsageResponse:
    return UsageResponse(**admin.usage(db))


@router.get("/platform", response_model=PlatformResponse)
def get_platform() -> PlatformResponse:
    return PlatformResponse(settings=platform.snapshot())


@router.put("/platform", response_model=PlatformResponse)
def put_platform(
    body: PlatformUpdate,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> PlatformResponse:
    try:
        return PlatformResponse(
            settings=platform.update(db, actor, body.settings, ip=_ip(request))
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
