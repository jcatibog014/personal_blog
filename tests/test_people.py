"""Invite links, the People page and blocking."""
from datetime import timedelta

import pytest
from sqlalchemy import event, select

from akda import db, invites
from akda.dates import utcnow
from akda.models import AUTHOR, OWNER, READER, Invite, User

from .conftest import PASSWORD, add_post, get_user, is_logged_in, log_in_as, make_user, post as post_form


@pytest.fixture
def owner(app, owner_id):
    return log_in_as(app.test_client(), owner_id)


def make_invite(app, owner_id, now=None):
    with app.app_context():
        s = db.session()
        token = invites.create(s, s.get(User, owner_id), now or utcnow())
        s.commit()
        return token


def join(client, token, username="rosa", password="long enough", **extra):
    return post_form(client, f"/invite/{token}", {"username": username, "password": password,
                                                  "confirm_password": password, **extra})


# ---------- Invites ----------

def test_the_owner_makes_a_link_shown_once(app, owner):
    response = post_form(owner, "/desk/people/invites")
    assert response.status_code == 302
    page = owner.get("/desk/people").data
    assert b"/invite/" in page and b"Your New Invite Link" in page
    assert b"Your New Invite Link" not in owner.get("/desk/people").data  # gone on the next visit


def test_only_a_hash_of_the_token_is_stored(app, owner_id):
    token = make_invite(app, owner_id)
    with app.app_context():
        stored = db.session().scalar(select(Invite))
    assert stored.token_hash != token and token not in stored.token_hash and len(stored.token_hash) == 64


def test_an_invite_makes_an_author_and_logs_in(app, client, owner_id):
    token = make_invite(app, owner_id)
    response = join(client, token)
    assert response.status_code == 302 and "/desk" in response.headers["Location"]
    assert get_user(app, "rosa").role == AUTHOR
    assert client.get("/desk/").status_code == 200


def test_an_invite_ignores_a_role_in_the_form(app, client, owner_id):
    join(client, make_invite(app, owner_id), role=OWNER)
    assert get_user(app, "rosa").role == AUTHOR


def test_an_invite_works_only_once(app, owner_id):
    token = make_invite(app, owner_id)
    join(app.test_client(), token)
    with app.test_client() as second:
        assert second.get(f"/invite/{token}").status_code == 404
        assert join(second, token, username="ben").status_code == 404
    assert get_user(app, "ben") is None
    with app.app_context():
        assert db.session().scalar(select(Invite)).used_by_id == get_user(app, "rosa").id


def test_two_people_at_once_only_one_wins(app, ctx, owner_id):
    token = make_invite(app, owner_id)
    invite = invites.find_usable(ctx, token, utcnow())
    first, second = make_user(app, "first"), make_user(app, "second")
    assert invites.claim(ctx, invite, ctx.get(User, first), utcnow()) is True
    assert invites.claim(ctx, invite, ctx.get(User, second), utcnow()) is False


def test_an_expired_invite_fails(app, client, owner_id):
    token = make_invite(app, owner_id, utcnow() - invites.LIFETIME - timedelta(seconds=1))
    assert client.get(f"/invite/{token}").status_code == 404
    assert join(client, token).status_code == 404
    assert get_user(app, "rosa") is None


def test_a_made_up_invite_fails(client):
    assert client.get("/invite/not-a-real-token").status_code == 404


def test_a_bad_username_keeps_the_invite_usable(app, client, owner_id):
    token = make_invite(app, owner_id)
    assert join(client, token, username="a").status_code == 400
    make_user(app, "taken")
    assert join(client, token, username="taken").status_code == 400
    assert join(client, token).status_code == 302


def test_a_logged_in_person_is_asked_to_log_out_first(app, owner_id, reader_id):
    token = make_invite(app, owner_id)
    reader = log_in_as(app.test_client(), reader_id)
    assert b"log out first" in reader.get(f"/invite/{token}").data
    assert join(reader, token).status_code == 200
    assert get_user(app, "rosa") is None
    assert get_user(app, "pedro").role == READER


def test_cancelling_an_invite(app, client, owner, owner_id):
    token = make_invite(app, owner_id)
    with app.app_context():
        invite_id = db.session().scalar(select(Invite.id))
    assert post_form(owner, f"/desk/people/invites/{invite_id}/cancel").status_code == 302
    assert client.get(f"/invite/{token}").status_code == 404


def test_waiting_invites_are_listed_but_not_used_or_expired_ones(app, ctx, owner_id):
    make_invite(app, owner_id)
    make_invite(app, owner_id, utcnow() - invites.LIFETIME - timedelta(days=1))
    used = make_invite(app, owner_id)
    invites.claim(ctx, invites.find_usable(ctx, used, utcnow()), ctx.get(User, owner_id), utcnow())
    ctx.commit()
    assert len(invites.waiting(ctx, utcnow())) == 1


# ---------- Who can use the People page ----------

@pytest.mark.parametrize("role,status", [(AUTHOR, 403), (READER, 403)])
def test_the_people_page_is_only_for_the_owner(app, owner_id, role, status):
    other = make_user(app, "rosa", role)
    token = make_invite(app, owner_id)
    with app.app_context():
        invite_id = db.session().scalar(select(Invite.id))
    client = log_in_as(app.test_client(), other)
    assert client.get("/desk/people").status_code == status
    assert post_form(client, "/desk/people/invites").status_code == status
    assert post_form(client, f"/desk/people/invites/{invite_id}/cancel").status_code == status
    assert post_form(client, f"/desk/people/{owner_id}/block").status_code == status
    assert get_user(app, "juan").is_blocked is False
    assert app.test_client().get(f"/invite/{token}").status_code == 200


def test_visitors_are_sent_to_log_in(client):
    assert client.get("/desk/people").status_code == 302


def test_the_menu_shows_people_only_to_the_owner(app, owner, author_id):
    assert b"/desk/people" in owner.get("/desk/").data
    assert b"/desk/people" not in log_in_as(app.test_client(), author_id).get("/desk/").data


# ---------- Blocking ----------

def test_blocking_ends_the_session_and_login_then_unblocking_restores_it(app, owner, reader_id):
    reader = log_in_as(app.test_client(), reader_id)
    assert is_logged_in(reader)

    assert post_form(owner, f"/desk/people/{reader_id}/block").status_code == 302
    assert not is_logged_in(reader)
    denied = post_form(app.test_client(), "/login", {"username": "pedro", "password": PASSWORD})
    assert denied.status_code == 401

    post_form(owner, f"/desk/people/{reader_id}/unblock")
    allowed = post_form(app.test_client(), "/login", {"username": "pedro", "password": PASSWORD})
    assert allowed.status_code == 302


def test_a_blocked_author_cannot_write_but_their_posts_stay(app, client, owner, author_id):
    add_post(app, author_id, title="Still Here")
    author = log_in_as(app.test_client(), author_id)
    post_form(owner, f"/desk/people/{author_id}/block")
    assert author.get("/desk/").status_code == 302
    assert b"Still Here" in client.get("/").data


def test_the_owner_cannot_be_blocked(app, owner, owner_id):
    other_owner = make_user(app, "second", OWNER)
    assert post_form(owner, f"/desk/people/{owner_id}/block").status_code == 403
    assert post_form(owner, f"/desk/people/{other_owner}/block").status_code == 403
    assert get_user(app, "juan").is_blocked is False


def test_a_missing_or_demo_person_gives_404(app, owner):
    demo = make_user(app, "demo-writer", AUTHOR, is_demo=True)
    assert post_form(owner, f"/desk/people/{demo}/block").status_code == 404
    assert post_form(owner, "/desk/people/9999/block").status_code == 404


# ---------- The People page ----------

def test_the_list_has_counts_and_no_demo_users(app, owner, author_id):
    make_user(app, "demo-writer", AUTHOR, is_demo=True, display_name="Hidden Demo")
    add_post(app, author_id)
    add_post(app, author_id, title="Another")
    page = owner.get("/desk/people").data
    assert b"maria" in page and b"Hidden Demo" not in page
    assert b"<td>2</td>" in page


def test_the_list_needs_no_query_per_person(app, owner):
    with app.app_context():
        engine = db.engine()

    def count_queries():
        statements = []
        listener = lambda conn, cur, statement, *rest: statements.append(statement)
        event.listen(engine, "before_cursor_execute", listener)
        assert owner.get("/desk/people").status_code == 200
        event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    few = count_queries()
    for number in range(5):
        make_user(app, f"person{number}")
    assert count_queries() == few
