"""Logging in and out, signing up, and protection for every form.

Anyone can sign up, and the sign-up page can only ever make a READER: it
never reads a role from the form. The owner's account is made on the
command line:

    flask --app akda create-user <name> --role owner

Passwords are stored only as hashes. The login cookie holds the user's id
and their session_version; load_user() checks both on every request, so a
blocked user or an old cookie is logged out straight away.
"""
import functools
import hmac
import re
import secrets
from datetime import timedelta

import click
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from flask.cli import with_appcontext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, permissions
from .dates import utcnow
from .models import READER, ROLES, User

bp = Blueprint("auth", __name__)

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 40
DISPLAY_NAME_MAX_LENGTH = 60
PASSWORD_MIN_LENGTH = 8
USERNAME_PATTERN = re.compile(r"[a-z0-9_-]+")
# Nobody may sign up with a name that looks like it speaks for the site.
RESERVED_USERNAMES = {"admin", "administrator", "owner", "akda", "moderator", "support"}
# After 5 wrong passwords in a row, the account waits 15 minutes.
# This makes guessing a password on the live site very slow.
MAX_FAILED_LOGINS = 5
LOCK_TIME = timedelta(minutes=15)

WRONG_LOGIN = "Wrong username or password."
BLOCKED_LOGIN = "This account has been blocked."


# ---------- Users in the database ----------

def clean_username(text):
    return (text or "").strip().lower()


def username_problem(username):
    """Why this (cleaned) username can't be used, or None if it is fine."""
    if not USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH:
        return f"Use {USERNAME_MIN_LENGTH} to {USERNAME_MAX_LENGTH} characters."
    if not USERNAME_PATTERN.fullmatch(username):
        return "Use only letters, numbers, - and _."
    if username in RESERVED_USERNAMES or username.startswith("demo"):
        return "That username is not available."
    return None


def password_problem(password, confirm):
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Use at least {PASSWORD_MIN_LENGTH} characters."
    if password != confirm:
        return "The two passwords are not the same."
    return None


def find_user(s, username):
    """A real (not demo) user by username, or None."""
    return s.scalar(select(User).where(User.username == clean_username(username), User.is_demo.is_(False)))


def create_user(s, username, password, role=READER, display_name=None, is_demo=False):
    """Add a user. The caller commits."""
    username = clean_username(username)
    user = User(username=username, display_name=display_name or username,
                password_hash=generate_password_hash(password), role=role, is_demo=is_demo)
    s.add(user)
    s.flush()
    return user


def set_password(user, password):
    user.password_hash = generate_password_hash(password)
    user.failed_logins = 0
    user.locked_until = None
    user.session_version += 1  # every other device is logged out


def check_login(s, username, password, moment):
    """Return (user, None) if the password is right, else (None, message).

    The message never says whether the username exists. A blocked user only
    finds out after giving the right password.
    """
    user = find_user(s, username)
    if user is None:
        return None, WRONG_LOGIN

    if user.locked_until and user.locked_until > moment:
        return None, "Too many failed attempts. Please wait 15 minutes and try again."

    if not check_password_hash(user.password_hash, password or ""):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins, user.locked_until = 0, moment + LOCK_TIME
        s.commit()
        return None, WRONG_LOGIN

    if user.is_blocked:
        return None, BLOCKED_LOGIN

    user.failed_logins, user.locked_until = 0, None
    s.commit()
    return user, None


def safe_next(target, default=None):
    """Only go back to a page on this site (after logging in or saving a form).

    "/posts/hello" is fine. "https://evil.example" and "//evil.example"
    are not: a fake link could send people there after a real login. Browsers
    drop tabs and newlines and read a backslash as a slash, so those are out too.
    """
    if (target and target.startswith("/") and not target.startswith("//")
            and "\\" not in target and not any(ord(c) < 32 for c in target)):
        return target
    return default or url_for("public.home")


def log_in(user):
    session.clear()  # a new session for the new user (old cookies can't be reused)
    session.permanent = True  # stay logged in for PERMANENT_SESSION_LIFETIME
    session["user_id"] = user.id
    session["session_version"] = user.session_version


def after_login_page(user):
    return url_for("desk.my_posts") if permissions.can_write(user) else url_for("public.home")


# ---------- Every request ----------

@bp.before_app_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is None:
        return
    user = db.session().get(User, user_id)
    if user is None or user.is_blocked or session.get("session_version") != user.session_version:
        # Keep the CSRF token: only the login part of this cookie is out of date.
        session.pop("user_id", None)
        session.pop("session_version", None)
        return
    g.user = user


def csrf_token():
    """A secret per session, put into every form as a hidden field.

    Another website could make your browser send a form to this site (your
    login cookie goes with it). It can't read this secret, so its form fails.
    """
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@bp.before_app_request
def check_csrf():
    if request.method != "POST":
        return
    sent = request.form.get("csrf_token", "")
    expected = session.get("csrf", "")
    # compare_digest takes the same time for every wrong guess.
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "This form has expired. Please go back, reload the page and try again.")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            # Only a GET can be repeated after logging in.
            next_page = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("auth.login", next=next_page))
        return view(*args, **kwargs)
    return wrapped


# ---------- Pages ----------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(after_login_page(g.user))
    next_page = request.values.get("next", "")
    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "")[:USERNAME_MAX_LENGTH]
        user, error = check_login(db.session(), username, request.form.get("password", ""), utcnow())
        if user:
            log_in(user)
            return redirect(safe_next(next_page, after_login_page(user)))
    status = 401 if error else 200
    return render_template("login.html", error=error, username=username, next=next_page), status


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user is not None:
        return redirect(after_login_page(g.user))
    next_page = request.values.get("next", "")
    errors = {}
    username = ""
    if request.method == "POST":
        # A hidden field people never see. Only robots fill it in, and they get
        # the same page as everyone else, so they learn nothing from it.
        if request.form.get("website"):
            return redirect(url_for("public.home"))
        username = clean_username(request.form.get("username", ""))[:USERNAME_MAX_LENGTH + 1]
        password = request.form.get("password", "")
        problem = username_problem(username)
        if problem:
            errors["username"] = problem
        problem = password_problem(password, request.form.get("confirm_password", ""))
        if problem:
            errors["password"] = problem
        if not errors:
            s = db.session()
            try:
                user = create_user(s, username, password)
                s.commit()
            except IntegrityError:
                s.rollback()
                errors["username"] = "That username is already taken."
            else:
                log_in(user)
                flash("Welcome to Akda! You can now comment on any post.")
                return redirect(safe_next(next_page))
    return render_template("signup.html", errors=errors, username=username,
                           next=next_page), 400 if errors else 200


@bp.post("/logout")
def logout():
    session.clear()
    flash("You have logged out.")
    return redirect(url_for("public.home"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    errors = {}
    if request.method == "POST":
        if g.user.is_demo:
            abort(403, "The demo account can't change its settings.")
        action = request.form.get("action")
        if action == "name":
            name = request.form.get("display_name", "").strip()
            if not name or len(name) > DISPLAY_NAME_MAX_LENGTH:
                errors["display_name"] = f"Use 1 to {DISPLAY_NAME_MAX_LENGTH} characters."
            else:
                g.user.display_name = name
                db.session().commit()
                flash("Your name has been changed.")
                return redirect(url_for("auth.settings"))
        elif action == "password":
            new = request.form.get("new_password", "")
            if not check_password_hash(g.user.password_hash, request.form.get("current_password", "")):
                errors["current_password"] = "That isn't your current password."
            problem = password_problem(new, request.form.get("confirm_password", ""))
            if problem:
                errors["new_password"] = problem
            if not errors:
                set_password(g.user, new)
                db.session().commit()
                # This device stays logged in; every other one is logged out.
                session["session_version"] = g.user.session_version
                flash("Your password has been changed.")
                return redirect(url_for("auth.settings"))
    return render_template("settings.html", errors=errors), 400 if errors else 200


# ---------- Command line ----------

def ask_password():
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < PASSWORD_MIN_LENGTH:
        raise click.ClickException(f"Use at least {PASSWORD_MIN_LENGTH} characters.")
    return password


@click.command("create-user")
@with_appcontext
@click.argument("username")
@click.option("--role", type=click.Choice(ROLES), default=READER, show_default=True)
def create_user_command(username, role):
    """Make a login. This is the only way to make an owner."""
    s = db.session()
    username = clean_username(username)
    problem = username_problem(username)
    if problem:
        raise click.ClickException(problem)
    if s.scalar(select(User).where(User.username == username)):
        raise click.ClickException(f'"{username}" already exists. Use set-password to change the password.')
    create_user(s, username, ask_password(), role=role)
    s.commit()
    click.echo(f'Made the {role} "{username}".')


@click.command("set-password")
@with_appcontext
@click.argument("username")
def set_password_command(username):
    """Change a user's password (and unlock the account). Also ends their sessions."""
    s = db.session()
    user = find_user(s, username)
    if user is None:
        raise click.ClickException(f'There is no user "{username}".')
    set_password(user, ask_password())
    s.commit()
    click.echo("The password is changed.")


def init_app(app):
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["can"] = permissions
    for command in (create_user_command, set_password_command):
        app.cli.add_command(command)
