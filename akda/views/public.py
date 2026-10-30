"""The pages everyone can see."""
from datetime import UTC
from email.utils import format_datetime

from flask import Blueprint, Response, abort, g, render_template, request, url_for
from sqlalchemy import select

from .. import comments, db, permissions, posts, render, tags
from ..dates import utcnow
from ..models import OWNER, Image, Post, Tag, User

bp = Blueprint("public", __name__)

SEARCH_MAX_LENGTH = 100


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
        headings=render.headings(post.body_html), related=posts.related(s, post, g.user, now),
        thread=comments.thread(s, post, g.user), comment_count=comments.public_count(s, post),
        already_reported=comments.reported_by(s, g.user, post),
    )


@bp.get("/tags")
def all_tags():
    return render_template("tags.html", tags=tags.with_counts(db.session(), g.user, utcnow()))


@bp.get("/tags/<slug>")
def tag_page(slug):
    s = db.session()
    tag = s.scalar(select(Tag).where(Tag.slug == slug))
    if tag is None:
        abort(404)
    page = page_number()
    items, pages = posts.grid_page(s, g.user, utcnow(), page, Post.tags.any(Tag.id == tag.id))
    # A tag whose posts are all hidden doesn't exist for this viewer.
    if not items or page > pages:
        abort(404)
    return render_template("tag.html", tag=tag, items=items, page=page, pages=pages)


@bp.get("/search")
def search():
    words = " ".join(request.args.get("q", "").split())[:SEARCH_MAX_LENGTH]
    page = page_number()
    items, pages = [], 1
    if words:
        items, pages = posts.grid_page(db.session(), g.user, utcnow(), page, posts.search_filter(words))
        if page > pages:
            abort(404)
    return render_template("search.html", words=words, items=items, page=page, pages=pages)


@bp.get("/archive")
def archive():
    return render_template("archive.html", months=posts.archive(db.session(), g.user, utcnow()))


def site_owner(s):
    return s.scalar(select(User).where(User.role == OWNER, User.is_demo.is_(False)).order_by(User.id))


@bp.get("/about")
def about():
    owner = site_owner(db.session())
    return render_template("about.html", about_html=render.to_html(owner.bio) if owner and owner.bio else "")


@bp.get("/feed.xml")
def feed():
    site = url_for("public.home", _external=True).rstrip("/")
    items = [
        {
            "title": post.title,
            "link": url_for("public.show_post", slug=post.slug, _external=True),
            "author": post.author.display_name,
            "date": format_datetime(post.published_at.replace(tzinfo=UTC)),
            # Feed readers open posts somewhere else, so our pictures need the full address.
            "html": post.body_html.replace('src="/images/', f'src="{site}/images/'),
        }
        for post in posts.feed_items(db.session(), utcnow())
    ]
    # .xml templates are autoescaped: the HTML goes in as escaped text, as RSS wants.
    xml = render_template("feed.xml", items=items, site=site, feed_url=url_for("public.feed", _external=True))
    return Response(xml, mimetype="application/rss+xml")


@bp.get("/images/<int:image_id>")
def image(image_id):
    picture = db.session().get(Image, image_id)
    # The demo's uploads are for demo visitors only, so nobody can use a free
    # demo account to host pictures on this site's address.
    if picture is None or (picture.owner.is_demo and not (g.user and g.user.is_demo)):
        abort(404)
    response = Response(picture.data, mimetype=picture.mime)
    # A picture never changes (a new upload is a new address), so browsers can keep it.
    response.headers["Cache-Control"] = ("private" if picture.owner.is_demo else "public") + ", max-age=31536000, immutable"
    return response


@bp.get("/healthz")
def healthz():
    return "ok"
