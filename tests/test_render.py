"""Markdown -> safe HTML. The most dangerous text on the site."""
import pytest

from akda import render


def test_markdown_becomes_html():
    html = render.to_html("## Title\n\nSome **bold** and *italic*.\n\n- one\n- two\n\n| a |\n|---|\n| b |")
    for part in ('<h2 id="h-title">Title</h2>', "<strong>bold</strong>", "<em>italic</em>", "<li>one</li>", "<td>b</td>"):
        assert part in html


@pytest.mark.parametrize("attack", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<iframe src='https://evil.example'></iframe>",
    "<style>body{display:none}</style>",
    "<svg onload=alert(1)></svg>",
])
def test_raw_html_never_becomes_a_tag(attack):
    html = render.to_html(attack)
    assert "<script" not in html and "<iframe" not in html and "<style" not in html
    assert "<svg" not in html and "<img" not in html


@pytest.mark.parametrize("link", [
    "[x](javascript:alert(1))",
    "[x](JaVaScRiPt:alert(1))",
    "[x](data:text/html;base64,PHNjcmlwdD4=)",
    "[x](vbscript:alert(1))",
])
def test_dangerous_links_are_removed(link):
    html = render.to_html(link).lower()
    assert "javascript:" not in html.replace("[x](javascript:alert(1))", "")
    assert 'href="javascript' not in html and 'href="data' not in html and 'href="vbscript' not in html


def test_the_cleaner_itself_stops_attacks_even_if_markdown_let_them_through():
    html = render.clean_html('<a href="javascript:alert(1)" onclick="x()">x</a><script>bad()</script><p style="x">y</p>')
    assert "javascript" not in html and "onclick" not in html and "bad()" not in html and "style" not in html


def test_links_get_a_safe_rel():
    assert 'rel="noopener noreferrer nofollow"' in render.to_html("[x](https://example.com)")


def test_only_our_own_pictures_load():
    assert 'src="/images/12"' in render.to_html("![cat](/images/12)")
    for other in ("https://tracker.example/a.png", "//tracker.example/a.png", "/images/12/../../evil", "/static/x.png"):
        html = render.to_html(f"![cat]({other})")
        assert "src=" not in html, other


def test_excerpt_is_plain_text_and_cut_at_a_word():
    html = render.to_html("# Hi\n\nSome *fine* text & more " + "word " * 100)
    text = render.excerpt(html)
    assert text.startswith("Hi Some fine text & more")
    assert "<" not in text and len(text) <= render.EXCERPT_LENGTH + 3 and text.endswith("...")
    assert render.excerpt(render.to_html("Short.")) == "Short."
