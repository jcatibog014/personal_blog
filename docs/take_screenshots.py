"""Take the README screenshots (docs/screenshots/*.png).

Retake them in every pull request that visibly changes a page, and add a new
one when a page or feature is added: the README shows everything the site can
do. tests/test_readme.py fails if the pictures and the README disagree.

It uses a practice database with made-up people, so no real person or post can
show. Most pictures use "Try Demo". It uses Microsoft Edge, which Windows already
has, through Playwright. Playwright is only a tool for this script, so it is not
in requirements.txt:

    .venv\\Scripts\\python -m pip install playwright
    $env:DATABASE_URL = "sqlite:///C:/Temp/akda-screenshots.sqlite"
    .venv\\Scripts\\python docs\\make_practice_data.py
    .venv\\Scripts\\flask --app akda run --port 5005      (keep this one running)
    .venv\\Scripts\\python docs\\take_screenshots.py      (in another terminal)

Every picture is one screen (no full-page shots), so they are all the same
size and the README table stays short and even.

Add a line to PAGES when a page is added.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5005"
OUT = Path(__file__).parent / "screenshots"
DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}
OWNER, OWNER_PASSWORD = "juan", "practice password"  # from make_practice_data.py

# (file name, address, theme, screen size). {post} is the demo's newest post.
PAGES = [
    ("home.png", "/", "light", DESKTOP),
    ("home-dark.png", "/", "dark", DESKTOP),
    ("article.png", "{post}", "light", DESKTOP),
    ("comments.png", "{post}#comments", "light", DESKTOP),
    ("my-posts.png", "/desk/?tab=published", "light", DESKTOP),
    ("my-posts-phone.png", "/desk/?tab=published", "light", PHONE),
    ("moderation.png", "/desk/comments", "light", DESKTOP),
    ("reports.png", "/desk/comments?tab=reported", "dark", DESKTOP),
    ("tags.png", "/tags", "light", DESKTOP),
    ("archive.png", "/archive", "light", DESKTOP),
    ("search.png", "/search?q=notebook", "light", DESKTOP),
    ("settings.png", "/settings", "light", DESKTOP),
    ("phone.png", "/", "light", PHONE),
]


def demo_page(browser, theme, size):
    page = browser.new_page(viewport=size, color_scheme=theme)
    page.goto(f"{BASE}/login")
    page.get_by_role("button", name="Try Demo").click()
    page.wait_for_url("**/desk/**")
    return page


def save(page, name):
    page.wait_for_load_state("networkidle")  # fonts and pictures are in
    page.wait_for_timeout(300)
    page.screenshot(path=OUT / name)
    print("saved", name)


def shoot(page, name, path):
    page.goto(f"{BASE}{path}")
    save(page, name)


def shoot_visitor_pages(browser):
    page = browser.new_page(viewport=DESKTOP, color_scheme="light")
    shoot(page, "login.png", "/login")
    shoot(page, "signup.png", "/signup")
    shoot(page, "about.png", "/about")
    page.close()


def shoot_people_page(browser):
    """As the practice owner, with one invite waiting."""
    page = browser.new_page(viewport=DESKTOP, color_scheme="light")
    page.goto(f"{BASE}/login")
    page.get_by_label("Username").fill(OWNER)
    page.get_by_label("Password").fill(OWNER_PASSWORD)
    page.get_by_role("button", name="Log in", exact=True).click()
    page.wait_for_url("**/desk/**")
    page.goto(f"{BASE}/desk/people")
    if page.get_by_role("button", name="Cancel invite").count() == 0:
        page.get_by_role("button", name="Invite an author").click()
    shoot(page, "people.png", "/desk/people")  # opened again, so the secret link is gone
    page.close()


def shoot_page_parts(page):
    """Things that need a scroll or a click first."""
    page.goto(f"{BASE}/")
    # Start at the heading, so the picture shows Latest Posts down to Browse by Tag.
    page.evaluate("document.querySelector('.section-title').scrollIntoView(); window.scrollBy(0, -16)")
    save(page, "browse-by-tag.png")

    page.goto(f"{BASE}/")
    page.locator(".search-toggle-wide").click()
    page.keyboard.type("notebook")
    save(page, "search-bar.png")

    page.goto(f"{BASE}/desk/?tab=published")
    page.locator(".user-menu summary").click()
    save(page, "user-menu.png")


def shoot_editor_and_versions(page):
    """Open the demo's draft, then save it once more so there are two versions."""
    page.goto(f"{BASE}/desk/?tab=drafts")
    page.locator(".post-row h2 a").first.click()
    save(page, "editor.png")
    body = page.locator("[data-body]")
    extra = "The tests broke next, and they were right."
    if extra not in body.input_value():  # the demo keeps it for an hour, if this runs twice
        body.fill(f"{body.input_value()}\n\n{extra}")
    page.get_by_role("button", name="Save draft").click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="Versions").click()
    save(page, "versions.png")


def shoot_phone_menu(page):
    page.goto(f"{BASE}/")
    page.get_by_role("button", name="Menu").click()
    save(page, "phone-menu.png")


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        shoot_visitor_pages(browser)
        shoot_people_page(browser)

        pages = {}
        for name, path, theme, size in PAGES:
            key = (theme, size["width"])
            if key not in pages:
                pages[key] = demo_page(browser, theme, size)
            page = pages[key]
            if "{post}" in path:
                page.goto(f"{BASE}/search?q=notebook")
                link = page.locator(".post-card h2 a", has_text="Why I Still Write by Hand").get_attribute("href")
                path = path.replace("{post}", link)
            shoot(page, name, path)

        desktop = pages[("light", DESKTOP["width"])]
        shoot_page_parts(desktop)
        shoot_editor_and_versions(desktop)
        shoot_phone_menu(pages[("light", PHONE["width"])])
        browser.close()


if __name__ == "__main__":
    main()
