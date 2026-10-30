"""The editor's page: a quiet start, and what the keyboard is allowed to press.

What the keys really do is checked in a real browser. These check what the page
tells app.js, because that decides whether Ctrl+S can reach readers.
"""
import re
from datetime import timedelta

import pytest

from akda import posts
from akda.dates import utcnow
from akda.models import DRAFT

from .conftest import add_post, edit_form, get_post, log_in_as, post as post_form


@pytest.fixture
def writer(client, author_id):
    return log_in_as(client, author_id)


def buttons_with_shortcut(page, name):
    """The values of the buttons this keyboard shortcut would press."""
    found = []
    for tag in re.findall(rb"<button[^>]*data-shortcut[^>]*>", page):
        shortcut = re.search(rb'data-shortcut="([^"]*)"', tag).group(1).split()
        if name in shortcut:
            found.append(re.search(rb'value="([^"]*)"', tag).group(1))
    return found


# ---------- What the keyboard may press ----------

def test_on_a_draft_ctrl_s_saves_and_ctrl_enter_publishes_after_asking(app, writer, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    page = writer.get(f"/desk/posts/{draft}/edit").data
    assert buttons_with_shortcut(page, b"save") == [b"save"]
    assert buttons_with_shortcut(page, b"publish") == [b"publish"]
    assert b'data-shortcut="publish" data-shortcut-confirm' in page


def test_on_a_live_post_ctrl_s_presses_nothing(app, writer, author_id):
    """It is a habit, and it must never put half-finished words in front of readers."""
    live = add_post(app, author_id)
    page = writer.get(f"/desk/posts/{live}/edit").data
    assert buttons_with_shortcut(page, b"save") == []
    assert buttons_with_shortcut(page, b"publish") == [b"update"]
    assert b'data-shortcut="publish" data-shortcut-confirm' in page


def test_on_a_scheduled_post_both_update_because_readers_cannot_see_it_yet(app, writer, author_id):
    scheduled = add_post(app, author_id, published_at=utcnow() + timedelta(days=1))
    page = writer.get(f"/desk/posts/{scheduled}/edit").data
    assert buttons_with_shortcut(page, b"save") == [b"update"]
    assert buttons_with_shortcut(page, b"publish") == [b"update"]
    assert b"data-shortcut-confirm" not in page
    assert b'value="publish_now" data-shortcut' not in page  # never by keyboard


# ---------- A quiet start ----------

def test_post_details_start_closed_with_the_fields_inside(app, writer, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    page = writer.get(f"/desk/posts/{draft}/edit").data
    assert b'<details class="editor-details">' in page
    details = page[page.index(b"editor-details"):page.index(b"</details>", page.index(b"editor-details"))]
    for name in (b'name="summary"', b'name="tags"', b'name="publish_at"', b'name="cover"'):
        assert name in details, name
    assert b'name="title"' not in details and b'name="body_md"' not in details


def test_post_details_mention_the_date_only_when_it_can_be_used(app, writer, author_id):
    live = add_post(app, author_id)
    draft = add_post(app, author_id, status=DRAFT)
    assert b"Summary, tags and cover" in writer.get(f"/desk/posts/{live}/edit").data
    assert b"Summary, tags, date and cover" in writer.get(f"/desk/posts/{draft}/edit").data


@pytest.mark.parametrize("fields", [
    {"tags": "a,b,c,d,e,f"},
    {"summary": "x" * (posts.SUMMARY_MAX_LENGTH + 1)},
    {"action": "publish", "publish_at": "not a date"},
])
def test_post_details_open_by_themselves_when_a_field_inside_has_a_problem(app, writer, author_id, fields):
    draft = add_post(app, author_id, status=DRAFT)
    response = post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, **fields))
    assert response.status_code == 400
    assert b'<details class="editor-details" open>' in response.data


def test_a_problem_with_the_title_leaves_post_details_closed(app, writer, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    response = post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, title="x" * 201))
    assert response.status_code == 400
    assert b'<details class="editor-details">' in response.data


# ---------- Word count and reading time ----------

def test_the_live_count_uses_the_same_speed_as_the_server(app, writer, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    page = writer.get(f"/desk/posts/{draft}/edit").data
    assert f'data-words-per-minute="{posts.WORDS_PER_MINUTE}"'.encode() in page


@pytest.mark.parametrize("words,minutes", [(0, 1), (1, 1), (200, 1), (201, 2), (400, 2), (401, 3)])
def test_reading_time_comes_from_the_word_count(words, minutes):
    assert posts.reading_minutes(" ".join(["word"] * words)) == minutes


def test_saving_updates_the_reading_time_on_the_post(app, writer, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, body_md="word " * 450))
    assert get_post(app, draft).reading_minutes == 3


# ---------- RSS ----------

def test_the_footer_has_an_rss_icon(client):
    page = client.get("/about").data
    footer = page[page.index(b"site-footer"):]
    assert b'class="rss-link" href="/feed.xml"' in footer and b"<svg" in footer
