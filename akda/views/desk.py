"""The Desk: where owners and authors write. Readers get 403 on every page here."""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from .. import db, images, permissions, posts, render, tags
from ..auth import login_required
from ..dates import utcnow
from ..formatting import nice_datetime
from ..models import DRAFT, PUBLISHED, Post, PostVersion

bp = Blueprint("desk", __name__, url_prefix="/desk")

TABS = {"drafts": "Drafts", "scheduled": "Scheduled", "published": "Published"}
STALE = "This post changed in another tab or by someone else. Copy your text, then reload the page."
DEMO_MAX_POSTS = 20


@bp.before_request
@login_required
def writers_only():
    if not permissions.can_write(g.user):
        abort(403, "Only authors can use the Desk.")


def find_post(post_id):
    """A post, or 404. The next check decides between 403 and 404."""
    post = db.session().get(Post, post_id)
    if post is None:
        abort(404)
    return post


def refuse(post):
    """403 if they can see this post, 404 if they mustn't even know it exists."""
    abort(403 if permissions.can_view_post(g.user, post, utcnow()) else 404)


def editable_post(post_id):
    post = find_post(post_id)
    if not permissions.can_edit_post(g.user, post):
        refuse(post)
    return post


def removable_post(post_id):
    post = find_post(post_id)
    if not permissions.can_take_down_post(g.user, post, utcnow()):
        refuse(post)
    return post


def version_of(post, version_id):
    version = db.session().get(PostVersion, version_id)
    if version is None or version.post_id != post.id:
        abort(404)
    return version


def tab_of(post, now):
    if post.status == DRAFT:
        return "drafts"
    return "published" if permissions.is_live(post, now) else "scheduled"


@bp.get("/")
def my_posts():
    now = utcnow()
    tab = request.args.get("tab", "drafts")
    if tab not in TABS:
        abort(404)
    mine = db.session().scalars(
        select(Post).where(Post.author_id == g.user.id).order_by(Post.updated_at.desc(), Post.id.desc())
    ).all()
    groups = {name: [] for name in TABS}
    for post in mine:
        groups[tab_of(post, now)].append(post)
    # Drafts stay last-touched first. These read better by their dates.
    groups["scheduled"].sort(key=lambda post: post.published_at)
    groups["published"].sort(key=lambda post: post.published_at, reverse=True)
    return render_template("desk/posts.html", tabs=TABS, tab=tab, groups=groups, shown=groups[tab])


@bp.post("/posts/new")
def new_post():
    s = db.session()
    if g.user.is_demo and posts.count_where(s, Post.author_id == g.user.id) >= DEMO_MAX_POSTS:
        flash(f"The demo can hold {DEMO_MAX_POSTS} posts. Delete one to write another.")
        return redirect(url_for("desk.my_posts"))
    post = Post(author=g.user)
    s.add(post)
    s.commit()
    return redirect(url_for("desk.edit_post", post_id=post.id))


# ---------- The editor ----------

def show_editor(post, form, errors=None, status=200, restored_from=None):
    now = utcnow()
    return render_template(
        "desk/editor.html", post=post, form=form, errors=errors or {}, restored_from=restored_from,
        preview_html=render.to_html(form["body_md"]), is_scheduled=posts.is_scheduled(post, now),
        is_live=permissions.is_live(post, now), version_count=len(post.versions),
    ), status


@bp.route("/posts/<int:post_id>/edit", methods=["GET", "POST"])
def edit_post(post_id):
    post = editable_post(post_id)
    if request.method == "GET":
        form = posts.blank_form(post)
        restored_from = None
        version_id = request.args.get("from_version", type=int)
        if version_id:  # a live post: the old words wait in the form until you press Update
            restored_from = version_of(post, version_id)
            form.update(title=restored_from.title, summary=restored_from.summary, body_md=restored_from.body_md)
        return show_editor(post, form, restored_from=restored_from)

    form = posts.read_form(request.form)
    action = request.form.get("action", "save")
    if action == "preview":  # the Preview button (without JavaScript) saves nothing
        return show_editor(post, form)
    errors, status = save_post(post, form, action)
    if errors:
        return show_editor(post, form, errors, status)
    return redirect(url_for("desk.edit_post", post_id=post.id))


def save_post(post, form, action):
    """Returns (errors, http status): no errors means it is saved."""
    s = db.session()
    now = utcnow()
    if request.form.get("revision") != str(post.revision):
        return {"stale": STALE}, 409

    scheduled = posts.is_scheduled(post, now)
    errors = posts.form_errors(form, publishing=action == "publish" or post.status == PUBLISHED)
    when = None
    if action == "publish" or scheduled:
        when, problem = posts.read_schedule(form["publish_at"], now)
        if problem:
            errors["publish_at"] = problem
    if errors:
        return errors, 400

    # Tags first: their queries must run before the post has unsaved changes, or
    # SQLAlchemy would save the post early, outside the try below.
    post.tags = tags.resolve(s, tags.parse(form["tags"]))
    try:
        save_cover(post)
    except images.PictureError as error:
        s.rollback()
        return {"cover": str(error)}, 400
    posts.apply_content(post, form, now)
    message = "Your draft has been saved."
    if post.status == DRAFT and action == "publish":
        posts.publish(s, post, when or now)
        message = f"Your post is scheduled for {nice_datetime(when)}." if when else "Your post is published."
    elif scheduled and action == "publish_now":
        post.published_at = now
        message = "Your post is published."
    elif scheduled:
        post.published_at = when or post.published_at
        message = f"Your post is scheduled for {nice_datetime(post.published_at)}."
    elif post.status == PUBLISHED:
        message = "Your post has been updated."
    posts.snapshot(s, post, g.user, now)
    try:
        s.commit()
    except (StaleDataError, IntegrityError):  # another save got in between the check above and this one
        s.rollback()
        return {"stale": STALE}, 409
    flash(message)
    return {}, 200


def save_cover(post):
    """A new cover from the form, or none if "remove" is ticked. Raises PictureError."""
    s = db.session()
    upload = request.files.get("cover")
    old = post.cover
    if upload and upload.filename:
        post.cover = images.add(s, g.user, upload.read())
    elif request.form.get("remove_cover"):
        post.cover = None
    else:
        return
    if old is not None:
        s.delete(old)  # a cover belongs to one post, so nothing else can be using it


@bp.post("/posts/<int:post_id>/autosave")
def autosave(post_id):
    """Keep a draft's text safe while typing. It never touches a live post, because
    half-finished sentences must not reach readers, and it makes no version."""
    post = editable_post(post_id)
    if post.status != DRAFT:
        return jsonify(error="Only drafts are saved automatically."), 409
    if request.form.get("revision") != str(post.revision):
        return jsonify(error=STALE), 409
    form = posts.read_form(request.form)
    errors = posts.form_errors(form, publishing=False)
    if errors:
        return jsonify(error=next(iter(errors.values()))), 400
    s = db.session()
    now = utcnow()
    post.tags = tags.resolve(s, tags.parse(form["tags"]))
    posts.apply_content(post, form, now)
    try:
        s.commit()
    except (StaleDataError, IntegrityError):
        s.rollback()
        return jsonify(error=STALE), 409
    return jsonify(revision=post.revision, saved=nice_datetime(now))


@bp.post("/preview")
def preview():
    """Live preview: the same cleaning as the real post, so it looks the same."""
    return render.to_html(request.form.get("body_md", ""))


@bp.post("/images")
def upload_picture():
    """A picture for inside a post. JavaScript gets JSON and puts the Markdown at
    the cursor; without JavaScript, a page shows the line to copy."""
    s = db.session()
    upload = request.files.get("picture")
    wants_json = request.accept_mimetypes.best == "application/json"
    try:
        image = images.add(s, g.user, upload.read() if upload else b"")
    except images.PictureError as error:
        if wants_json:
            return jsonify(error=str(error)), 400
        abort(400, str(error))
    s.commit()
    url = url_for("public.image", image_id=image.id)
    markdown = f"![Describe the picture]({url})"
    if wants_json:
        return jsonify(url=url, markdown=markdown)
    return render_template("desk/picture_added.html", markdown=markdown, url=url)


# ---------- Version history ----------

@bp.get("/posts/<int:post_id>/versions")
def versions(post_id):
    post = editable_post(post_id)
    history = posts.versions_of(db.session(), post)
    chosen = None
    version_id = request.args.get("v", type=int)
    if version_id:
        chosen = version_of(post, version_id)
    elif history:
        chosen = history[0]
    return render_template("desk/versions.html", post=post, history=history, chosen=chosen,
                           chosen_html=render.to_html(chosen.body_md) if chosen else "")


@bp.post("/posts/<int:post_id>/versions/<int:version_id>/restore")
def restore_version(post_id, version_id):
    """Nothing is ever lost: a draft keeps its current words as a new version first.
    A live post doesn't change here at all: the old words open in the editor."""
    post = editable_post(post_id)
    version = version_of(post, version_id)
    if post.status != DRAFT:
        return redirect(url_for("desk.edit_post", post_id=post.id, from_version=version.id))
    s = db.session()
    now = utcnow()
    posts.snapshot(s, post, g.user, now)
    posts.apply_content(post, {"title": version.title, "summary": version.summary, "body_md": version.body_md}, now)
    s.commit()
    flash("The older version is back. Your previous text is kept in the history.")
    return redirect(url_for("desk.edit_post", post_id=post.id))


# ---------- Taking a post down ----------

@bp.post("/posts/<int:post_id>/unpublish")
def unpublish_post(post_id):
    post = removable_post(post_id)
    posts.unpublish(post)
    db.session().commit()
    flash("The post is no longer public.")
    return redirect(url_for("desk.edit_post", post_id=post.id)
                    if permissions.can_edit_post(g.user, post) else url_for("public.home"))


@bp.post("/posts/<int:post_id>/delete")
def delete_post(post_id):
    post = removable_post(post_id)
    s = db.session()
    cover = post.cover
    s.delete(post)
    if cover is not None:
        s.delete(cover)
    s.commit()
    flash("The post has been deleted.")
    return redirect(url_for("desk.my_posts") if post.author_id == g.user.id else url_for("public.home"))
