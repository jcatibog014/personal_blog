"""Take the README screenshots (docs/screenshots/*.png).

It logs in with "Try Demo", so only sample posts show. It uses Microsoft
Edge, which Windows already has, through Playwright. Playwright is only a tool
for this script, so it is not in requirements.txt:

    .venv\\Scripts\\python -m pip install playwright
    .venv\\Scripts\\flask --app akda run --port 5005      (in another terminal)
    .venv\\Scripts\\python docs\\take_screenshots.py

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

# (file name, address, theme, screen size). {post} is the demo's newest post.
PAGES = [
    ("home.png", "/", "light", DESKTOP),
    ("home-dark.png", "/", "dark", DESKTOP),
    ("article.png", "{post}", "light", DESKTOP),
    ("comments.png", "{post}#comments", "light", DESKTOP),
    ("my-posts.png", "/desk/?tab=published", "light", DESKTOP),
    ("moderation.png", "/desk/comments", "light", DESKTOP),
    ("reports.png", "/desk/comments?tab=reported", "dark", DESKTOP),
    ("tags.png", "/tags", "light", DESKTOP),
    ("archive.png", "/archive", "light", DESKTOP),
    ("phone.png", "/", "light", PHONE),
]


def demo_page(browser, theme, size):
    page = browser.new_page(viewport=size, color_scheme=theme)
    page.goto(f"{BASE}/login")
    page.get_by_role("button", name="Try Demo").click()
    page.wait_for_url("**/desk/**")
    return page


def shoot(page, name, path):
    page.goto(f"{BASE}{path}")
    page.wait_for_load_state("networkidle")  # fonts and pictures are in
    page.wait_for_timeout(300)
    page.screenshot(path=OUT / name)
    print("saved", name)


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")

        page = browser.new_page(viewport=DESKTOP, color_scheme="light")
        page.goto(f"{BASE}/login")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=OUT / "login.png")
        page.close()
        print("saved login.png")

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

        # The editor: open the demo's draft.
        page = pages[("light", DESKTOP["width"])]
        page.goto(f"{BASE}/desk/?tab=drafts")
        page.locator(".post-row h2 a").first.click()
        page.wait_for_load_state("networkidle")
        page.screenshot(path=OUT / "editor.png")
        print("saved editor.png")
        browser.close()


if __name__ == "__main__":
    main()
