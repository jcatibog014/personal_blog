"""The home page's sections and the search bar that opens from the menu."""
from datetime import timedelta

from akda import posts
from akda.dates import utcnow
from akda.models import AUTHOR, DRAFT
from akda.views.public import HOME_TAGS

from .conftest import add_post, log_in_as, make_user


# ---------- Home sections ----------

def test_latest_posts_has_a_heading_only_when_there_are_cards(app, client, author_id):
    add_post(app, author_id, title="Only One")
    assert b"Latest Posts" not in client.get("/").data  # it is the banner, with no grid under it
    add_post(app, author_id, title="Second One")
    assert b"Latest Posts" in client.get("/").data


def test_later_pages_say_older_posts(app, client, author_id):
    for number in range(posts.GRID_SIZE + 2):
        add_post(app, author_id, title=f"Number {number}", published_at=utcnow() - timedelta(days=number + 1))
    second = client.get("/?page=2").data
    assert b"Older Posts" in second and b"Latest Posts" not in second


def test_the_tag_cloud_links_to_tags_with_their_counts(app, client, author_id):
    add_post(app, author_id, title="One", tag_names=["python", "life"])
    add_post(app, author_id, title="Two", tag_names=["python"])
    page = client.get("/").data
    assert b"Browse by Tag" in page and b'href="/tags"' in page
    assert b'href="/tags/python">python <span class="byline">2</span>' in page
    assert b'href="/tags/life">life <span class="byline">1</span>' in page


def test_no_tag_cloud_without_tags(app, client, author_id):
    add_post(app, author_id)
    assert b"Browse by Tag" not in client.get("/").data


def test_the_tag_cloud_shows_only_the_most_used_tags(app, client, author_id):
    add_post(app, author_id, title="Popular", tag_names=["popular"])
    add_post(app, author_id, title="Popular Too", tag_names=["popular"])
    for number in range(HOME_TAGS):
        add_post(app, author_id, title=f"Rare {number}", tag_names=[f"rare{number:02}"])
    page = client.get("/").data
    cloud = page[page.index(b"Browse by Tag"):]  # post cards also link to their tags
    assert b'href="/tags/popular"' in cloud
    assert cloud.count(b'href="/tags/rare') == HOME_TAGS - 1


def test_the_tag_cloud_never_shows_hidden_posts_tags(app, client, author_id):
    demo = make_user(app, "demo-writer", AUTHOR, is_demo=True)
    add_post(app, author_id, title="Open", tag_names=["open"])
    add_post(app, author_id, status=DRAFT, tag_names=["draftonly"])
    add_post(app, author_id, published_at=utcnow() + timedelta(days=1), tag_names=["futureonly"])
    add_post(app, demo, tag_names=["demoonly"])
    page = client.get("/").data
    assert b"open" in page
    assert b"draftonly" not in page and b"futureonly" not in page and b"demoonly" not in page
    assert b"demoonly" in log_in_as(app.test_client(), demo).get("/").data


# ---------- Search ----------

def test_the_menu_has_a_search_link_not_a_box(client):
    page = client.get("/about").data
    assert b'class="search-bar' in page and b'id="site-search"' in page
    assert b"data-search-toggle" in page and b'href="/search"' in page
    # The bar starts closed, so the menu stays clean.
    start = page.index(b'id="site-search"')
    assert b"hidden" in page[start:page.index(b">", start)]


def test_the_search_page_has_its_own_form_and_keeps_the_words(client):
    page = client.get("/search", query_string={"q": 'adobo "recipe"'}).data
    assert b'id="site-search"' not in page and b"data-search-toggle" not in page
    assert b'value="adobo &#34;recipe&#34;"' in page
    assert page.count(b'action="/search"') == 1


def test_the_search_page_form_is_there_with_nothing_typed(client):
    page = client.get("/search").data
    assert b'class="search-bar search-page-form"' in page and b"Type a word" in page
