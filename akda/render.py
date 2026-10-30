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
EXCERPT_LENGTH = 200


def _keep_attribute(tag, attribute, value):
    if tag == "img" and attribute == "src" and not OUR_PICTURE.fullmatch(value):
        return None
    return value


def clean_html(raw):
    return nh3.clean(raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, attribute_filter=_keep_attribute,
                     url_schemes={"http", "https", "mailto"}, link_rel="noopener noreferrer nofollow")


def to_html(markdown_text):
    return clean_html(_markdown.render(markdown_text or ""))


def excerpt(safe_html, length=EXCERPT_LENGTH):
    """The first words as plain text, for the card of a post without a summary."""
    text = " ".join(html.unescape(nh3.clean(safe_html, tags=set())).split())
    if len(text) <= length:
        return text
    return text[:length].rsplit(" ", 1)[0] + "..."
