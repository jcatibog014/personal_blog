"""Tags: a many-to-many between posts and tags (the post_tags table)."""
from sqlalchemy import func, select

from . import posts
from .models import Post, Tag, post_tags

MAX_PER_POST = 5
NAME_MAX_LENGTH = 30


def parse(text):
    """"Python, life,  python" -> ["python", "life"] (lowercase, in order, no repeats)."""
    names = []
    for part in (text or "").split(","):
        name = " ".join(part.split()).lower()
        if name and name not in names:
            names.append(name)
    return names


def problem(names):
    if len(names) > MAX_PER_POST:
        return f"Use at most {MAX_PER_POST} tags."
    for name in names:
        if len(name) > NAME_MAX_LENGTH:
            return f"Keep each tag to {NAME_MAX_LENGTH} characters."
        if not posts.has_slug(name):
            return f'"{name}" needs at least one plain letter or number.'
    return None


def resolve(s, names):
    """The Tag rows for these names, adding new ones. A tag IS its slug, so "C++"
    and "c" are one tag, and the UNIQUE slug can never clash."""
    wanted = {posts.slugify(name): name for name in names}
    found = {tag.slug: tag for tag in s.scalars(select(Tag).where(Tag.slug.in_(wanted)))}
    result = []
    for slug, name in wanted.items():
        tag = found.get(slug)
        if tag is None:
            tag = Tag(name=name, slug=slug)
            s.add(tag)
        result.append(tag)
    return result


def with_counts(s, viewer, now, limit=None):
    """[(tag, number of visible posts)], most used first. An inner join with GROUP
    BY, so a tag whose posts are all hidden doesn't show at all."""
    number = func.count(Post.id)
    query = (select(Tag, number).join(post_tags, post_tags.c.tag_id == Tag.id)
             .join(Post, Post.id == post_tags.c.post_id)
             .where(posts.visible_filter(viewer, now))
             .group_by(Tag.id).order_by(number.desc(), Tag.name).limit(limit))
    return s.execute(query).all()
