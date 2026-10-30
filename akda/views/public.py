"""The pages everyone can see."""
from flask import Blueprint, abort, g, render_template, request
from sqlalchemy import select

from .. import comments, db, permissions, posts
from ..dates import utcnow
from ..models import Post

bp = Blueprint("public", __name__)


def page_number():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        abort(404)
    return page


@bp.get("/")
def home():
    now = utcnow()
    page = page_number()
    featured, grid, pages = posts.home_page(db.session(), g.user, now, page)
    if page > pages:
        abort(404)
    return render_template("home.html", featured=featured, grid=grid, page=page, pages=pages)


@bp.get("/posts/<slug>")
def show_post(slug):
    now = utcnow()
    post = db.session().scalar(select(Post).where(Post.slug == slug))
    # 404, not 403: a stranger must not learn that a hidden post exists.
    if post is None or not permissions.can_view_post(g.user, post, now):
        abort(404)
    s = db.session()
    return render_template(
        "post.html", post=post, now=now, is_live=permissions.is_live(post, now),
        thread=comments.thread(s, post, g.user), comment_count=comments.public_count(s, post),
        already_reported=comments.reported_by(s, g.user, post),
    )


@bp.get("/healthz")
def healthz():
    return "ok"
