"""Every role against every action, as one table, then the real routes.

The rules are plain functions, so the table needs no database. The route tests
below check that the views really ask them (the right 403 or 404).
"""
from datetime import datetime, timedelta

import pytest

from akda import permissions as can
from akda.models import APPROVED, AUTHOR, DRAFT, OWNER, PENDING, PUBLISHED, READER, REJECTED, Comment, Post, User

from .conftest import add_post, edit_form, get_post, log_in_as, make_user, post as post_form

NOW = datetime(2026, 10, 30, 12)
OWNER_ID, AUTHOR_ID, OTHER_AUTHOR_ID, READER_ID, DEMO_ID = 1, 2, 3, 4, 5


def user(role, user_id, **fields):
    return User(id=user_id, role=role, is_blocked=fields.pop("is_blocked", False),
                is_demo=fields.pop("is_demo", False), **fields)


PEOPLE = {
    "visitor": None,
    "reader": user(READER, READER_ID),
    "author": user(AUTHOR, AUTHOR_ID),
    "other_author": user(AUTHOR, OTHER_AUTHOR_ID),
    "owner": user(OWNER, OWNER_ID),
    "blocked_author": user(AUTHOR, AUTHOR_ID, is_blocked=True),
    "blocked_owner": user(OWNER, OWNER_ID, is_blocked=True),
    "demo": user(AUTHOR, DEMO_ID, is_demo=True),
}


def a_post(status=PUBLISHED, published_at=NOW - timedelta(hours=1), author=None):
    author = author or PEOPLE["author"]
    return Post(id=1, author_id=author.id, author=author, status=status,
                published_at=published_at if status == PUBLISHED else None)


LIVE = a_post()
DRAFT_POST = a_post(status=DRAFT)
SCHEDULED = a_post(published_at=NOW + timedelta(hours=1))
DEMO_LIVE = a_post(author=PEOPLE["demo"])


@pytest.mark.parametrize("who,expected", [
    ("visitor", False), ("reader", False), ("author", True), ("other_author", True), ("owner", True),
    ("blocked_author", False), ("blocked_owner", False), ("demo", True),
])
def test_can_write(who, expected):
    assert can.can_write(PEOPLE[who]) is expected


@pytest.mark.parametrize("who,live,draft,scheduled,demo_live", [
    ("visitor", True, False, False, False),
    ("reader", True, False, False, False),
    ("author", True, True, True, False),
    ("other_author", True, False, False, False),
    ("owner", True, False, False, False),  # drafts are private, even from the owner
    ("blocked_author", True, False, False, False),
    ("demo", True, False, False, True),
])
def test_can_view_post(who, live, draft, scheduled, demo_live):
    person = PEOPLE[who]
    assert can.can_view_post(person, LIVE, NOW) is live
    assert can.can_view_post(person, DRAFT_POST, NOW) is draft
    assert can.can_view_post(person, SCHEDULED, NOW) is scheduled
    assert can.can_view_post(person, DEMO_LIVE, NOW) is demo_live


@pytest.mark.parametrize("who,live,draft", [
    ("visitor", False, False),
    ("reader", False, False),
    ("author", True, True),
    ("other_author", False, False),
    ("owner", False, False),  # the owner can never change somebody's words
    ("blocked_author", False, False),
    ("demo", False, False),
])
def test_can_edit_post(who, live, draft):
    assert can.can_edit_post(PEOPLE[who], LIVE) is live
    assert can.can_edit_post(PEOPLE[who], DRAFT_POST) is draft


@pytest.mark.parametrize("who,live,draft,scheduled,demo_live", [
    ("visitor", False, False, False, False),
    ("reader", False, False, False, False),
    ("author", True, True, True, False),
    ("other_author", False, False, False, False),
    ("owner", True, False, False, False),  # the owner can take down what is live, nothing else
    ("blocked_owner", False, False, False, False),
    ("demo", False, False, False, True),  # its own sandbox post, nothing real
])
def test_can_take_down_post(who, live, draft, scheduled, demo_live):
    person = PEOPLE[who]
    assert can.can_take_down_post(person, LIVE, NOW) is live
    assert can.can_take_down_post(person, DRAFT_POST, NOW) is draft
    assert can.can_take_down_post(person, SCHEDULED, NOW) is scheduled
    assert can.can_take_down_post(person, DEMO_LIVE, NOW) is demo_live


def test_a_post_scheduled_for_exactly_now_is_live():
    assert can.is_live(a_post(published_at=NOW), NOW) is True


# ---------- Comments ----------

def a_comment(writer="reader", status=APPROVED, post=LIVE, created_at=NOW, deleted_at=None):
    return Comment(id=1, user_id=PEOPLE[writer].id, post=post, status=status, created_at=created_at,
                   deleted_at=deleted_at, body="Hi")


@pytest.mark.parametrize("who,live,draft,demo_live", [
    ("visitor", False, False, False),
    ("reader", True, False, False),
    ("author", True, False, False),
    ("owner", True, False, False),
    ("blocked_author", False, False, False),
    ("demo", False, False, True),  # never on a real post
])
def test_can_comment(who, live, draft, demo_live):
    assert can.can_comment(PEOPLE[who], LIVE, NOW) is live
    assert can.can_comment(PEOPLE[who], DRAFT_POST, NOW) is draft
    assert can.can_comment(PEOPLE[who], DEMO_LIVE, NOW) is demo_live


@pytest.mark.parametrize("who,own_comment,someone_elses", [
    ("visitor", False, False), ("reader", True, False), ("owner", False, False),
])
def test_can_edit_comment_is_only_for_the_writer(who, own_comment, someone_elses):
    assert can.can_edit_comment(PEOPLE[who], a_comment("reader"), NOW) is own_comment
    assert can.can_edit_comment(PEOPLE[who], a_comment("author"), NOW) is someone_elses


def test_the_edit_window_is_15_minutes():
    reader = PEOPLE["reader"]
    assert can.can_edit_comment(reader, a_comment(created_at=NOW - timedelta(minutes=15)), NOW) is True
    assert can.can_edit_comment(reader, a_comment(created_at=NOW - timedelta(minutes=16)), NOW) is False


def test_a_removed_or_rejected_comment_cannot_be_edited():
    reader = PEOPLE["reader"]
    assert can.can_edit_comment(reader, a_comment(deleted_at=NOW), NOW) is False
    assert can.can_edit_comment(reader, a_comment(status=REJECTED), NOW) is False


@pytest.mark.parametrize("who,on_authors_post,on_other_authors_post,on_demo_post", [
    ("visitor", False, False, False),
    ("reader", False, False, False),
    ("author", True, False, False),
    ("other_author", False, True, False),
    ("owner", True, True, False),  # everything, except the sandbox
    ("blocked_owner", False, False, False),
    ("demo", False, False, True),
])
def test_can_moderate_comment(who, on_authors_post, on_other_authors_post, on_demo_post):
    person = PEOPLE[who]
    assert can.can_moderate_comment(person, a_comment(post=a_post(author=PEOPLE["author"]))) is on_authors_post
    assert can.can_moderate_comment(person, a_comment(post=a_post(author=PEOPLE["other_author"]))) is on_other_authors_post
    assert can.can_moderate_comment(person, a_comment(post=DEMO_LIVE)) is on_demo_post


@pytest.mark.parametrize("who,expected", [
    ("visitor", False), ("reader", False), ("author", True), ("other_author", True), ("owner", True),
    ("blocked_author", False),
])
def test_can_report_someone_elses_comment(who, expected):
    # The reader wrote it, so the reader is the one person who can't report it.
    assert can.can_report_comment(PEOPLE[who], a_comment("reader")) is expected


def test_cannot_report_a_hidden_comment():
    assert can.can_report_comment(PEOPLE["author"], a_comment(status=PENDING)) is False
    assert can.can_report_comment(PEOPLE["author"], a_comment(deleted_at=NOW)) is False


@pytest.mark.parametrize("who,pending,rejected", [
    ("visitor", False, False),
    ("reader", True, False),  # its writer
    ("author", True, False),  # the post's author
    ("other_author", False, False),
    ("owner", True, False),
])
def test_can_see_comment(who, pending, rejected):
    person = PEOPLE[who]
    assert can.can_see_comment(person, a_comment()) is True
    assert can.can_see_comment(person, a_comment(status=PENDING)) is pending
    assert can.can_see_comment(person, a_comment(status=REJECTED)) is rejected


def test_needs_approval_only_for_a_readers_first_comment():
    assert can.needs_approval(PEOPLE["reader"], False) is True
    assert can.needs_approval(PEOPLE["reader"], True) is False
    assert can.needs_approval(PEOPLE["author"], False) is False
    assert can.needs_approval(PEOPLE["owner"], False) is False


# ---------- The real routes ----------

@pytest.fixture
def people(app):
    return {"owner": make_user(app, "juan", OWNER), "author": make_user(app, "maria", AUTHOR),
            "other_author": make_user(app, "rosa", AUTHOR), "reader": make_user(app, "pedro", READER)}


def client_of(app, user_id):
    return log_in_as(app.test_client(), user_id)


def test_the_desk_is_for_writers(app, client, people):
    assert client.get("/desk/").status_code == 302  # a visitor goes to log in
    assert client_of(app, people["reader"]).get("/desk/").status_code == 403
    assert client_of(app, people["author"]).get("/desk/").status_code == 200
    assert client_of(app, people["owner"]).get("/desk/").status_code == 200


def test_a_reader_cannot_start_a_post(app, people):
    response = post_form(client_of(app, people["reader"]), "/desk/posts/new")
    assert response.status_code == 403


def test_another_authors_draft_gives_404_even_to_the_owner(app, people):
    draft = add_post(app, people["author"], status=DRAFT)
    for name in ("other_author", "owner"):
        client = client_of(app, people[name])
        assert client.get(f"/desk/posts/{draft}/edit").status_code == 404
        assert post_form(client, f"/desk/posts/{draft}/edit", edit_form(draft, app)).status_code == 404
        assert post_form(client, f"/desk/posts/{draft}/delete").status_code == 404
        assert post_form(client, f"/desk/posts/{draft}/unpublish").status_code == 404
    assert get_post(app, draft) is not None


def test_another_authors_live_post_gives_403_when_editing(app, people):
    live = add_post(app, people["author"], title="Original")
    for name in ("other_author", "owner"):
        client = client_of(app, people[name])
        assert client.get(f"/desk/posts/{live}/edit").status_code == 403
        form = edit_form(live, app, title="Changed by someone else")
        assert post_form(client, f"/desk/posts/{live}/edit", form).status_code == 403
    assert get_post(app, live).title == "Original"


def test_another_author_cannot_take_down_a_live_post(app, people):
    live = add_post(app, people["author"])
    client = client_of(app, people["other_author"])
    assert post_form(client, f"/desk/posts/{live}/unpublish").status_code == 403
    assert post_form(client, f"/desk/posts/{live}/delete").status_code == 403
    assert get_post(app, live).status == PUBLISHED


def test_the_owner_can_take_down_a_live_post_then_it_is_private_again(app, people):
    live = add_post(app, people["author"])
    client = client_of(app, people["owner"])
    assert post_form(client, f"/desk/posts/{live}/unpublish").status_code == 302
    assert get_post(app, live).status == DRAFT
    # It is somebody's draft now, so the owner can no longer touch it.
    assert post_form(client, f"/desk/posts/{live}/delete").status_code == 404


def test_the_owner_can_delete_a_live_post(app, people):
    live = add_post(app, people["author"])
    assert post_form(client_of(app, people["owner"]), f"/desk/posts/{live}/delete").status_code == 302
    assert get_post(app, live) is None


def test_the_sign_up_page_can_only_make_readers_and_they_get_no_desk(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = "x"
    post_form(client, "/signup", {"username": "ana", "password": "long enough",
                                  "confirm_password": "long enough", "role": OWNER})
    assert client.get("/desk/").status_code == 403
