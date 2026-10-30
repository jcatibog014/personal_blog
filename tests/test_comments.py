"""Comments: approval, replies, editing, reports and the queue."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from akda import comments, db, permissions
from akda.dates import utcnow
from akda.models import APPROVED, AUTHOR, DRAFT, PENDING, REJECTED, Comment, CommentReport

from .conftest import add_post, log_in_as, make_user, post as post_form


def get_comment(app, comment_id):
    with app.app_context():
        return db.session().get(Comment, comment_id)


def add_comment(app, post_id, user_id, body="Nice post.", status=APPROVED, **fields):
    with app.app_context():
        s = db.session()
        comment = Comment(post_id=post_id, user_id=user_id, body=body, status=status, **fields)
        s.add(comment)
        s.commit()
        return comment.id


def all_comments(app):
    with app.app_context():
        return db.session().scalars(select(Comment).order_by(Comment.id)).all()


@pytest.fixture
def live(app, author_id):
    return add_post(app, author_id, title="Hello")


@pytest.fixture
def reader(app, reader_id):
    return log_in_as(app.test_client(), reader_id)


@pytest.fixture
def author(app, author_id):
    return log_in_as(app.test_client(), author_id)


def write(client, post_id, body="Nice post.", **data):
    return post_form(client, f"/posts/{post_id}/comments", {"body": body, **data})


# ---------- Writing ----------

def test_visitors_cannot_comment_and_are_invited_to_log_in(app, client, live):
    response = write(client, live)
    assert response.status_code == 302 and "/login" in response.headers["Location"]
    assert all_comments(app) == []
    assert b"to join the conversation" in client.get("/posts/hello").data


def test_a_readers_first_comment_waits(app, client, reader, live):
    write(reader, live, "My first comment")
    comment = all_comments(app)[0]
    assert comment.status == PENDING
    assert b"My first comment" not in client.get("/posts/hello").data  # strangers can't see it
    page = reader.get("/posts/hello").data  # its writer can
    assert b"My first comment" in page and b"Waiting for approval" in page


def test_after_one_approval_a_readers_comments_appear_at_once(app, reader, reader_id, live):
    add_comment(app, live, reader_id)
    write(reader, live, "My second comment")
    assert all_comments(app)[-1].status == APPROVED


def test_a_rejected_comment_does_not_earn_trust(app, reader, reader_id, live):
    add_comment(app, live, reader_id, status=REJECTED)
    write(reader, live, "Trying again")
    assert all_comments(app)[-1].status == PENDING


def test_authors_are_approved_at_once(app, author, live):
    write(author, live)
    assert all_comments(app)[0].status == APPROVED


def test_comments_are_plain_text(app, client, author, live):
    write(author, live, "<script>bad()</script> **not bold** [x](javascript:bad())")
    page = client.get("/posts/hello").data
    assert b"&lt;script&gt;bad()" in page and b"<script>bad()" not in page
    assert b"**not bold**" in page and b'href="javascript' not in page


def test_an_empty_or_huge_comment_is_refused(app, author, live):
    write(author, live, "   ")
    write(author, live, "x" * (comments.BODY_MAX_LENGTH + 1))
    assert all_comments(app) == []


def test_no_comments_on_a_draft_or_a_scheduled_post(app, author, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    future = add_post(app, author_id, published_at=utcnow() + timedelta(days=1))
    assert write(author, draft).status_code == 403
    assert write(author, future).status_code == 403


def test_a_stranger_gets_404_on_a_hidden_post(app, reader, author_id):
    draft = add_post(app, author_id, status=DRAFT)
    assert write(reader, draft).status_code == 404
    assert write(reader, 9999).status_code == 404


def test_the_rate_limit(app, author, live):
    for number in range(comments.RATE_LIMIT + 1):
        write(author, live, f"Comment {number}")
    assert len(all_comments(app)) == comments.RATE_LIMIT
    assert b"very quickly" in author.get("/posts/hello").data


def test_the_owner_has_no_rate_limit(app, owner_id, live):
    owner = log_in_as(app.test_client(), owner_id)
    for number in range(comments.RATE_LIMIT + 1):
        write(owner, live, f"Comment {number}")
    assert len(all_comments(app)) == comments.RATE_LIMIT + 1


# ---------- Replies ----------

def test_a_reply_hangs_under_its_comment(app, author, reader_id, live):
    top = add_comment(app, live, reader_id)
    write(author, live, "A reply", parent_id=top)
    assert all_comments(app)[-1].parent_id == top


def test_a_reply_to_a_reply_joins_the_same_thread(app, author, reader_id, live):
    top = add_comment(app, live, reader_id)
    reply = add_comment(app, live, reader_id, parent_id=top)
    write(author, live, "Deeper", parent_id=reply)
    assert all_comments(app)[-1].parent_id == top


def test_cannot_reply_to_a_comment_on_another_post_or_a_hidden_one(app, author, author_id, reader_id, live):
    other = add_post(app, author_id, title="Other")
    elsewhere = add_comment(app, other, reader_id)
    waiting = add_comment(app, live, reader_id, status=PENDING)
    removed = add_comment(app, live, reader_id, deleted_at=utcnow())
    before = len(all_comments(app))
    for parent in (elsewhere, waiting, removed, 9999):
        write(author, live, "Bad parent", parent_id=parent)
    assert len(all_comments(app)) == before


def test_a_removed_comment_stays_as_a_placeholder_only_if_it_has_replies(app, client, reader_id, live):
    with_reply = add_comment(app, live, reader_id, body="Gone with reply", deleted_at=utcnow())
    add_comment(app, live, reader_id, body="The reply", parent_id=with_reply)
    add_comment(app, live, reader_id, body="Gone alone", deleted_at=utcnow())
    page = client.get("/posts/hello").data
    assert b"This comment was removed." in page and b"The reply" in page
    assert b"Gone with reply" not in page and b"Gone alone" not in page
    assert page.count(b"This comment was removed.") == 1


# ---------- Editing and removing ----------

def test_editing_within_the_window_shows_the_edited_label(app, client, reader, reader_id, live):
    comment = add_comment(app, live, reader_id, created_at=utcnow())
    response = post_form(reader, f"/comments/{comment}/edit", {"body": "Changed"})
    assert response.status_code == 302
    page = client.get("/posts/hello").data
    assert b"Changed" in page and b"edited" in page


def test_saving_the_same_text_is_not_an_edit(app, reader, reader_id, live):
    comment = add_comment(app, live, reader_id, created_at=utcnow(), body="Same")
    post_form(reader, f"/comments/{comment}/edit", {"body": "Same"})
    assert get_comment(app, comment).edited_at is None


def test_no_editing_after_the_window(app, reader, reader_id, live):
    late = utcnow() - permissions.COMMENT_EDIT_WINDOW - timedelta(minutes=1)
    comment = add_comment(app, live, reader_id, created_at=late, body="Original")
    assert post_form(reader, f"/comments/{comment}/edit", {"body": "Spam"}).status_code == 403
    assert get_comment(app, comment).body == "Original"


def test_nobody_edits_someone_elses_comment(app, owner_id, author, reader_id, live):
    comment = add_comment(app, live, reader_id, created_at=utcnow(), body="Original")
    owner = log_in_as(app.test_client(), owner_id)
    assert post_form(author, f"/comments/{comment}/edit", {"body": "Changed"}).status_code == 403
    assert post_form(owner, f"/comments/{comment}/edit", {"body": "Changed"}).status_code == 403
    assert get_comment(app, comment).body == "Original"


def test_writers_and_moderators_can_remove_others_cannot(app, owner_id, reader, reader_id, author, live):
    stranger = log_in_as(app.test_client(), make_user(app, "stranger"))
    other_author = log_in_as(app.test_client(), make_user(app, "rosa", AUTHOR))
    owner = log_in_as(app.test_client(), owner_id)
    for client in (reader, author, owner):
        comment = add_comment(app, live, reader_id)
        assert post_form(client, f"/comments/{comment}/delete").status_code == 302
        assert get_comment(app, comment).deleted_at is not None
    comment = add_comment(app, live, reader_id)
    for client in (stranger, other_author):
        assert post_form(client, f"/comments/{comment}/delete").status_code == 403
    assert get_comment(app, comment).deleted_at is None


# ---------- Reports ----------

def test_one_report_per_person(app, author, reader_id, live):
    comment = add_comment(app, live, reader_id)
    for _ in range(2):
        assert post_form(author, f"/comments/{comment}/report", {"reason": "Rude"}).status_code == 302
    with app.app_context():
        assert len(db.session().scalars(select(CommentReport)).all()) == 1
    assert b"Reported" in author.get("/posts/hello").data


def test_you_cannot_report_your_own_comment(app, reader, reader_id, live):
    comment = add_comment(app, live, reader_id)
    assert post_form(reader, f"/comments/{comment}/report").status_code == 403


def test_a_stranger_cannot_report_a_comment_they_cannot_see(app, author, reader_id, live):
    waiting = add_comment(app, live, reader_id, status=PENDING)
    other_reader = log_in_as(app.test_client(), make_user(app, "stranger"))
    assert post_form(other_reader, f"/comments/{waiting}/report").status_code == 404


# ---------- The queue ----------

def test_the_queue_is_for_writers_and_shows_only_their_posts(app, owner_id, author, author_id, reader, reader_id, live):
    other_author = make_user(app, "rosa", AUTHOR)
    other_post = add_post(app, other_author, title="Rosas Post")
    add_comment(app, live, reader_id, body="On Marias post", status=PENDING)
    add_comment(app, other_post, reader_id, body="On Rosas post", status=PENDING)

    assert reader.get("/desk/comments").status_code == 403
    page = author.get("/desk/comments").data
    assert b"On Marias post" in page and b"On Rosas post" not in page
    owner_page = log_in_as(app.test_client(), owner_id).get("/desk/comments").data
    assert b"On Marias post" in owner_page and b"On Rosas post" in owner_page


def test_reject_is_a_red_outline_and_approve_is_green_and_last(app, author, reader_id, live):
    add_comment(app, live, reader_id, status=PENDING)
    page = author.get("/desk/comments").data
    reject, approve = page.index(b"button-danger"), page.index(b"button-positive")
    assert reject < approve  # the main button of a row is last on the right


def test_a_post_back_in_draft_leaves_the_owners_queue(app, owner_id, author, reader_id, live):
    """Its title is private again, even from the owner. Only its author still sees it."""
    waiting = add_comment(app, live, reader_id, body="Still waiting", status=PENDING)
    approved = add_comment(app, live, reader_id, body="Already approved")
    owner = log_in_as(app.test_client(), owner_id)
    assert b"Hello" in owner.get("/desk/comments").data
    post_form(author, f"/desk/posts/{live}/unpublish")

    for tab in ("waiting", "recent"):
        assert b"Hello" not in owner.get(f"/desk/comments?tab={tab}").data
    assert b"Comments (1)" not in owner.get("/desk/comments").data
    assert post_form(owner, f"/desk/comments/{waiting}/approve").status_code == 404
    assert post_form(owner, f"/desk/comments/{approved}/reject").status_code == 404
    assert post_form(owner, f"/comments/{approved}/delete").status_code == 404
    assert b"Still waiting" in author.get("/desk/comments").data


def test_approve_and_reject(app, client, author, reader_id, live):
    first = add_comment(app, live, reader_id, body="Good one", status=PENDING)
    second = add_comment(app, live, reader_id, body="Bad one", status=PENDING)
    post_form(author, f"/desk/comments/{first}/approve", {"back": "waiting"})
    post_form(author, f"/desk/comments/{second}/reject", {"back": "waiting"})
    page = client.get("/posts/hello").data
    assert b"Good one" in page and b"Bad one" not in page
    assert b"Comments (1)" in page


def test_only_the_posts_author_or_the_owner_moderates(app, reader, reader_id, live):
    comment = add_comment(app, live, reader_id, status=PENDING)
    other_author = log_in_as(app.test_client(), make_user(app, "rosa", AUTHOR))
    # A waiting comment on someone else's post isn't yours to know about.
    assert post_form(other_author, f"/desk/comments/{comment}/approve").status_code == 404
    assert post_form(reader, f"/desk/comments/{comment}/approve").status_code == 404
    assert get_comment(app, comment).status == PENDING


def test_reported_tab_and_keeping_or_removing(app, author, reader_id, live):
    keep = add_comment(app, live, reader_id, body="Keep me")
    drop = add_comment(app, live, reader_id, body="Drop me")
    other_reader = log_in_as(app.test_client(), make_user(app, "stranger"))
    post_form(other_reader, f"/comments/{keep}/report", {"reason": "Not sure"})
    post_form(other_reader, f"/comments/{drop}/report", {"reason": "Rude"})
    page = author.get("/desk/comments?tab=reported").data
    assert b"Keep me" in page and b"Rude" in page

    post_form(author, f"/desk/comments/{keep}/dismiss", {"back": "reported"})
    post_form(author, f"/comments/{drop}/delete", {"back": "reported"})
    page = author.get("/desk/comments?tab=reported").data
    assert b"Keep me" not in page and b"Drop me" not in page
    assert get_comment(app, keep).deleted_at is None
    assert get_comment(app, drop).deleted_at is not None


def test_deleting_a_post_deletes_its_comments_and_reports(app, author, reader_id, live):
    comment = add_comment(app, live, reader_id)
    add_comment(app, live, reader_id, parent_id=comment)
    post_form(log_in_as(app.test_client(), make_user(app, "stranger")), f"/comments/{comment}/report")
    assert post_form(author, f"/desk/posts/{live}/delete").status_code == 302
    with app.app_context():
        assert db.session().scalars(select(Comment)).all() == []
        assert db.session().scalars(select(CommentReport)).all() == []


def test_the_post_page_needs_no_query_per_comment(app, client, reader_id, live):
    from sqlalchemy import event

    def count_queries():
        with app.app_context():
            engine = db.engine()
        statements = []
        listener = lambda conn, cur, statement, *rest: statements.append(statement)
        event.listen(engine, "before_cursor_execute", listener)
        assert client.get("/posts/hello").status_code == 200
        event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    add_comment(app, live, reader_id)
    few = count_queries()
    for number in range(10):
        add_comment(app, live, make_user(app, f"reader{number}"), body=f"Comment {number}")
    assert count_queries() == few
