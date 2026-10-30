"""Logging in, signing up, sessions and form protection."""
from datetime import timedelta

import pytest
from flask import url_for

from akda import auth, db
from akda.dates import utcnow
from akda.models import AUTHOR, OWNER, READER, User

from .conftest import CSRF, PASSWORD, get_user, log_in_as, make_user, post


def sign_up(client, username="ana", password="long enough", confirm=None, **extra):
    return post(client, "/signup", {"username": username, "password": password,
                                    "confirm_password": confirm or password, **extra})


# ---------- Sign-up ----------

def test_sign_up_makes_a_reader_and_logs_in(app, client):
    response = sign_up(client)
    assert response.status_code == 302
    user = get_user(app, "ana")
    assert user.role == READER
    assert user.password_hash != "long enough"
    assert client.get("/settings").status_code == 200


def test_sign_up_ignores_a_role_in_the_form(app, client):
    sign_up(client, role=OWNER, is_demo="1")
    user = get_user(app, "ana")
    assert user.role == READER and user.is_demo is False


@pytest.mark.parametrize("username", ["ab", "has space", "demo", "demo-reader-1", "ADMIN", "a" * 41, "eva<script>"])
def test_sign_up_refuses_bad_usernames(app, client, username):
    assert sign_up(client, username=username).status_code == 400
    assert get_user(app, auth.clean_username(username)) is None


def test_sign_up_refuses_a_taken_username_in_any_case(app, client):
    make_user(app, "ana")
    response = sign_up(client, username="ANA")
    assert response.status_code == 400
    assert b"already taken" in response.data


def test_sign_up_refuses_a_short_or_different_password(client):
    assert sign_up(client, password="short").status_code == 400
    assert sign_up(client, password="long enough", confirm="something else").status_code == 400


def test_robots_filling_the_hidden_field_make_no_account(app, client):
    response = sign_up(client, website="http://spam.example")
    assert response.status_code == 302
    assert get_user(app, "ana") is None


# ---------- Logging in ----------

def test_log_in_and_out(app, client):
    make_user(app, "ana")
    response = post(client, "/login", {"username": "ANA ", "password": PASSWORD})
    assert response.status_code == 302
    assert client.get("/settings").status_code == 200
    post(client, "/logout")
    assert client.get("/settings").status_code == 302


def test_wrong_login_never_says_whether_the_username_exists(app, client):
    make_user(app, "ana")
    wrong_password = post(client, "/login", {"username": "ana", "password": "nope"})
    no_such_user = post(client, "/login", {"username": "nobody", "password": "nope"})
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert auth.WRONG_LOGIN.encode() in wrong_password.data
    assert auth.WRONG_LOGIN.encode() in no_such_user.data


def test_five_wrong_passwords_lock_the_account(app, ctx):
    user = auth.create_user(ctx, "ana", PASSWORD)
    ctx.commit()
    moment = utcnow()
    for _ in range(auth.MAX_FAILED_LOGINS):
        assert auth.check_login(ctx, "ana", "nope", moment)[0] is None
    # Now even the right password waits...
    found, message = auth.check_login(ctx, "ana", PASSWORD, moment)
    assert found is None and "15 minutes" in message
    # ...and works again once the lock is over.
    found, message = auth.check_login(ctx, "ana", PASSWORD, moment + auth.LOCK_TIME + timedelta(seconds=1))
    assert found.id == user.id and message is None


def test_blocked_user_cannot_log_in_and_learns_only_with_the_right_password(app, client):
    make_user(app, "ana", is_blocked=True)
    wrong = post(client, "/login", {"username": "ana", "password": "nope"})
    assert auth.WRONG_LOGIN.encode() in wrong.data
    right = post(client, "/login", {"username": "ana", "password": PASSWORD})
    assert right.status_code == 401
    assert auth.BLOCKED_LOGIN.encode() in right.data


def test_demo_users_cannot_log_in_with_the_form(app, client):
    make_user(app, "demo-writer", is_demo=True)
    response = post(client, "/login", {"username": "demo-writer", "password": PASSWORD})
    assert response.status_code == 401


# ---------- Sessions ----------

def test_blocking_ends_the_session_at_once(app, client):
    user_id = make_user(app, "ana")
    log_in_as(client, user_id)
    assert client.get("/settings").status_code == 200
    with app.app_context():
        db.session().get(User, user_id).is_blocked = True
        db.session().commit()
    assert client.get("/settings").status_code == 302


def test_changing_the_password_logs_out_other_devices_but_not_this_one(app):
    user_id = make_user(app, "ana")
    this_device, other_device = app.test_client(), app.test_client()
    log_in_as(this_device, user_id)
    log_in_as(other_device, user_id)
    response = post(this_device, "/settings", {
        "action": "password", "current_password": PASSWORD,
        "new_password": "a new password", "confirm_password": "a new password"})
    assert response.status_code == 302
    assert this_device.get("/settings").status_code == 200
    assert other_device.get("/settings").status_code == 302


def test_password_change_needs_the_current_password(app, client):
    log_in_as(client, make_user(app, "ana"))
    response = post(client, "/settings", {
        "action": "password", "current_password": "wrong",
        "new_password": "a new password", "confirm_password": "a new password"})
    assert response.status_code == 400
    assert b"current password" in response.data


def test_changing_the_display_name(app, client):
    log_in_as(client, make_user(app, "ana"))
    post(client, "/settings", {"action": "name", "display_name": "Ana Cruz"})
    assert get_user(app, "ana").display_name == "Ana Cruz"


# ---------- Forms and links ----------

def test_a_post_without_the_csrf_token_fails(app, client):
    assert client.post("/login", data={"username": "ana", "password": PASSWORD}).status_code == 400
    assert client.post("/login", data={"username": "ana", "password": PASSWORD,
                                       "csrf_token": "wrong"}).status_code == 400
    assert client.post("/login", data={"username": "ana", "password": PASSWORD,
                                       "csrf_token": CSRF}).status_code == 401


@pytest.mark.parametrize("target", [
    "https://evil.example", "//evil.example", "/\\evil.example", "/\t/evil.example", "evil.example",
])
def test_safe_next_refuses_other_sites(app, target):
    with app.test_request_context():
        assert auth.safe_next(target) == url_for("public.home")


def test_safe_next_allows_this_site(app):
    with app.test_request_context():
        assert auth.safe_next("/posts/hello?x=1") == "/posts/hello?x=1"


def test_login_goes_back_only_to_this_site(app, client):
    make_user(app, "ana")
    response = post(client, "/login", {"username": "ana", "password": PASSWORD, "next": "//evil.example"})
    assert "evil.example" not in response.headers["Location"]


def test_security_headers_are_on_every_page(client):
    headers = client.get("/").headers
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"


# ---------- Command line ----------

def test_create_user_command_makes_an_owner(app):
    result = app.test_cli_runner().invoke(args=["create-user", "juan", "--role", OWNER],
                                          input="a long password\na long password\n")
    assert result.exit_code == 0, result.output
    assert get_user(app, "juan").role == OWNER


def test_set_password_command_ends_sessions(app, client):
    user_id = make_user(app, "juan", AUTHOR)
    log_in_as(client, user_id)
    result = app.test_cli_runner().invoke(args=["set-password", "juan"],
                                          input="a long password\na long password\n")
    assert result.exit_code == 0, result.output
    assert client.get("/settings").status_code == 302
