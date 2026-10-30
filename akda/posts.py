"""Posts: the rule for what counts as live, saving, publishing and listing.

ALL public lists (home, tags, search, archive, related posts, RSS) start from
visible_filter(), so drafts, scheduled posts and the demo's posts can't leak
into one of them by accident.
"""
import math
import re
import unicodedata

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import selectinload, undefer

from . import render, tags
from .dates import parse_local, to_local
from .models import DRAFT, PUBLISHED, Post, PostVersion, Tag, User, post_tags

TITLE_MAX_LENGTH = 200
SUMMARY_MAX_LENGTH = 300
BODY_MAX_LENGTH = 100_000
SLUG_MAX_LENGTH = 80
WORDS_PER_MINUTE = 200
GRID_SIZE = 12
MAX_VERSIONS = 30


# ---------- What is live? ----------

def live_filter(now):
    """THE rule, in SQL. permissions.is_live() is the same rule in Python.

    A scheduled post is just a published post with a date in the future. So
    it goes live by itself at that moment, with no background job to run.
    """
    return and_(Post.status == PUBLISHED, Post.published_at <= now)


def visible_filter(viewer, now):
    """The posts this viewer may see in lists.

    The demo is a sandbox: its posts are seen only by demo visitors, who also
    see the real posts. Being the author of a draft doesn't count here, because
    public lists never show drafts, not even your own.
    """
    if viewer is not None and viewer.is_demo:
        return live_filter(now)
    return and_(live_filter(now), Post.author.has(User.is_demo.is_(False)))


# ---------- Small helpers ----------

def _ascii_slug(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:SLUG_MAX_LENGTH].rstrip("-")


def slugify(title):
    """"Kumusta, Mundo!" -> "kumusta-mundo"; "Piña" -> "pina"."""
    return _ascii_slug(title) or "post"


def has_slug(text):
    return bool(_ascii_slug(text))


def unique_slug(s, title):
    slug = slugify(title)
    with s.no_autoflush:  # the caller is halfway through changing a post
        taken = set(s.scalars(select(Post.slug).where(Post.slug.like(f"{slug}%"))))
    if slug not in taken:
        return slug
    number = 2
    while f"{slug}-{number}" in taken:
        number += 1
    return f"{slug}-{number}"


def reading_minutes(text):
    return max(1, math.ceil(len(text.split()) / WORDS_PER_MINUTE))


# ---------- The form ----------

def blank_form(post):
    return {"title": post.title, "summary": post.summary, "body_md": post.body_md,
            "tags": ", ".join(tag.name for tag in post.tags), "publish_at": ""}


def read_form(form):
    return {
        "title": form.get("title", "").strip(),
        "summary": form.get("summary", "").strip(),
        # Windows browsers send \r\n in text boxes. Keep one kind of line ending.
        "body_md": form.get("body_md", "").replace("\r\n", "\n"),
        "tags": form.get("tags", "").strip(),
        "publish_at": form.get("publish_at", "").strip(),
    }


def read_schedule(text, now):
    """What the date box says -> (when, problem). Empty means "no date"."""
    if not text:
        return None, None
    try:
        when = parse_local(text)
    except ValueError:
        return None, "That isn't a date and time."
    if when <= now:
        return None, "Choose a time in the future."
    return when, None


def form_errors(data, publishing):
    """A draft may be unfinished; a post going public needs a title and some text."""
    errors = {}
    problem = tags.problem(tags.parse(data["tags"]))
    if problem:
        errors["tags"] = problem
    if len(data["title"]) > TITLE_MAX_LENGTH:
        errors["title"] = f"Use at most {TITLE_MAX_LENGTH} characters."
    if len(data["summary"]) > SUMMARY_MAX_LENGTH:
        errors["summary"] = f"Use at most {SUMMARY_MAX_LENGTH} characters."
    if len(data["body_md"]) > BODY_MAX_LENGTH:
        errors["body_md"] = f"Use at most {BODY_MAX_LENGTH:,} characters."
    if publishing:
        if not data["title"]:
            errors["title"] = "A published post needs a title."
        if not data["body_md"].strip():
            errors["body_md"] = "A published post needs some text."
    return errors


# ---------- Changing a post ----------

def apply_content(post, data, now):
    post.title = data["title"]
    post.summary = data["summary"]
    post.body_md = data["body_md"]
    post.body_html = render.to_html(data["body_md"])
    post.excerpt = data["summary"] or render.excerpt(post.body_html)
    post.reading_minutes = reading_minutes(data["body_md"])
    post.updated_at = now


def publish(s, post, when):
    post.status = PUBLISHED
    post.published_at = when
    # The address is fixed the first time: later title changes don't break links.
    if post.slug is None:
        post.slug = unique_slug(s, post.title)


def unpublish(post):
    post.status = DRAFT
    post.published_at = None


def is_scheduled(post, now):
    return post.status == PUBLISHED and post.published_at > now


# ---------- Version history ----------

def versions_of(s, post):
    return s.scalars(select(PostVersion).where(PostVersion.post_id == post.id)
                     .order_by(PostVersion.saved_at.desc(), PostVersion.id.desc())).all()


def snapshot(s, post, user, now):
    """Keep a copy of the post's words, unless the newest copy already says the same."""
    with s.no_autoflush:
        newest = s.scalar(select(PostVersion).where(PostVersion.post_id == post.id)
                          .order_by(PostVersion.saved_at.desc(), PostVersion.id.desc()).limit(1))
        same = newest is not None and (newest.title, newest.summary, newest.body_md) == (
            post.title, post.summary, post.body_md)
        if same:
            return
        # Keep the newest 30: this new one plus 29 of the old ones.
        too_old = s.scalars(select(PostVersion.id).where(PostVersion.post_id == post.id)
                            .order_by(PostVersion.saved_at.desc(), PostVersion.id.desc())
                            .offset(MAX_VERSIONS - 1)).all()
    if too_old:
        s.execute(delete(PostVersion).where(PostVersion.id.in_(too_old)))
    s.add(PostVersion(post_id=post.id, saved_by_id=user.id, title=post.title, summary=post.summary,
                      body_md=post.body_md, saved_at=now))


# ---------- Lists ----------

def card_options():
    """What a post card needs. selectinload: one extra query each, not one per card."""
    return (selectinload(Post.author), selectinload(Post.tags))


def newest_first(query):
    return query.order_by(Post.published_at.desc(), Post.id.desc())


def count_where(s, *conditions):
    return s.scalar(select(func.count()).select_from(Post).where(*conditions))


def home_page(s, viewer, now, page):
    """(featured post or None, grid posts, number of pages). The newest post is
    the banner on page 1, and the grid of 12 starts after it."""
    total = count_where(s, visible_filter(viewer, now))
    pages = max(1, math.ceil((total - 1) / GRID_SIZE))
    query = newest_first(select(Post).where(visible_filter(viewer, now))).options(*card_options())
    grid = list(s.scalars(query.offset((page - 1) * GRID_SIZE + 1).limit(GRID_SIZE)))
    featured = s.scalar(query.limit(1)) if page == 1 else None
    return featured, grid, pages


def grid_page(s, viewer, now, page, *conditions):
    """(posts, number of pages) for a tag page or a search."""
    where = (visible_filter(viewer, now), *conditions)
    pages = max(1, math.ceil(count_where(s, *where) / GRID_SIZE))
    query = newest_first(select(Post).where(*where)).options(*card_options())
    return list(s.scalars(query.offset((page - 1) * GRID_SIZE).limit(GRID_SIZE))), pages


def search_filter(words):
    """Find in the title, summary, text or tags. autoescape: a typed % or _ means
    itself, not "anything". icontains ignores upper and lower case on both databases."""
    return or_(
        Post.title.icontains(words, autoescape=True),
        Post.summary.icontains(words, autoescape=True),
        Post.body_md.icontains(words, autoescape=True),
        Post.tags.any(Tag.name.icontains(words, autoescape=True)),
    )


def related(s, post, viewer, now, limit=3):
    """The posts sharing the most tags with this one, newest first among equals.

    Join to post_tags, keep only rows with this post's tags, then GROUP BY post:
    COUNT is then the number of tags that post shares with this one.
    """
    tag_ids = [tag.id for tag in post.tags]
    if not tag_ids:
        return []
    query = (select(Post).join(post_tags, post_tags.c.post_id == Post.id)
             .where(post_tags.c.tag_id.in_(tag_ids), Post.id != post.id, visible_filter(viewer, now))
             .group_by(Post.id)
             .order_by(func.count(post_tags.c.tag_id).desc(), Post.published_at.desc(), Post.id.desc())
             .limit(limit).options(*card_options()))
    return list(s.scalars(query))


def archive(s, viewer, now):
    """[{"year", "month", "name", "posts"}], newest month first. Grouped here, not in
    SQL, because a month is a Philippine-time month and the database holds UTC."""
    rows = s.execute(newest_first(select(Post.title, Post.slug, Post.published_at, Post.cover_image_id)
                                  .where(visible_filter(viewer, now)))).all()
    months = []
    for row in rows:
        local = to_local(row.published_at)
        if not months or (months[-1]["year"], months[-1]["month"]) != (local.year, local.month):
            months.append({"year": local.year, "month": local.month, "name": f"{local:%B} {local.year}", "posts": []})
        months[-1]["posts"].append(row)
    return months


def feed_items(s, now, limit=20):
    """The newest posts for RSS. viewer=None: a feed reader is always a stranger."""
    query = newest_first(select(Post).where(visible_filter(None, now))).options(
        selectinload(Post.author), undefer(Post.body_html)).limit(limit)
    return list(s.scalars(query))
