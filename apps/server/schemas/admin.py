"""Backoffice payloads. These models are the allowlist of what an admin can see:
no dataset names or contents, no settings values, no secrets."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AdminUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    role: str
    is_active: bool
    locked: bool = Field(description="Listed in ADMIN_EMAILS: role and status fixed")
    providers: List[str]
    has_password: bool
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    configured_keys: List[str] = Field(description="Kinds of keys saved — never values")
    datasets: int
    pairs: int
    runs: int


class AdminUsersResponse(BaseModel):
    total: int
    users: List[AdminUser]


class AdminUserUpdate(BaseModel):
    role: Optional[Literal["user", "admin"]] = None
    is_active: Optional[bool] = None


class AuditEntry(BaseModel):
    id: str
    created_at: datetime
    action: str
    actor: Optional[str] = None
    target: Optional[str] = None
    target_user_id: Optional[str] = None
    ip: Optional[str] = None
    detail: Dict[str, Any]


class AuditResponse(BaseModel):
    total: int
    entries: List[AuditEntry]


class PlatformSwitch(BaseModel):
    key: str
    label: str
    value: Any
    overridden: bool = Field(
        description="Set from the backoffice (else the env default)"
    )


class PlatformResponse(BaseModel):
    settings: List[PlatformSwitch]


class PlatformUpdate(BaseModel):
    settings: Dict[str, Any] = Field(
        description="key → value; null resets to the env default"
    )


class UsageUsers(BaseModel):
    total: int
    active: int
    admins: int
    signed_in_30d: int


class UsageResponse(BaseModel):
    users: UsageUsers
    datasets: int
    pairs: int
    runs_30d: Dict[str, int]
    running: int
