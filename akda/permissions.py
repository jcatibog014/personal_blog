"""Who may do what. EVERY rule about roles is in this file.

Views and templates ask these functions and never look at user.role
themselves, so a rule can only ever be wrong in one place. They are plain
functions: `user` is a User or None (a visitor who isn't logged in).
tests/test_permissions.py checks them as one big table.
"""
from datetime import timedelta

from .models import APPROVED, AUTHOR, OWNER, PENDING, PUBLISHED, REJECTED

COMMENT_EDIT_WINDOW = timedelta(minutes=15)


def is_active(user):
    return user is not None and not user.is_blocked


def is_owner(user):
    return is_active(user) and user.role == OWNER


def can_write(user):
    """Owners and authors have the Desk: they write posts."""
    return is_active(user) and user.role in (OWNER, AUTHOR)


def can_edit_about(user):
    return is_owner(user)


def can_manage_people(user):
    """Invite authors, block users."""
    return is_owner(user)


def can_block_user(user, person):
    """Anyone but an owner, so the site can never lock out the person running it."""
    return can_manage_people(user) and person.role != OWNER and not person.is_demo


# ---------- Posts ----------

def is_live(post, now):
    """THE rule, in Python. posts.live_filter() is the same rule in SQL."""
    return post.status == PUBLISHED and post.published_at <= now


def is_own_post(user, post):
    return is_active(user) and post.author_id == user.id


def can_view_post(user, post, now):
    """Your own post, always. Anyone else's only when live, and the demo's
    posts only for demo visitors (the demo is a sandbox)."""
    if is_own_post(user, post):
        return True
    if not is_live(post, now):
        return False
    return not post.author.is_demo or (user is not None and user.is_demo)


def can_edit_post(user, post):
    """Only the author, ever. The owner can take a post down but can't change
    somebody's words or read their drafts."""
    return can_write(user) and is_own_post(user, post)


def can_take_down_post(user, post, now):
    """Unpublish or delete: the author, or the owner if the post is live."""
    if can_edit_post(user, post):
        return True
    return is_owner(user) and can_view_post(user, post, now)


# ---------- Comments ----------

def can_comment(user, post, now):
    """Anyone logged in, on a post that is live and that they can see. The demo
    can only comment on demo posts, so it can never write on the real site."""
    if not is_active(user) or not is_live(post, now) or not can_view_post(user, post, now):
        return False
    return not user.is_demo or post.author.is_demo


def is_own_comment(user, comment):
    return is_active(user) and comment.user_id == user.id


def can_edit_comment(user, comment, now):
    """Your own, for 15 minutes. After that, an approved comment can't quietly
    turn into something else."""
    return (is_own_comment(user, comment) and comment.deleted_at is None
            and comment.status != REJECTED and now <= comment.created_at + COMMENT_EDIT_WINDOW)


def can_moderate_comment(user, comment, now):
    """An author moderates comments on their own posts. The owner also moderates
    on any post they can see, but not on someone's post that went back to being a
    private draft, and not in the demo's sandbox."""
    if not can_write(user) or comment.deleted_at is not None:
        return False
    return comment.post.author_id == user.id or (is_owner(user) and can_view_post(user, comment.post, now))


def can_delete_comment(user, comment, now):
    if comment.deleted_at is not None:
        return False
    return is_own_comment(user, comment) or can_moderate_comment(user, comment, now)


def can_report_comment(user, comment):
    """Anyone logged in, about someone else's visible comment."""
    return (is_active(user) and comment.user_id != user.id and comment.status == APPROVED
            and comment.deleted_at is None)


def can_see_comment(user, comment, now):
    """Approved ones are public. Pending ones show to their writer and the moderators."""
    if comment.status == APPROVED:
        return True
    if comment.status == PENDING:
        return is_own_comment(user, comment) or can_moderate_comment(user, comment, now)
    return False


def needs_approval(user, has_approved_comment):
    """A reader's first comment waits; once one is approved, the rest appear at once."""
    return not can_write(user) and not has_approved_comment
