"""Comments: threads, approval, the queue and the limits. Who may do what is in permissions.py."""
from datetime import timedelta

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from . import permissions, posts
from .models import APPROVED, PENDING, REJECTED, Comment, CommentReport, Post

BODY_MAX_LENGTH = 2000
REASON_MAX_LENGTH = 200
# Slows down a flood from one account. Owners moderate, so they have no limit.
RATE_LIMIT = 5
RATE_WINDOW = timedelta(minutes=10)
RECENT_SIZE = 50


def body_problem(text):
    if not text:
        return "Write something first."
    if len(text) > BODY_MAX_LENGTH:
        return f"Use at most {BODY_MAX_LENGTH:,} characters."
    return None


def clean_body(text):
    return (text or "").replace("\r\n", "\n").strip()


def over_rate_limit(s, user, now):
    if permissions.is_owner(user):
        return False
    recent = s.scalar(select(func.count()).select_from(Comment).where(
        Comment.user_id == user.id, Comment.created_at > now - RATE_WINDOW))
    return recent >= RATE_LIMIT


def has_approved_comment(s, user):
    return s.scalar(select(exists().where(Comment.user_id == user.id, Comment.status == APPROVED)))


def add(s, user, post, body, parent, now):
    """Save a new comment. The caller has checked permissions and the body."""
    waits = permissions.needs_approval(user, has_approved_comment(s, user))
    # One level of replies: a reply to a reply joins the same thread.
    parent_id = None
    if parent is not None:
        parent_id = parent.parent_id or parent.id
    comment = Comment(post=post, user=user, body=body, parent_id=parent_id,
                      status=PENDING if waits else APPROVED, created_at=now)
    s.add(comment)
    return comment


def valid_parent(s, post, parent_id):
    """The comment being replied to, if it is a visible one on this same post."""
    parent = s.get(Comment, parent_id)
    if parent is None or parent.post_id != post.id or parent.status != APPROVED or parent.deleted_at is not None:
        return None
    return parent


def thread(s, post, viewer, now):
    """The comments this viewer may see, as [(comment, [replies])], oldest first.

    One query loads the whole post's comments with their writers, however many
    there are. A removed comment only stays as a placeholder if replies hang under it.
    """
    rows = s.scalars(
        select(Comment).where(Comment.post_id == post.id)
        .options(joinedload(Comment.user)).order_by(Comment.created_at, Comment.id)
    ).all()
    for comment in rows:
        comment.post = post  # already loaded: saves a query per comment in the checks below
    replies = {}
    for comment in rows:
        if comment.parent_id and comment.deleted_at is None and permissions.can_see_comment(viewer, comment, now):
            replies.setdefault(comment.parent_id, []).append(comment)
    result = []
    for comment in rows:
        if comment.parent_id:
            continue
        under = replies.get(comment.id, [])
        if comment.deleted_at is not None:
            if under:
                result.append((comment, under))
        elif permissions.can_see_comment(viewer, comment, now):
            result.append((comment, under))
    return result


def public_count(s, post):
    return s.scalar(select(func.count()).select_from(Comment).where(
        Comment.post_id == post.id, Comment.status == APPROVED, Comment.deleted_at.is_(None)))


def reported_by(s, user, post):
    """The ids of the comments on this post that this user already reported."""
    if user is None:
        return set()
    return set(s.scalars(select(CommentReport.comment_id).join(Comment).where(
        Comment.post_id == post.id, CommentReport.reporter_id == user.id)))


# ---------- Moderating ----------

def _scope(user, now):
    """The comments this user moderates: on their own posts, or for the owner, also
    on every post visible to them. The same rule as permissions.can_moderate_comment:
    a post that went back to draft is private, so its title must not show here."""
    if permissions.is_owner(user):
        return or_(Post.author_id == user.id, posts.visible_filter(user, now))
    return Post.author_id == user.id


def _queue_query(user, now):
    return (select(Comment).join(Comment.post).where(_scope(user, now), Comment.deleted_at.is_(None))
            .options(joinedload(Comment.user), joinedload(Comment.post)))


def waiting(s, user, now):
    return s.scalars(_queue_query(user, now).where(Comment.status == PENDING).order_by(Comment.created_at)).all()


def reported(s, user, now):
    """Comments with open reports, each with its reports (selectinload: no N+1)."""
    open_report = Comment.reports.any(CommentReport.resolved_at.is_(None))
    return s.scalars(_queue_query(user, now).where(open_report, Comment.status == APPROVED)
                     .options(selectinload(Comment.reports)).order_by(Comment.created_at)).all()


def recent(s, user, now):
    return s.scalars(_queue_query(user, now).where(Comment.status == APPROVED)
                     .order_by(Comment.created_at.desc()).limit(RECENT_SIZE)).all()


def waiting_count(s, user, now):
    return s.scalar(select(func.count()).select_from(Comment).join(Comment.post).where(
        _scope(user, now), Comment.deleted_at.is_(None), Comment.status == PENDING))


def resolve_reports(comment, now):
    for report in comment.reports:
        if report.resolved_at is None:
            report.resolved_at = now


def approve(comment):
    comment.status = APPROVED


def reject(comment, now):
    comment.status = REJECTED
    resolve_reports(comment, now)


def remove(comment, now):
    comment.deleted_at = now
    resolve_reports(comment, now)
