"""Tags, search, the archive, related posts, RSS and the About page.

The biggest rule: drafts, scheduled posts and the demo's posts never show in any list.
"""
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, select

from akda import db, posts, render, tags
from akda.dates import utcnow
from akda.models import AUTHOR, DRAFT, OWNER, Tag

from .conftest import add_post, edit_form, get_post, get_user, log_in_as, make_user, post as post_form


@pytest.fixture
def hidden_posts(app, author_id):
    """One of everything that must never leak. Each has the word "secret" and the tag "hush"."""
    demo = make_user(app, "demo-writer", AUTHOR, is_demo=True)
    add_post(app, author_id, title="Secret Draft", body="secret", status=DRAFT, tag_names=["hush"])
    add_post(app, author_id, title="Secret Scheduled", body="secret", tag_names=["hush"],
             published_at=utcnow() + timedelta(days=1))
    add_post(app, demo, title="Secret Demo", body="secret", tag_names=["hush"])
    return demo


# ---------- Hidden posts stay hidden everywhere ----------

@pytest.mark.parametrize("url", ["/", "/tags", "/tags/hush", "/search?q=secret", "/archive", "/feed.xml"])
def test_hidden_posts_are_in_no_list(app, client, author_id, hidden_posts, url):
    add_post(app, author_id, title="Open Post", body="Nothing to hide here.", tag_names=["open"])
    page = client.get(url)
    assert page.status_code in (200, 404)
    assert b"Secret" not in page.data
    assert b"hush" not in page.data or url == "/tags/hush"


def test_a_tag_with_only_hidden_posts_gives_404(app, client, hidden_posts):
    assert client.get("/tags/hush").status_code == 404


def test_related_posts_never_show_hidden_ones(app, client, author_id, hidden_posts):
    add_post(app, author_id, title="Open Post", tag_names=["hush"])
    page = client.get("/posts/open-post").data
    assert b"Secret" not in page and b"Related Posts" not in page


def test_demo_visitors_also_see_the_demos_posts_but_never_real_hidden_ones(app, hidden_posts):
    demo = log_in_as(app.test_client(), hidden_posts)
    for url in ("/", "/tags/hush", "/search?q=secret", "/archive"):
        page = demo.get(url).data
        assert b"Secret Demo" in page, url
        assert b"Secret Draft" not in page and b"Secret Scheduled" not in page
    assert b"Secret" not in demo.get("/feed.xml").data  # a feed is always for strangers


# ---------- Tags ----------

def test_parsing_tags():
    assert tags.parse(" Python, life,  PYTHON ,, New   Year ") == ["python", "life", "new year"]
    assert tags.parse("") == []


def test_tag_rules():
    assert tags.problem(["a", "b", "c", "d", "e"]) is None
    assert "at most 5" in tags.problem(["a", "b", "c", "d", "e", "f"])
    assert "30 characters" in tags.problem(["x" * 31])
    assert "plain letter" in tags.problem(["日本語"])


def test_the_editor_saves_tags_and_reuses_old_ones(app, client, author_id):
    writer = log_in_as(client, author_id)
    draft = add_post(app, author_id, status=DRAFT, tag_names=["python"])
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, tags="Python, C++, life"))
    assert sorted(tag.name for tag in get_post(app, draft).tags) == ["c++", "life", "python"]
    with app.app_context():
        assert sorted(db.session().scalars(select(Tag.name))) == ["c++", "life", "python"]
    # Taking one off keeps the others.
    post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, tags="life"))
    assert [tag.name for tag in get_post(app, draft).tags] == ["life"]


def test_the_editor_refuses_too_many_tags(app, client, author_id):
    writer = log_in_as(client, author_id)
    draft = add_post(app, author_id, status=DRAFT)
    response = post_form(writer, f"/desk/posts/{draft}/edit", edit_form(draft, app, tags="a,b,c,d,e,f"))
    assert response.status_code == 400 and b"at most 5 tags" in response.data


def test_tag_slug_is_the_identity(app, ctx):
    first = tags.resolve(ctx, ["C++"])[0]
    ctx.commit()
    assert tags.resolve(ctx, ["c"])[0].id == first.id


def test_tag_counts_only_count_visible_posts(app, ctx, author_id, hidden_posts):
    add_post(app, author_id, title="One", tag_names=["hush", "open"])
    add_post(app, author_id, title="Two", tag_names=["open"])
    counts = {tag.name: number for tag, number in tags.with_counts(ctx, None, utcnow())}
    assert counts == {"open": 2, "hush": 1}


def test_tag_page_and_index(app, client, author_id):
    add_post(app, author_id, title="Tagged", tag_names=["python"])
    add_post(app, author_id, title="Untagged")
    page = client.get("/tags/python").data
    assert b"Tagged" in page and b"Untagged" not in page
    assert b"python" in client.get("/tags").data
    assert client.get("/tags/nothing").status_code == 404


def test_deleting_a_post_removes_its_links_but_keeps_the_tag(app, client, author_id):
    live = add_post(app, author_id, tag_names=["keep"])
    post_form(log_in_as(client, author_id), f"/desk/posts/{live}/delete")
    with app.app_context():
        assert db.session().scalar(select(Tag.name)) == "keep"
    assert b"keep" not in client.get("/tags").data


# ---------- Search ----------

@pytest.mark.parametrize("words", ["adobo", "ADOBO", "Adobo Recipe", "Vinegar", "my-summary", "cooking"])
def test_search_finds_title_text_summary_and_tags(app, client, author_id, words):
    add_post(app, author_id, title="Adobo Recipe", body="Lots of vinegar.", summary="my-summary", tag_names=["cooking"])
    add_post(app, author_id, title="Unrelated")
    page = client.get("/search", query_string={"q": words}).data
    assert b"Adobo Recipe" in page and b"Unrelated" not in page


def test_search_treats_wildcards_as_plain_characters(app, client, author_id):
    add_post(app, author_id, title="Ordinary Post")
    add_post(app, author_id, title="100% Real")
    assert b"Ordinary Post" not in client.get("/search?q=%25").data  # %25 is a typed "%"
    assert b"100% Real" in client.get("/search?q=%25").data
    assert b"Nothing Found" in client.get("/search?q=_rdinary").data


def test_search_with_nothing_typed_and_with_odd_input(client):
    assert b"Type a word" in client.get("/search").data
    assert b"Type a word" in client.get("/search?q=%20%20").data
    assert client.get("/search?q=" + "x" * 500).status_code == 200


def test_search_words_are_escaped(client):
    page = client.get("/search", query_string={"q": "<script>bad()</script>"}).data
    assert b"<script>bad()" not in page


def test_search_pages(app, client, author_id):
    for number in range(posts.GRID_SIZE + 1):
        add_post(app, author_id, title=f"Findme {number}")
    assert b"Page 1 of 2" in client.get("/search?q=findme").data
    second = client.get("/search?q=findme&page=2")
    assert second.status_code == 200 and b"q=findme" in second.data
    assert client.get("/search?q=findme&page=3").status_code == 404


# ---------- Archive ----------

def test_archive_groups_by_philippine_month(app, ctx, client, author_id):
    # 20:00 UTC on Jan 31 is already 04:00 on Feb 1 in Manila.
    add_post(app, author_id, title="Late January UTC", published_at=datetime(2026, 1, 31, 20))
    add_post(app, author_id, title="Early January", published_at=datetime(2026, 1, 5))
    months = posts.archive(ctx, None, utcnow())
    assert [month["name"] for month in months] == ["February 2026", "January 2026"]
    assert [row.title for row in months[0]["posts"]] == ["Late January UTC"]
    assert b"February 2026" in client.get("/archive").data


# ---------- Related posts ----------

def test_related_posts_are_ranked_by_shared_tags(app, ctx, author_id):
    this = add_post(app, author_id, title="This", tag_names=["a", "b", "c"])
    add_post(app, author_id, title="Shares One", tag_names=["a"], published_at=utcnow() - timedelta(minutes=1))
    add_post(app, author_id, title="Shares Three", tag_names=["a", "b", "c"], published_at=utcnow() - timedelta(days=9))
    add_post(app, author_id, title="Shares Two", tag_names=["a", "b"], published_at=utcnow() - timedelta(days=5))
    add_post(app, author_id, title="Shares None", tag_names=["z"])
    add_post(app, author_id, title="Shares One Older", tag_names=["c"], published_at=utcnow() - timedelta(days=20))
    found = posts.related(ctx, ctx.get(posts.Post, this), None, utcnow())
    assert [post.title for post in found] == ["Shares Three", "Shares Two", "Shares One"]


def test_a_post_without_tags_has_no_related_posts(app, ctx, author_id):
    this = add_post(app, author_id, title="This")
    assert posts.related(ctx, ctx.get(posts.Post, this), None, utcnow()) == []


# ---------- On This Page ----------

def test_headings_get_ids_and_are_listed():
    html = render.to_html("## First *Part*\n\ntext\n\n### Small\n\n## First Part\n\n#### Too Deep")
    assert '<h2 id="h-first-part">First <em>Part</em></h2>' in html
    assert [h["id"] for h in render.headings(html)] == ["h-first-part", "h-small", "h-first-part-2"]
    assert [h["level"] for h in render.headings(html)] == [2, 3, 2]
    assert render.headings(html)[0]["text"] == "First Part"


def test_on_this_page_shows_from_two_headings(app, client, author_id):
    add_post(app, author_id, title="One Heading", body="## Only One")
    add_post(app, author_id, title="Two Headings", body="## First\n\n## Second")
    assert b"On This Page" not in client.get("/posts/one-heading").data
    page = client.get("/posts/two-headings").data
    assert b"On This Page" in page and b'href="#h-second"' in page


def test_a_heading_cannot_smuggle_html_into_the_list(app, client, author_id):
    add_post(app, author_id, title="Bad", body="## <script>bad()</script>\n\n## Two")
    assert b"<script>bad()" not in client.get("/posts/bad").data


# ---------- RSS ----------

def test_the_feed_is_valid_xml_with_full_links(app, client, author_id):
    add_post(app, author_id, title="Tom & Jerry <3", body="Hello **world** ![x](/images/5)")
    response = client.get("/feed.xml")
    assert response.mimetype == "application/rss+xml"
    item = ElementTree.fromstring(response.data).find("channel/item")
    assert item.find("title").text == "Tom & Jerry <3"
    assert item.find("link").text.startswith("http://localhost/posts/")
    assert "<strong>world</strong>" in item.find("description").text
    assert 'src="http://localhost/images/5"' in item.find("description").text
    assert item.find("pubDate").text.endswith("+0000")


def test_the_feed_works_when_empty(client):
    assert ElementTree.fromstring(client.get("/feed.xml").data).find("channel/item") is None


# ---------- About ----------

def test_about_page_shows_the_owners_text_cleaned(app, client):
    make_user(app, "juan", OWNER, bio="# Hi\n\nI **write**. <script>bad()</script>")
    page = client.get("/about").data
    assert b"<strong>write</strong>" in page and b"<script>bad()" not in page


def test_about_page_without_an_owner(client):
    assert b"hasn't been written yet" in client.get("/about").data


def test_only_the_owner_can_edit_about(app, owner_id, author_id):
    post_form(log_in_as(app.test_client(), owner_id), "/settings", {"action": "about", "bio": "New text"})
    assert get_user(app, "juan").bio == "New text"
    response = post_form(log_in_as(app.test_client(), author_id), "/settings", {"action": "about", "bio": "Hacked"})
    assert response.status_code == 403
    assert get_user(app, "juan").bio == "New text"


# ---------- Query counts ----------

def count_queries(app, client, url):
    with app.app_context():
        engine = db.engine()
    statements = []
    listener = lambda conn, cur, statement, *rest: statements.append(statement)
    event.listen(engine, "before_cursor_execute", listener)
    assert client.get(url).status_code == 200
    event.remove(engine, "before_cursor_execute", listener)
    return len(statements)


@pytest.mark.parametrize("url", ["/", "/tags/shared", "/search?q=post", "/posts/post-0", "/feed.xml", "/tags", "/archive"])
def test_lists_need_no_query_per_post(app, client, author_id, url):
    other = make_user(app, "rosa", AUTHOR)
    for number in range(2):
        add_post(app, author_id, title=f"Post {number}", tag_names=["shared", f"t{number}"])
    few = count_queries(app, client, url)
    for number in range(2, 8):
        add_post(app, other if number % 2 else author_id, title=f"Post {number}", tag_names=["shared", f"t{number}"])
    assert count_queries(app, client, url) == few
