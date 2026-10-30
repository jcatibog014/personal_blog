"""Who may do what. EVERY rule about roles is in this file.

Views and templates ask these functions and never look at user.role
themselves, so a rule can only ever be wrong in one place. They are plain
functions: `user` is a User or None (a visitor who isn't logged in).
tests/test_permissions.py checks them as one big table.
"""
from .models import AUTHOR, OWNER, PUBLISHED


def is_active(user):
    return user is not None and not user.is_blocked


def is_owner(user):
    return is_active(user) and user.role == OWNER


def can_write(user):
    """Owners and authors have the Desk: they write posts."""
    return is_active(user) and user.role in (OWNER, AUTHOR)


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
