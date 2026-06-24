import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, Boolean
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
