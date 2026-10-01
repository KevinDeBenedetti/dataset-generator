from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SecretStatus(BaseModel):
    """What the API says about a stored secret — never the secret itself."""

    kind: str
    configured: bool
    hint: Optional[str] = Field(
        None, description="Last four characters of an API key, when it is safe to show"
    )
    updated_at: Optional[datetime] = None


class SecretsResponse(BaseModel):
    secrets: List[SecretStatus]


class SecretPut(BaseModel):
    value: str = Field(..., min_length=1, max_length=4096, repr=False)
    force: bool = Field(
        False,
        description="Save even if the live check fails (the provider is down, or the "
        "key is only valid for actions the check does not cover)",
    )


class SecretCheck(BaseModel):
    kind: str
    ok: bool
    checked: bool = Field(
        description="False when this kind of secret can only be format-checked"
    )
    message: str


class SecretPutResponse(BaseModel):
    secret: SecretStatus
    check: SecretCheck


class SettingsResponse(BaseModel):
    settings: Dict[str, str]


class SettingsUpdate(BaseModel):
    settings: Dict[str, Optional[str]]


class IdentityOut(BaseModel):
    id: str
    provider: str
    email: Optional[str] = None
    username: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None


class IdentitiesResponse(BaseModel):
    identities: List[IdentityOut]
    has_password: bool
    locked_admin: bool = Field(
        description="Your email is in ADMIN_EMAILS: you stay admin whatever happens"
    )
