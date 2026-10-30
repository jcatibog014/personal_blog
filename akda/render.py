"""What authors write (Markdown) -> HTML that is safe to show to readers.

There are three walls, because this is the most dangerous text on the site:
1. markdown-it runs with html=False, so raw <script> in a post stays plain text.
2. nh3 then keeps only the tags and attributes listed here. It also throws out
   javascript: links and any picture that isn't one of ours (a picture from
   another site could track who reads the post).
3. The browser's Content-Security-Policy (__init__.py) refuses inline scripts.

Comments never come here: they are plain text, escaped by the templates.
"""
import html
import re

import nh3
from markdown_it import MarkdownIt

_markdown = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])

ALLOWED_TAGS = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "del", "s", "a", "img",
    "ul", "ol", "li", "blockquote", "pre", "code", "table", "thead", "tbody", "tr", "th", "td",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "img": {"src", "alt", "title"}, "ol": {"start"}}
OUR_PICTURE = re.compile(r"/images/\d+")
HEADING = re.compile(r"<h([23])>(.*?)</h\1>", re.DOTALL)
HEADING_WITH_ID = re.compile(r'<h([23]) id="([^"]+)">(.*?)</h\1>', re.DOTALL)
ANY_HEADING = re.compile(r"<h[1-6][^>]*>.*?</h[1-6]>", re.DOTALL)
EXCERPT_LENGTH = 200


def _keep_attribute(tag, attribute, value):
    if tag == "img" and attribute == "src" and not OUR_PICTURE.fullmatch(value):
        return None
    return value


def clean_html(raw):
    return nh3.clean(raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, attribute_filter=_keep_attribute,
                     url_schemes={"http", "https", "mailto"}, link_rel="noopener noreferrer nofollow")


def to_html(markdown_text):
    return _add_heading_ids(clean_html(_markdown.render(markdown_text or "")))


def _plain_text(safe_html):
    return " ".join(html.unescape(nh3.clean(safe_html, tags=set())).split())


def _add_heading_ids(safe_html):
    """Give h2 and h3 an id, so On This Page can link to them. The "h-" start
    means a heading can never clash with an id the page itself uses."""
    used = set()

    def with_id(match):
        level, inner = match.groups()
        words = re.sub(r"[^a-z0-9]+", "-", _plain_text(inner).lower()).strip("-") or "section"
        anchor = f"h-{words}"
        number = 2
        while anchor in used:
            anchor = f"h-{words}-{number}"
            number += 1
        used.add(anchor)
        return f'<h{level} id="{anchor}">{inner}</h{level}>'

    return HEADING.sub(with_id, safe_html)


def headings(safe_html):
    """[{"level", "id", "text"}] of the h2 and h3 headings, for On This Page."""
    return [{"level": int(level), "id": anchor, "text": _plain_text(inner)}
            for level, anchor, inner in HEADING_WITH_ID.findall(safe_html)]


def excerpt(safe_html, length=EXCERPT_LENGTH):
    """The first words as plain text, for the card of a post without a summary.
    Headings read badly in the middle of a sentence, so they are left out."""
    text = _plain_text(ANY_HEADING.sub(" ", safe_html)) or _plain_text(safe_html)
    if len(text) <= length:
        return text
    return text[:length].rsplit(" ", 1)[0].rstrip(".,;:!?-") + "..."
