import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, Boolean, ForeignKey
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
    OIDC = "oidc"  # Infomaniak OIDC


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    # Null for OIDC-only accounts that never set a local password.
    hashed_password: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(
        String, nullable=False, default=UserRole.USER, index=True
    )
    # "local" or "oidc": how the account was created / authenticates.
    provider: Mapped[str] = mapped_column(
        String, nullable=False, default=AuthProvider.LOCAL
    )
    # The OIDC subject identifier ("sub"), set for accounts linked to Infomaniak.
    oidc_sub: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


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
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    # Set when the token is consumed by a rotation, a logout, or a family-wide
    # revocation. Null = still usable (subject to expires_at).
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
