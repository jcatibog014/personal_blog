"""Posts: the rule for what counts as live, saving, publishing and listing.

ALL public lists (home, tags, search, archive, related posts, RSS) start from
visible_filter(), so drafts, scheduled posts and the demo's posts can't leak
into one of them by accident.
"""
import math
import re
import unicodedata

from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from . import render
from .models import DRAFT, PUBLISHED, Post, User

TITLE_MAX_LENGTH = 200
SUMMARY_MAX_LENGTH = 300
BODY_MAX_LENGTH = 100_000
SLUG_MAX_LENGTH = 80
WORDS_PER_MINUTE = 200
GRID_SIZE = 12


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

def slugify(title):
    """"Kumusta, Mundo!" -> "kumusta-mundo"; "Piña" -> "pina"."""
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:SLUG_MAX_LENGTH].rstrip("-") or "post"


def unique_slug(s, title):
    slug = slugify(title)
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
    return {"title": post.title, "summary": post.summary, "body_md": post.body_md}


def read_form(form):
    return {
        "title": form.get("title", "").strip(),
        "summary": form.get("summary", "").strip(),
        # Windows browsers send \r\n in text boxes. Keep one kind of line ending.
        "body_md": form.get("body_md", "").replace("\r\n", "\n"),
    }


def form_errors(data, publishing):
    """A draft may be unfinished; a post going public needs a title and some text."""
    errors = {}
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


# ---------- Lists ----------

def card_options():
    """What a post card needs. selectinload: one extra query, not one per card."""
    return (selectinload(Post.author),)


def newest_first(query):
    return query.order_by(Post.published_at.desc(), Post.id.desc())


def count_visible(s, viewer, now):
    return s.scalar(select(func.count()).select_from(Post).where(visible_filter(viewer, now)))


def home_page(s, viewer, now, page):
    """(featured post or None, grid posts, number of pages). The newest post is
    the banner on page 1, and the grid of 12 starts after it."""
    total = count_visible(s, viewer, now)
    pages = max(1, math.ceil((total - 1) / GRID_SIZE))
    query = newest_first(select(Post).where(visible_filter(viewer, now))).options(*card_options())
    grid = list(s.scalars(query.offset((page - 1) * GRID_SIZE + 1).limit(GRID_SIZE)))
    featured = s.scalar(query.limit(1)) if page == 1 else None
    return featured, grid, pages
