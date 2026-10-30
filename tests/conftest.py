import os
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload, undefer

from akda import auth, create_app, db, posts, tags
from akda.dates import utcnow
from akda.models import AUTHOR, OWNER, PUBLISHED, READER, Post, User

# Tests use a fresh SQLite file per test. To check everything on PostgreSQL
# too, set TEST_DATABASE_URL to an EMPTY Neon branch (its tables are dropped
# and made again for every test, so never point it at the live database).
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

CSRF = "test-csrf-token"
PASSWORD = "correct horse"


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATABASE": str(tmp_path / "test.sqlite"),
        "DATABASE_URL": TEST_DATABASE_URL,
    })
    with app.app_context():
        if TEST_DATABASE_URL:
            db.drop_tables()
        db.create_tables()
    return app


@pytest.fixture
def ctx(app):
    """An app context, for tests that use db.session() directly."""
    with app.app_context():
        yield db.session()


@pytest.fixture
def client(app):
    client = app.test_client()
    # Every POST needs the session's CSRF token. Put a known one in the session.
    with client.session_transaction() as session:
        session["csrf"] = CSRF
    return client


def post(client, url, data=None, **kwargs):
    """POST a form with the right CSRF token, like a real page would."""
    # Logging in or out starts a new session (and a new token), so set it every time.
    with client.session_transaction() as session:
        session["csrf"] = CSRF
    return client.post(url, data={"csrf_token": CSRF, **(data or {})}, **kwargs)


def make_user(app, username, role=READER, **fields):
    """Put a user straight into the database. Returns the id."""
    with app.app_context():
        s = db.session()
        user = auth.create_user(s, username, PASSWORD, role=role)
        for name, value in fields.items():
            setattr(user, name, value)
        s.commit()
        return user.id


def log_in_as(client, user_id):
    """Skip the login form: put the user straight into the session."""
    with client.application.app_context():
        version = db.session().get(User, user_id).session_version
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["session_version"] = version
        session["csrf"] = CSRF
    return client


def is_logged_in(client):
    """The real check: load_user() runs on every request and drops a session that
    is no longer valid, so ask after a request what is left in the cookie."""
    client.get("/")
    with client.session_transaction() as session:
        return "user_id" in session


def get_user(app, username):
    with app.app_context():
        return db.session().scalar(select(User).where(User.username == username))


HOUR = timedelta(hours=1)


def add_post(app, author_id, title="A Post", body="Some text.", summary="", status=PUBLISHED, published_at=None,
             tag_names=(), **fields):
    """Put a post straight into the database. Published an hour ago unless told
    otherwise. Returns the id."""
    with app.app_context():
        s = db.session()
        post = Post(author_id=author_id, **fields)
        s.add(post)
        with s.no_autoflush:
            post.tags = tags.resolve(s, list(tag_names))
            posts.apply_content(post, {"title": title, "summary": summary, "body_md": body}, utcnow())
            if status == PUBLISHED:
                posts.publish(s, post, published_at or utcnow() - HOUR)
        s.commit()
        return post.id


def get_post(app, post_id):
    with app.app_context():
        return db.session().scalar(
            select(Post).where(Post.id == post_id).options(
                undefer(Post.body_md), undefer(Post.body_html), selectinload(Post.tags)))


def edit_form(post_id, app, **fields):
    """What the editor sends, with the right revision."""
    post = get_post(app, post_id)
    return {"revision": post.revision, "title": post.title, "summary": post.summary,
            "body_md": post.body_md, "tags": ", ".join(tag.name for tag in post.tags), "action": "save", **fields}


@pytest.fixture
def owner_id(app):
    return make_user(app, "juan", OWNER)


@pytest.fixture
def author_id(app):
    return make_user(app, "maria", AUTHOR)


@pytest.fixture
def reader_id(app):
    return make_user(app, "pedro", READER)
