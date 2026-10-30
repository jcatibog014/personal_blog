"""Who may do what. EVERY rule about roles is in this file.

Views and templates ask these functions and never look at user.role
themselves, so a rule can only ever be wrong in one place. They are plain
functions: `user` is a User or None (a visitor who isn't logged in).
tests/test_permissions.py checks them as one big table.
"""
from .models import AUTHOR, OWNER


def is_active(user):
    return user is not None and not user.is_blocked


def is_owner(user):
    return is_active(user) and user.role == OWNER


def can_write(user):
    """Owners and authors have the Desk: they write posts."""
    return is_active(user) and user.role in (OWNER, AUTHOR)
