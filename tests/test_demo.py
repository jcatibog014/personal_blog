"""The demo: a sandbox author that can never touch or reach the real site."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from akda import auth, db, seed
from akda.dates import utcnow
from akda.models import APPROVED, AUTHOR, Comment, CommentReport, Image, PENDING, Post, PostVersion, User

from .conftest import PASSWORD, add_post, edit_form, get_post, get_user, log_in_as, post as post_form


@pytest.fixture
def demo(app):
    """A browser that pressed Try Demo."""
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = "x"
    assert post_form(client, "/demo").status_code == 302
    return client


def demo_user(app):
    return get_user(app, auth.DEMO_USERNAME)


def count(app, model, *where):
    with app.app_context():
        return db.session().scalar(select(func.count()).select_from(model).where(*where))


# ---------- Starting it ----------

def test_try_demo_logs_in_as_a_sample_author_with_sample_posts(app, demo):
    user = demo_user(app)
    assert user.is_demo and user.role == AUTHOR
    assert count(app, Post, Post.author_id == user.id) == 6
    page = demo.get("/desk/").data
    assert b"Building a Small Web App" in page and b"You are in the demo" in page
    assert b"A Post From the Future" in demo.get("/desk/?tab=scheduled").data


def test_the_sample_has_something_to_moderate(app, demo):
    assert count(app, Comment, Comment.status == PENDING) == 1
    assert b"Which notebook" in demo.get("/desk/comments").data
    assert b"advert" in demo.get("/desk/comments?tab=reported").data


def test_the_demo_can_moderate_its_own_sample(app, demo):
    with app.app_context():
        waiting = db.session().scalar(select(Comment.id).where(Comment.status == PENDING))
    assert post_form(demo, f"/desk/comments/{waiting}/approve").status_code == 302
    assert count(app, Comment, Comment.status == PENDING) == 0


def test_nobody_can_log_in_as_a_demo_user(app, demo):
    for username in (auth.DEMO_USERNAME, *seed.SAMPLE_READERS):
        assert post_form(app.test_client(), "/login", {"username": username, "password": PASSWORD}).status_code == 401


def test_nobody_can_sign_up_with_a_demo_name(app, client):
    response = post_form(client, "/signup", {"username": "demo-reader-9", "password": "long enough",
                                             "confirm_password": "long enough"})
    assert response.status_code == 400


# ---------- The sandbox ----------

@pytest.mark.parametrize("url", ["/", "/tags", "/search?q=notebook", "/archive", "/feed.xml"])
def test_strangers_never_see_the_demo(app, client, demo, url):
    page = client.get(url).data
    assert b"Why I Still Write by Hand" not in page and b"Demo Writer" not in page


def test_strangers_get_404_on_demo_posts_tags_and_pictures(app, client, demo):
    assert client.get("/posts/why-i-still-write-by-hand").status_code == 404
    assert client.get("/tags/writing").status_code == 404
    with app.app_context():
        picture = db.session().scalar(select(Image.id))
    assert client.get(f"/images/{picture}").status_code == 404


def test_a_real_owner_never_sees_or_moderates_the_demo(app, demo, owner_id):
    with app.app_context():
        pending = db.session().scalar(select(Comment.id).where(Comment.status == PENDING))
    owner = log_in_as(app.test_client(), owner_id)
    assert b"Which notebook" not in owner.get("/desk/comments").data
    assert owner.get("/posts/why-i-still-write-by-hand").status_code == 404
    assert post_form(owner, f"/desk/comments/{pending}/approve").status_code == 404
    assert b"Demo Writer" not in owner.get("/desk/people").data


def test_a_demo_post_published_by_a_visitor_stays_in_the_sandbox(app, client, demo):
    with app.app_context():
        draft = db.session().scalar(select(Post.id).where(Post.status == "draft"))
    post_form(demo, f"/desk/posts/{draft}/edit", edit_form(draft, app, title="Spam For Everyone", action="publish"))
    assert b"Spam For Everyone" in demo.get("/").data
    assert b"Spam For Everyone" not in client.get("/").data
    assert client.get("/posts/spam-for-everyone").status_code == 404


def test_demo_visitors_see_real_posts_but_cannot_comment_or_change_them(app, demo, author_id):
    real = add_post(app, author_id, title="Real Post")
    assert b"Real Post" in demo.get("/").data
    assert b"can only comment on demo posts" in demo.get("/posts/real-post").data
    assert post_form(demo, f"/posts/{real}/comments", {"body": "Spam"}).status_code == 403
    assert count(app, Comment, Comment.post_id == real) == 0
    assert post_form(demo, f"/desk/posts/{real}/edit", edit_form(real, app, title="Hacked")).status_code == 403
    assert post_form(demo, f"/desk/posts/{real}/delete").status_code == 403
    assert get_post(app, real).title == "Real Post"


def test_the_demo_has_no_people_page_and_no_settings(app, demo):
    assert demo.get("/desk/people").status_code == 403
    assert post_form(demo, "/settings", {"action": "name", "display_name": "Hacked"}).status_code == 403
    assert demo_user(app).display_name == "Demo Writer"


def test_the_demo_has_a_post_limit(app, demo, monkeypatch):
    from akda.views import desk
    monkeypatch.setattr(desk, "DEMO_MAX_POSTS", 6)
    before = count(app, Post)
    response = post_form(demo, "/desk/posts/new", follow_redirects=True)
    assert b"can hold 6 posts" in response.data
    assert count(app, Post) == before


# ---------- Resetting ----------

def test_the_demo_resets_after_an_hour_and_not_before(app, demo, ctx):
    user = ctx.scalar(select(User).where(User.username == auth.DEMO_USERNAME))
    ctx.add(Post(author=user, title="Made by a visitor"))
    ctx.commit()

    auth.demo_user(ctx, user.demo_reset_at + timedelta(minutes=59))
    ctx.commit()
    assert count(app, Post, Post.title == "Made by a visitor") == 1

    auth.demo_user(ctx, user.demo_reset_at + timedelta(minutes=61))
    ctx.commit()
    assert count(app, Post, Post.title == "Made by a visitor") == 0
    assert count(app, Post, Post.author_id == user.id) == 6


def test_a_reset_leaves_nothing_behind_and_touches_nothing_real(app, demo, ctx, author_id):
    real = add_post(app, author_id, title="Real Post")
    sizes = {model: count(app, model) for model in (Post, Comment, CommentReport, Image, PostVersion, User)}
    assert sizes[CommentReport] == 1 and sizes[Image] == 4
    for _ in range(3):
        auth.demo_user(ctx, utcnow(), force_reset=True)
        ctx.commit()
    assert {model: count(app, model) for model in sizes} == sizes
    assert get_post(app, real).title == "Real Post"


def test_the_reset_command(app, demo):
    result = app.test_cli_runner().invoke(args=["reset-demo"])
    assert result.exit_code == 0, result.output
    assert count(app, Post, Post.author_id == demo_user(app).id) == 6


def test_sample_comments_are_approved_or_waiting(app, demo):
    assert count(app, Comment, Comment.status == APPROVED) == 4
