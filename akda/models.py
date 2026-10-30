"""The data model.

    users ─┬─< posts ──< comments ──< comment_reports >── users
           └─< comments (parent_id points at another comment: one level of replies)

Roles live on the user (permissions.py holds every rule about them).
Times are naive UTC (dates.utcnow()).
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .dates import utcnow
from .db import Base

OWNER = "owner"
AUTHOR = "author"
READER = "reader"
ROLES = (OWNER, AUTHOR, READER)

DRAFT = "draft"
PUBLISHED = "published"

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"


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

    posts: Mapped[list["Post"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published')", name="status_known"),
        CheckConstraint("status = 'draft' OR published_at IS NOT NULL", name="published_has_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    # Empty until the first publish, then fixed. NULLs don't clash in a UNIQUE column.
    slug: Mapped[str | None] = mapped_column(String(100), unique=True)
    summary: Mapped[str] = mapped_column(String(300), default="")
    excerpt: Mapped[str] = mapped_column(String(320), default="")  # for cards: the summary or the first words
    # deferred: only loaded when used, so lists of posts never carry the full text.
    body_md: Mapped[str] = mapped_column(Text, default="", deferred=True)
    body_html: Mapped[str] = mapped_column(Text, default="", deferred=True)  # always cleaned by render.py
    status: Mapped[str] = mapped_column(String(10), default=DRAFT)
    # Scheduling is a date in the future. posts.live_filter() is the rule.
    published_at: Mapped[datetime | None] = mapped_column(index=True)
    reading_minutes: Mapped[int] = mapped_column(default=1)
    # SQLAlchemy adds 1 on every save. A save from an out-of-date tab fails instead
    # of overwriting newer text (the editor also sends the number it started from).
    revision: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __mapper_args__ = {"version_id_col": revision}

    author: Mapped[User] = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(back_populates="post", cascade="all, delete-orphan",
                                                     passive_deletes=True)


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status_known"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # The table points at itself: a reply's parent is another comment. comments.py
    # keeps it to one level, so a reply to a reply joins the same thread.
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)  # plain text: the templates escape it, it is never Markdown
    status: Mapped[str] = mapped_column(String(10), default=PENDING)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    edited_at: Mapped[datetime | None]
    # Soft delete: the row stays, so replies keep their place under "removed".
    deleted_at: Mapped[datetime | None]

    post: Mapped[Post] = relationship(back_populates="comments")
    user: Mapped[User] = relationship()
    parent: Mapped["Comment | None"] = relationship(remote_side=[id])
    reports: Mapped[list["CommentReport"]] = relationship(back_populates="comment", cascade="all, delete-orphan",
                                                          passive_deletes=True)


class CommentReport(Base):
    __tablename__ = "comment_reports"
    # One report per person: reporting twice can't make a comment look worse.
    __table_args__ = (UniqueConstraint("comment_id", "reporter_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), index=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    resolved_at: Mapped[datetime | None]

    comment: Mapped[Comment] = relationship(back_populates="reports")
    reporter: Mapped[User] = relationship()
