"""The Desk: where owners and authors write. Readers get 403 on every page here."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from .. import db, permissions, posts, render, tags
from ..auth import login_required
from ..dates import utcnow
from ..models import DRAFT, PUBLISHED, Post

bp = Blueprint("desk", __name__, url_prefix="/desk")

TABS = {"drafts": "Drafts", "scheduled": "Scheduled", "published": "Published"}
STALE = "This post changed in another tab or by someone else. Copy your text, then reload the page."


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
    return render_template("desk/posts.html", tabs=TABS, tab=tab, groups=groups, shown=groups[tab])


@bp.post("/posts/new")
def new_post():
    s = db.session()
    post = Post(author=g.user)
    s.add(post)
    s.commit()
    return redirect(url_for("desk.edit_post", post_id=post.id))


@bp.route("/posts/<int:post_id>/edit", methods=["GET", "POST"])
def edit_post(post_id):
    post = editable_post(post_id)
    form = posts.blank_form(post)
    errors = {}
    status = 200
    if request.method == "POST":
        form = posts.read_form(request.form)
        action = request.form.get("action", "save")
        if action != "preview":  # the Preview button (without JavaScript) saves nothing
            errors, status = save_post(post, form, action)
            if not errors:
                return redirect(url_for("desk.edit_post", post_id=post.id))
    return render_template("desk/editor.html", post=post, form=form, errors=errors,
                           preview_html=render.to_html(form["body_md"])), status


def save_post(post, form, action):
    """Returns (errors, http status): no errors means it is saved."""
    if request.form.get("revision") != str(post.revision):
        return {"stale": STALE}, 409
    publishing = action == "publish" or post.status == PUBLISHED
    errors = posts.form_errors(form, publishing)
    if errors:
        return errors, 400
    now = utcnow()
    # Tags first: their queries must run before the post has unsaved changes, or
    # SQLAlchemy would save the post early, outside the try below.
    post.tags = tags.resolve(db.session(), tags.parse(form["tags"]))
    posts.apply_content(post, form, now)
    message = "Your draft has been saved."
    if post.status == PUBLISHED:
        message = "Your post has been updated."
    elif action == "publish":
        posts.publish(db.session(), post, now)
        message = "Your post is published."
    try:
        db.session().commit()
    except (StaleDataError, IntegrityError):  # another save got in between the check above and this one
        db.session().rollback()
        return {"stale": STALE}, 409
    flash(message)
    return {}, 200


@bp.post("/preview")
def preview():
    """Live preview: the same cleaning as the real post, so it looks the same."""
    return render.to_html(request.form.get("body_md", ""))


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
    s.delete(post)
    s.commit()
    flash("The post has been deleted.")
    return redirect(url_for("desk.my_posts") if post.author_id == g.user.id else url_for("public.home"))
