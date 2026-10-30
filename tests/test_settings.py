"""The Settings page holds the theme and logging out, so the menus only navigate."""
import pytest

from akda.models import AUTHOR, OWNER, READER

from .conftest import PASSWORD, is_logged_in, log_in_as, make_user, post


@pytest.fixture
def demo(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = "x"
    post(client, "/demo")
    return client


# ---------- Who sees what ----------

def test_visitors_can_open_settings_for_the_theme(client):
    response = client.get("/settings")
    assert response.status_code == 200
    page = response.data
    assert b"Appearance" in page and b'name="theme"' in page
    assert b'href="/login"' in page and b'href="/signup"' in page
    assert b"Your Password" not in page and b"Your Name" not in page and b"Log out" not in page


@pytest.mark.parametrize("data", [
    {"action": "name", "display_name": "Hacked"},
    {"action": "password", "current_password": "x", "new_password": "long enough", "confirm_password": "long enough"},
    {"action": "about", "bio": "Hacked"},
])
def test_a_visitors_form_changes_nothing_and_goes_to_log_in(client, data):
    response = post(client, "/settings", data)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


@pytest.mark.parametrize("role,sees_about", [(READER, False), (AUTHOR, False), (OWNER, True)])
def test_logged_in_people_see_their_account_sections(app, client, role, sees_about):
    log_in_as(client, make_user(app, "ana", role))
    page = client.get("/settings").data
    assert b"Appearance" in page and b"Your Name" in page and b"Your Password" in page and b"Log out" in page
    assert (b"About Page" in page) is sees_about


def test_the_demo_can_choose_a_theme_and_log_out_but_change_nothing_else(demo):
    page = demo.get("/settings").data
    assert b"Appearance" in page and b"Log out" in page and b"demo" in page
    assert b"Your Password" not in page and b"Your Name" not in page


def test_settings_says_who_is_logged_in(app, client):
    log_in_as(client, make_user(app, "ana", display_name="Ana Cruz"))
    assert b"logged in as Ana Cruz (ana)" in client.get("/settings").data


# ---------- Logging out from Settings ----------

def test_logging_out_from_settings(app, client):
    make_user(app, "ana")
    post(client, "/login", {"username": "ana", "password": PASSWORD})
    assert b'action="/logout"' in client.get("/settings").data
    assert post(client, "/logout").status_code == 302
    assert not is_logged_in(client)


# ---------- The menus only navigate ----------

@pytest.mark.parametrize("role,url", [
    (None, "/"), (READER, "/"), (AUTHOR, "/"), (OWNER, "/about"), (AUTHOR, "/desk/"), (OWNER, "/desk/comments"),
])
def test_no_page_but_settings_has_a_theme_control(app, client, role, url):
    if role:
        log_in_as(client, make_user(app, "ana", role))
    response = client.get(url)
    assert response.status_code == 200
    page = response.data
    assert b'name="theme"' not in page and b"Dark mode" not in page
    assert b'href="/settings"' in page  # always one click away


@pytest.mark.parametrize("role,url", [(None, "/"), (READER, "/"), (AUTHOR, "/"), (OWNER, "/about")])
def test_public_pages_have_no_log_out_button(app, client, role, url):
    if role:
        log_in_as(client, make_user(app, "ana", role))
    assert b'action="/logout"' not in client.get(url).data


# ---------- The Desk's account menu ----------

def test_the_desk_has_an_account_menu_with_the_first_letter(app, client):
    log_in_as(client, make_user(app, "ana", AUTHOR, display_name="rosa Cruz"))
    page = client.get("/desk/").data
    assert b'class="avatar" aria-hidden="true">R<' in page
    assert b"Account menu for </span>rosa Cruz" in page
    menu = page[page.index(b'class="user-menu"'):page.index(b"</details>")]
    assert b'href="/settings"' in menu and b'action="/logout"' in menu and b"csrf_token" in menu


def test_the_account_menu_starts_closed(app, client):
    log_in_as(client, make_user(app, "ana", AUTHOR))
    assert b"<details class=\"user-menu\" data-user-menu>" in client.get("/desk/").data


def test_a_name_in_the_menu_is_escaped(app, client):
    log_in_as(client, make_user(app, "ana", AUTHOR, display_name="<b>Ana</b>"))
    page = client.get("/desk/").data
    assert b"&lt;b&gt;Ana&lt;/b&gt;" in page and b"<b>Ana</b>" not in page
    assert b'aria-hidden="true">&lt;<' in page  # the first letter is escaped too


def test_the_settings_link_is_marked_as_current(client):
    assert b'href="/settings" aria-current="page"' in client.get("/settings").data
