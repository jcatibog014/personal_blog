"""Writing, saving, publishing and showing posts."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from akda import db, posts
from akda.dates import utcnow
from akda.models import DRAFT, PUBLISHED, Post

from .conftest import add_post, edit_form, get_post, log_in_as, make_user, post as post_form


@pytest.fixture
def writer(client, author_id):
    return log_in_as(client, author_id)


def test_new_post_starts_as_a_draft_and_opens_the_editor(app, writer, author_id):
    response = post_form(writer, "/desk/posts/new")
    assert response.status_code == 302 and "/edit" in response.headers["Location"]
    with app.app_context():
        post = db.session().scalar(select(Post))
        assert post.status == DRAFT and post.author_id == author_id and post.slug is None
    assert writer.get(response.headers["Location"]).status_code == 200


def test_saving_a_draft_keeps_it_private(app, writer, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    response = post_form(writer, f"/desk/posts/{draft}/edit",
                         edit_form(draft, app, title="My Thoughts", body_md="## Hi\n\nText"))
    assert response.status_code == 302
    saved = get_post(app, draft)
    assert saved.title == "My Thoughts"
    assert ">Hi</h2>" in saved.body_html
    assert saved.status == DRAFT and saved.slug is None


def test_a_draft_may_be_unfinished_but_a_published_post_may_not(app, writer, author_id):
    draft = add_post(app, author_id, title="", body="", status=DRAFT)
    assert post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app)).status_code == 302
    response = post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, action="publish"))
    assert response.status_code == 400
    assert b"needs a title" in response.data and b"needs some text" in response.data
    assert get_post(app, draft).status == DRAFT


def test_publish_sets_the_date_and_the_slug(app, writer, author_id):
    draft = add_post(app, author_id, title="Kumusta, Mundo!", status=DRAFT)
    before = utcnow()
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, action="publish"))
    post = get_post(app, draft)
    assert post.status == PUBLISHED and post.slug == "kumusta-mundo"
    assert post.published_at >= before.replace(microsecond=0)
    assert writer.get("/posts/kumusta-mundo").status_code == 200


def test_the_link_stays_when_the_title_changes(app, writer, author_id):
    live = add_post(app, author_id, title="First Title")
    response = post_form(writer, f"/desk/posts/{live}/edit",
                         edit_form(live, app, title="A New Title", action="update"))
    assert response.status_code == 302
    post = get_post(app, live)
    assert post.title == "A New Title" and post.slug == "first-title"


def test_an_update_goes_live_and_must_stay_complete(app, writer, author_id):
    live = add_post(app, author_id)
    assert post_form(writer, f"/desk/posts/{live}/edit", edit_form(live, app, body_md="", action="update")).status_code == 400
    post_form(writer, f"/desk/posts/{live}/edit", edit_form(live, app, body_md="Better text.", action="update"))
    assert b"Better text." in writer.get(f"/posts/{get_post(app, live).slug}").data


def test_slugs_never_clash(app, author_id):
    first = add_post(app, author_id, title="Same Title")
    second = add_post(app, author_id, title="Same Title")
    third = add_post(app, author_id, title="Same Title")
    assert [get_post(app, i).slug for i in (first, second, third)] == ["same-title", "same-title-2", "same-title-3"]


@pytest.mark.parametrize("title,slug", [
    ("Kumusta, Mundo!", "kumusta-mundo"), ("Piña Colada", "pina-colada"), ("  --  ", "post"), ("日本語", "post"),
])
def test_slugify(title, slug):
    assert posts.slugify(title) == slug


def test_too_long_fields_are_refused(app, writer, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    response = post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, title="x" * 201))
    assert response.status_code == 400


def test_the_preview_button_saves_nothing(app, writer, author_id):
    draft = add_post(app, author_id, title="Keep", status=DRAFT)
    response = post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, title="Not saved",
                                                                        body_md="**bold**", action="preview"))
    assert response.status_code == 200 and b"<strong>bold</strong>" in response.data
    assert get_post(app, draft).title == "Keep"


def test_live_preview_is_cleaned_and_only_for_writers(app, writer, reader_id):
    response = post_form(writer, "/desk/preview", {"body_md": "**hi** <script>bad()</script>"})
    assert b"<strong>hi</strong>" in response.data and b"<script>" not in response.data
    reader_client = log_in_as(app.test_client(), reader_id)
    assert post_form(reader_client, "/desk/preview", {"body_md": "x"}).status_code == 403


def test_a_stale_tab_cannot_overwrite_newer_text(app, writer, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    old_tab = edit_form(draft, app, title="From the old tab")
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, title="From the new tab"))
    response = post_form(writer, f"/desk/posts/{draft}/edit", old_tab)
    assert response.status_code == 409
    assert b"changed in another tab" in response.data
    assert b"From the old tab" in response.data  # your typing is still in the form
    assert get_post(app, draft).title == "From the new tab"


def test_unpublish_and_publish_again_keeps_the_link(app, writer, author_id):
    live = add_post(app, author_id, title="Hello")
    post_form(writer, f"/desk/posts/{live}/unpublish")
    post = get_post(app, live)
    assert post.status == DRAFT and post.published_at is None
    post_form(writer, f"/desk/posts/{live}/edit", edit_form(live, app, action="publish"))
    assert get_post(app, live).slug == "hello"


def test_my_posts_shows_only_mine_in_the_right_tabs(app, writer, author_id, owner_id):
    add_post(app, author_id, title="My Draft", status=DRAFT)
    add_post(app, author_id, title="My Live Post")
    add_post(app, author_id, title="My Future Post", published_at=utcnow() + timedelta(days=1))
    add_post(app, owner_id, title="Not My Post")
    assert b"My Draft" in writer.get("/desk/").data
    assert b"My Live Post" not in writer.get("/desk/?tab=drafts").data
    assert b"My Live Post" in writer.get("/desk/?tab=published").data
    assert b"My Future Post" in writer.get("/desk/?tab=scheduled").data
    assert b"Not My Post" not in writer.get("/desk/?tab=published").data
    assert writer.get("/desk/?tab=nonsense").status_code == 404


# ---------- Public pages ----------

def test_home_shows_only_live_posts(app, client, author_id):
    add_post(app, author_id, title="Live One")
    add_post(app, author_id, title="Secret Draft", status=DRAFT)
    add_post(app, author_id, title="Future Post", published_at=utcnow() + timedelta(days=1))
    page = client.get("/").data
    assert b"Live One" in page
    assert b"Secret Draft" not in page and b"Future Post" not in page


def test_the_demos_posts_are_hidden_from_everyone_else(app, client):
    demo = make_user(app, "demo-writer", "author", is_demo=True)
    add_post(app, demo, title="Sandbox Post")
    assert b"Sandbox Post" not in client.get("/").data
    assert client.get("/posts/sandbox-post").status_code == 404
    demo_client = log_in_as(app.test_client(), demo)
    assert b"Sandbox Post" in demo_client.get("/").data
    assert demo_client.get("/posts/sandbox-post").status_code == 200


def test_a_scheduled_post_goes_live_by_itself(app, client, author_id):
    moment = utcnow() + timedelta(days=1)
    add_post(app, author_id, title="Soon", published_at=moment)
    with app.app_context():
        s = db.session()
        assert posts.home_page(s, None, moment - timedelta(seconds=1), 1)[0] is None
        assert posts.home_page(s, None, moment, 1)[0].title == "Soon"
    assert client.get("/posts/soon").status_code == 404


def test_hidden_posts_give_404_to_strangers_but_open_for_the_author(app, client, author_id):
    live = add_post(app, author_id, title="Going Away")
    post_form(log_in_as(app.test_client(), author_id), f"/desk/posts/{live}/unpublish")
    assert client.get("/posts/going-away").status_code == 404
    author = log_in_as(app.test_client(), author_id)
    response = author.get("/posts/going-away")
    assert response.status_code == 200 and b"Only you can see this" in response.data


def test_home_pages(app, client, author_id):
    for number in range(posts.GRID_SIZE + 2):  # 1 banner + 12 cards + 1 on page 2
        add_post(app, author_id, title=f"Number {number}",
                 published_at=utcnow() - timedelta(days=number + 1))
    first = client.get("/").data
    assert b"Number 0<" in first and b"Page 1 of 2" in first
    last_title = f"Number {posts.GRID_SIZE + 1}<".encode()
    assert last_title not in first
    assert last_title in client.get("/?page=2").data
    assert client.get("/?page=3").status_code == 404
    assert client.get("/?page=0").status_code == 404


def test_the_post_page_shows_clean_html(app, client, author_id):
    add_post(app, author_id, title="Attack", body="<script>bad()</script>\n\n[x](javascript:bad())")
    page = client.get("/posts/attack").data
    assert b"<script>bad()" not in page and b'href="javascript' not in page


def test_titles_are_escaped(app, client, author_id):
    add_post(app, author_id, title="<b>Bold</b> Title")
    assert b"&lt;b&gt;Bold&lt;/b&gt; Title" in client.get("/").data
