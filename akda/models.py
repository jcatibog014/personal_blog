"""The data model.

    users

Roles live on the user (permissions.py holds every rule about them).
Times are naive UTC (dates.utcnow()).
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .dates import utcnow
from .db import Base

OWNER = "owner"
AUTHOR = "author"
READER = "reader"
ROLES = (OWNER, AUTHOR, READER)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('owner', 'author', 'reader')", name="role_known"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    display_name: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default=READER)
    bio: Mapped[str] = mapped_column(Text, default="")  # the owner's bio is the About page
    is_blocked: Mapped[bool] = mapped_column(default=False)
    is_demo: Mapped[bool] = mapped_column(default=False)
    demo_reset_at: Mapped[datetime | None]
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None]
    # A copy sits in the login cookie. Adding 1 here ends every session at once
    # (after a password change or a block), because old cookies stop matching.
    session_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
