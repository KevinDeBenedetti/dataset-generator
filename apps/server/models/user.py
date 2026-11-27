import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class UserRole:
    """The two roles the app recognises. Stored as a plain string column."""

    USER = "user"
    ADMIN = "admin"

    ALL = (USER, ADMIN)


class AuthProvider:
    """How the account authenticates."""

    LOCAL = "local"  # email + password
    OIDC = "oidc"  # Infomaniak OIDC (accounts created before identities existed)
    INFOMANIAK = "infomaniak"
    GITHUB = "github"
    SYSTEM = "system"  # the inactive owner of pre-multi-user data (see below)
    SECRETS = "secrets"  # the admin, signed in from deployment secrets only
    HF = "hf"  # a Hugging Face username + token (auth/hf_token.py)


# The secrets admin's email: a reserved address derived from ADMIN_USERNAME, the
# stable key of its row (auth/admin_secrets.py). ``.invalid`` never receives mail.
SECRETS_ADMIN_DOMAIN = "secrets-admin.invalid"


def secrets_admin_email(username: str) -> str:
    return f"{username.lower()}@{SECRETS_ADMIN_DOMAIN}"


# Owns the datasets/runs/settings that predate per-user ownership when there was
# no admin yet to receive them. Inactive and passwordless, on a reserved TLD: it
# can never sign in, and `python -m server.cli claim-legacy` empties it.
SYSTEM_EMAIL = "system@datasetgen.invalid"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Null for a Hugging Face account whose email the Hub didn't give (or that
    # another account already holds). Unique when set.
    email: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    # The Hugging Face account a user signs in with (auth/hf_token.py): keyed on
    # the Hub's stable id, never the username, which can change.
    hf_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    hf_username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    hf_avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Null for OIDC-only accounts that never set a local password.
    hashed_password: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(
        String, nullable=False, default=UserRole.USER, index=True
    )
    # "local" or "oidc": how the account was created / authenticates.
    provider: Mapped[str] = mapped_column(
        String, nullable=False, default=AuthProvider.LOCAL
    )
    # Legacy: the Infomaniak subject before ``identities`` existed (copied there
    # by migration c0d1e2f3a4b5; no longer read). SSO sign-ins go through
    # ``Identity`` rows.
    oidc_sub: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, default=lambda: datetime.now(timezone.utc)
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Access tokens issued before this instant are refused ("sign out
    # everywhere", deactivation): a JWT otherwise stays valid until it expires.
    sessions_valid_after: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def display_name(self) -> str:
        """How the app names the account: its HF username, else its email."""
        return self.hf_username or self.email or self.id


class RefreshToken(Base):
    """A long-lived, single-use refresh token.

    Only the SHA-256 hash of the raw token is stored. Tokens belong to a
    *family* (the chain started at one login): each ``/auth/refresh`` revokes
    the presented token and issues a successor in the same family. Presenting
    an already-revoked token is treated as replay/theft and revokes the whole
    family, forcing a fresh login on every device holding a token from it.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    family_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, default=lambda: datetime.now(timezone.utc)
    )
    # Set when the token is consumed by a rotation, a logout, or a family-wide
    # revocation. Null = still usable (subject to expires_at).
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
