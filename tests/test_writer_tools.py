"""Autosave, version history, scheduling and pictures."""
import io
from datetime import timedelta

import pytest
from PIL import Image as PillowImage
from sqlalchemy import func, select

from akda import db, formatting, images, posts
from akda.dates import utcnow
from akda.models import AUTHOR, DRAFT, PUBLISHED, Image, Post, PostVersion, User

from .conftest import add_post, edit_form, get_post, log_in_as, make_user, post as post_form


def picture_bytes(format="PNG", size=(40, 30), **save_options):
    out = io.BytesIO()
    PillowImage.new("RGB", size, "red").save(out, format, **save_options)
    return out.getvalue()


def upload(content=None, name="photo.png"):
    return (io.BytesIO(picture_bytes() if content is None else content), name)


def count(app, model):
    with app.app_context():
        return db.session().scalar(select(func.count()).select_from(model))


def versions_of(app, post_id):
    with app.app_context():
        s = db.session()
        rows = posts.versions_of(s, s.get(Post, post_id))
        return [(version.title, version.body_md) for version in rows]


@pytest.fixture
def writer(client, author_id):
    return log_in_as(client, author_id)


@pytest.fixture
def draft(app, author_id):
    return add_post(app, author_id, title="Start", body="Start text.", status=DRAFT)


def in_future(**delta):
    """A moment in the future, as the date box sends it (in Philippine time)."""
    moment = utcnow() + timedelta(**delta)
    return moment, formatting.input_datetime(moment)


# ---------- Autosave ----------

def test_autosave_saves_a_draft_and_returns_the_new_revision(app, writer, draft):
    form = edit_form(draft, app, title="Typed", body_md="Typed **text**", tags="python")
    response = post_form(writer, f"/desk/posts/{draft}/autosave", form)
    assert response.status_code == 200
    saved = get_post(app, draft)
    assert saved.title == "Typed" and "<strong>text</strong>" in saved.body_html
    assert [tag.name for tag in saved.tags] == ["python"]
    assert response.json["revision"] == saved.revision and response.json["revision"] != form["revision"]
    assert response.json["saved"]


def test_autosave_twice_in_a_row_with_the_returned_revision(app, writer, draft):
    first = post_form(writer, f"/desk/posts/{draft}/autosave", edit_form(draft, app, title="One"))
    second = post_form(writer, f"/desk/posts/{draft}/autosave",
                       edit_form(draft, app, title="Two", revision=first.json["revision"]))
    assert second.status_code == 200 and get_post(app, draft).title == "Two"


def test_autosave_never_touches_a_live_or_scheduled_post(app, writer, author_id):
    for post_id in (add_post(app, author_id, title="Live", body="Finished."),
                    add_post(app, author_id, title="Later", body="Finished.", published_at=utcnow() + timedelta(days=1))):
        before = get_post(app, post_id).title
        response = post_form(writer, f"/desk/posts/{post_id}/autosave", edit_form(post_id, app, title="Half-writ"))
        assert response.status_code == 409
        assert get_post(app, post_id).title == before


def test_autosave_refuses_a_stale_tab(app, writer, draft):
    stale = edit_form(draft, app, title="From the old tab")
    post_form(writer, f"/desk/posts/{draft}/autosave", edit_form(draft, app, title="Newer"))
    response = post_form(writer, f"/desk/posts/{draft}/autosave", stale)
    assert response.status_code == 409 and "another tab" in response.json["error"]
    assert get_post(app, draft).title == "Newer"


def test_autosave_makes_no_version(app, writer, draft):
    post_form(writer, f"/desk/posts/{draft}/autosave", edit_form(draft, app, title="Typed"))
    assert versions_of(app, draft) == []


def test_autosave_is_only_for_the_author(app, owner_id, draft):
    owner = log_in_as(app.test_client(), owner_id)
    assert post_form(owner, f"/desk/posts/{draft}/autosave", edit_form(draft, app)).status_code == 404


def test_the_editor_only_turns_autosave_on_for_drafts(app, writer, author_id, draft):
    assert b"data-autosave-url" in writer.get(f"/desk/posts/{draft}/edit").data
    live = add_post(app, author_id)
    assert b"data-autosave-url" not in writer.get(f"/desk/posts/{live}/edit").data


# ---------- Version history ----------

def test_save_publish_and_update_each_keep_a_version(app, writer, draft):
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, body_md="One"))
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, body_md="Two", action="publish"))
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, body_md="Three", action="update"))
    assert [body for _, body in versions_of(app, draft)] == ["Three", "Two", "One"]


def test_saving_the_same_words_keeps_no_new_version(app, writer, draft):
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app))
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app))
    assert len(versions_of(app, draft)) == 1


def test_only_the_newest_versions_are_kept(app, ctx, author_id, draft):
    post = ctx.get(Post, draft)
    author = post.author
    for number in range(posts.MAX_VERSIONS + 5):
        posts.apply_content(post, {"title": "T", "summary": "", "body_md": f"Text {number}"}, utcnow())
        posts.snapshot(ctx, post, author, utcnow() + timedelta(seconds=number))
        ctx.commit()
    kept = versions_of(app, draft)
    assert len(kept) == posts.MAX_VERSIONS
    assert kept[0][1] == f"Text {posts.MAX_VERSIONS + 4}" and kept[-1][1] == "Text 5"


def test_restoring_on_a_draft_keeps_the_current_words(app, writer, draft):
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, title="Old", body_md="Old text"))
    with app.app_context():
        old_version = db.session().scalar(select(PostVersion.id))
    # This text only exists from autosave: no version holds it yet.
    post_form(writer, f"/desk/posts/{draft}/autosave", edit_form(draft, app, title="Unsaved", body_md="Unsaved text"))

    response = post_form(writer, f"/desk/posts/{draft}/versions/{old_version}/restore")
    assert response.status_code == 302
    post = get_post(app, draft)
    assert post.title == "Old" and post.body_md == "Old text"
    assert ("Unsaved", "Unsaved text") in versions_of(app, draft)  # nothing was lost


def test_restoring_on_a_live_post_changes_nothing_until_update(app, client, writer, author_id):
    live = add_post(app, author_id, title="Live", body="Old live text")
    post_form(writer, f"/desk/posts/{live}/edit", edit_form(live, app, action="update"))
    with app.app_context():
        old_version = db.session().scalar(select(PostVersion.id))
    post_form(writer, f"/desk/posts/{live}/edit", edit_form(live, app, body_md="New live text", action="update"))

    response = post_form(writer, f"/desk/posts/{live}/versions/{old_version}/restore", follow_redirects=True)
    assert b"Old live text" in response.data and b"Readers still see the current text" in response.data
    assert b"New live text" in client.get("/posts/live").data
    assert get_post(app, live).body_md == "New live text"


def test_versions_are_private_to_the_author(app, writer, owner_id, author_id, draft):
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app))
    with app.app_context():
        version = db.session().scalar(select(PostVersion.id))
    owner = log_in_as(app.test_client(), owner_id)
    assert owner.get(f"/desk/posts/{draft}/versions").status_code == 404
    assert post_form(owner, f"/desk/posts/{draft}/versions/{version}/restore").status_code == 404
    live = add_post(app, author_id, title="Live One")
    assert owner.get(f"/desk/posts/{live}/versions").status_code == 403


def test_a_version_from_another_post_gives_404(app, writer, author_id, draft):
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app))
    with app.app_context():
        version = db.session().scalar(select(PostVersion.id))
    other = add_post(app, author_id, status=DRAFT)
    assert post_form(writer, f"/desk/posts/{other}/versions/{version}/restore").status_code == 404
    assert writer.get(f"/desk/posts/{other}/versions?v={version}").status_code == 404
    assert writer.get(f"/desk/posts/{other}/edit?from_version={version}").status_code == 404


def test_the_versions_page_shows_cleaned_text(app, writer, draft):
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, body_md="**hi** <script>bad()</script>"))
    page = writer.get(f"/desk/posts/{draft}/versions").data
    assert b"<strong>hi</strong>" in page and b"<script>bad()" not in page


def test_deleting_a_post_deletes_its_versions(app, writer, draft):
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app))
    post_form(writer, f"/desk/posts/{draft}/delete")
    assert count(app, PostVersion) == 0


# ---------- Scheduling ----------

def test_publishing_with_a_future_date_schedules_it(app, writer, draft):
    moment, typed = in_future(days=2)
    response = post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, action="publish", publish_at=typed))
    assert response.status_code == 302
    post = get_post(app, draft)
    assert post.status == PUBLISHED
    assert abs(post.published_at - moment) < timedelta(minutes=1)
    assert app.test_client().get(f"/posts/{post.slug}").status_code == 404
    assert b"Start" in writer.get("/desk/?tab=scheduled").data


@pytest.mark.parametrize("typed", ["2020-01-01T10:00", "not a date"])
def test_a_past_or_broken_date_is_refused(app, writer, draft, typed):
    response = post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, action="publish", publish_at=typed))
    assert response.status_code == 400
    assert get_post(app, draft).status == DRAFT


def test_saving_a_draft_ignores_the_date_box(app, writer, draft):
    response = post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, publish_at="not a date"))
    assert response.status_code == 302


def test_a_scheduled_post_can_be_moved_or_published_now(app, client, writer, author_id):
    scheduled = add_post(app, author_id, title="Later", published_at=utcnow() + timedelta(days=1))
    moment, typed = in_future(days=5)
    post_form(writer, f"/desk/posts/{scheduled}/edit", edit_form(scheduled, app, action="update", publish_at=typed))
    assert abs(get_post(app, scheduled).published_at - moment) < timedelta(minutes=1)

    post_form(writer, f"/desk/posts/{scheduled}/edit", edit_form(scheduled, app, action="publish_now"))
    assert get_post(app, scheduled).published_at <= utcnow()
    assert client.get("/posts/later").status_code == 200


def test_updating_a_scheduled_post_without_a_date_keeps_its_date(app, writer, author_id):
    when = utcnow() + timedelta(days=1)
    scheduled = add_post(app, author_id, published_at=when)
    post_form(writer, f"/desk/posts/{scheduled}/edit", edit_form(scheduled, app, action="update", body_md="New"))
    assert get_post(app, scheduled).published_at == when


def test_a_scheduled_post_can_go_back_to_draft(app, writer, author_id):
    scheduled = add_post(app, author_id, published_at=utcnow() + timedelta(days=1))
    post_form(writer, f"/desk/posts/{scheduled}/unpublish")
    assert get_post(app, scheduled).status == DRAFT


def test_updating_a_live_post_keeps_its_date(app, writer, author_id):
    live = add_post(app, author_id)
    before = get_post(app, live).published_at
    post_form(writer, f"/desk/posts/{live}/edit", edit_form(live, app, action="update", body_md="New"))
    assert get_post(app, live).published_at == before


def test_the_owner_cannot_touch_someone_elses_scheduled_post(app, owner_id, author_id):
    scheduled = add_post(app, author_id, published_at=utcnow() + timedelta(days=1))
    owner = log_in_as(app.test_client(), owner_id)
    assert post_form(owner, f"/desk/posts/{scheduled}/unpublish").status_code == 404


# ---------- Pictures ----------

def test_process_makes_a_small_webp_without_exif():
    exif = PillowImage.Exif()
    exif[0x010E] = "Secret place"
    data, width, height = images.process(picture_bytes("JPEG", size=(3000, 1500), exif=exif))
    assert (width, height) == (images.MAX_SIDE, images.MAX_SIDE // 2)
    with PillowImage.open(io.BytesIO(data)) as result:
        assert result.format == "WEBP"
        assert not result.getexif()


@pytest.mark.parametrize("raw", [b"", b"this is not a picture", b"<svg onload=alert(1)>"])
def test_process_refuses_what_is_not_a_picture(raw):
    with pytest.raises(images.PictureError):
        images.process(raw)


def test_process_refuses_a_format_we_do_not_allow():
    with pytest.raises(images.PictureError):
        images.process(picture_bytes("BMP"))


def test_a_cover_shows_on_the_card_and_the_post_and_can_be_replaced_or_removed(app, client, writer, draft):
    data = edit_form(draft, app, action="publish", cover=upload())
    assert post_form(writer, f"/desk/posts/{draft}/edit", data, content_type="multipart/form-data").status_code == 302
    first = get_post(app, draft).cover_image_id
    picture_url = f"/images/{first}".encode()
    assert picture_url in client.get("/").data and picture_url in client.get("/posts/start").data

    data = edit_form(draft, app, action="update", cover=upload())
    post_form(writer, f"/desk/posts/{draft}/edit", data, content_type="multipart/form-data")
    second = get_post(app, draft).cover_image_id
    assert second != first and count(app, Image) == 1  # the old one is gone

    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, action="update", remove_cover="1"))
    assert get_post(app, draft).cover_image_id is None and count(app, Image) == 0


def test_a_bad_cover_changes_nothing(app, writer, draft):
    data = edit_form(draft, app, title="Changed", cover=upload(b"not a picture"))
    response = post_form(writer, f"/desk/posts/{draft}/edit", data, content_type="multipart/form-data")
    assert response.status_code == 400 and b"read" in response.data
    assert b"Changed" in response.data  # your typing is still in the form
    assert get_post(app, draft).title == "Start"


def test_deleting_a_post_deletes_its_cover(app, writer, draft):
    data = edit_form(draft, app, cover=upload())
    post_form(writer, f"/desk/posts/{draft}/edit", data, content_type="multipart/form-data")
    assert count(app, Image) == 1
    post_form(writer, f"/desk/posts/{draft}/delete")
    assert count(app, Image) == 0


def test_a_picture_for_inside_a_post(app, client, writer):
    response = post_form(writer, "/desk/images", {"picture": upload()}, content_type="multipart/form-data",
                         headers={"Accept": "application/json"})
    assert response.status_code == 200 and response.json["markdown"].startswith("![")
    picture = client.get(response.json["url"])
    assert picture.status_code == 200 and picture.mimetype == "image/webp"
    assert "immutable" in picture.headers["Cache-Control"]
    assert picture.headers["X-Content-Type-Options"] == "nosniff"


def test_uploading_without_javascript_shows_the_line_to_copy(app, writer):
    response = post_form(writer, "/desk/images", {"picture": upload()}, content_type="multipart/form-data")
    assert response.status_code == 200 and b"Copy this line" in response.data


def test_a_bad_picture_upload(app, writer):
    response = post_form(writer, "/desk/images", {"picture": upload(b"nope")}, content_type="multipart/form-data",
                         headers={"Accept": "application/json"})
    assert response.status_code == 400 and response.json["error"]
    assert post_form(writer, "/desk/images", {"picture": upload(b"nope")}, content_type="multipart/form-data").status_code == 400


def test_readers_cannot_upload(app, reader_id):
    reader = log_in_as(app.test_client(), reader_id)
    response = post_form(reader, "/desk/images", {"picture": upload()}, content_type="multipart/form-data")
    assert response.status_code == 403
    assert count(app, Image) == 0


def test_the_limit_on_pictures(app, ctx, monkeypatch):
    user_id = make_user(app, "rosa", AUTHOR)
    user = ctx.get(User, user_id)
    monkeypatch.setattr(images, "MAX_PER_USER", 1)
    images.add(ctx, user, picture_bytes())
    ctx.commit()
    with pytest.raises(images.PictureError, match="limit"):
        images.add(ctx, user, picture_bytes())


def test_demo_pictures_are_for_demo_visitors_only(app, client, ctx):
    demo_id = make_user(app, "demo-writer", AUTHOR, is_demo=True)
    image = images.add(ctx, ctx.get(User, demo_id), picture_bytes())
    ctx.commit()
    assert client.get(f"/images/{image.id}").status_code == 404
    visitor = log_in_as(app.test_client(), demo_id).get(f"/images/{image.id}")
    assert visitor.status_code == 200 and "private" in visitor.headers["Cache-Control"]


def test_a_missing_picture(client):
    assert client.get("/images/999").status_code == 404


def test_lists_do_not_load_picture_bytes(app, client, ctx, author_id):
    from sqlalchemy import event
    live = add_post(app, author_id, title="With Cover")
    post = ctx.get(Post, live)
    post.cover = images.add(ctx, post.author, picture_bytes())
    ctx.commit()

    statements = []
    listener = lambda conn, cur, statement, *rest: statements.append(statement)
    event.listen(db.engine(), "before_cursor_execute", listener)
    assert client.get("/").status_code == 200
    event.remove(db.engine(), "before_cursor_execute", listener)
    assert not any("images.data" in statement for statement in statements)
