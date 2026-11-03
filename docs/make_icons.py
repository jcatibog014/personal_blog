"""Draw the app icon (akda/static/icons/): the masthead's "A" on a crimson tile, with a rule under it.

It uses the site's own Playfair Display font, so the icon matches the wordmark.
Phones and browsers want PNG pictures in fixed sizes, plus favicon.ico. Run this
again after changing the design. Like take_screenshots.py, it uses Playwright + Edge:

    .venv\\Scripts\\python -m pip install playwright
    .venv\\Scripts\\python docs\\make_icons.py
"""
import base64
import struct
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
ICONS = ROOT / "akda" / "static" / "icons"
FONT = ROOT / "akda" / "static" / "fonts" / "playfair-display-700.woff2"

# The site's crimson accent, not its ink: an ink tile vanishes on a dark browser
# tab or a dark phone screen, and crimson stands out on light and dark alike.
TILE = "#a4161a"  # the light theme's --accent
PAPER = "#fbfaf6"  # the light theme's --paper (7.6:1 on the crimson)

# (file, size, shape). "rounded" has see-through corners, for browser tabs and
# installed apps. "square" fills every pixel: iPhones round the corners
# themselves, and Android crops a "maskable" icon into its own shape.
PNGS = [
    ("icon-32.png", 32, "rounded"),
    ("icon-192.png", 192, "rounded"),
    ("icon-512.png", 512, "rounded"),
    ("icon-maskable-512.png", 512, "square"),
    ("apple-touch-icon.png", 180, "square"),
]
ICO_SIZES = (16, 32, 48)


def page_html(size, shape, font_data):
    radius = round(size * 0.22) if shape == "rounded" else 0
    # A maskable icon can be cropped to a circle, so its drawing stays in the middle 70%.
    scale = 0.85 if shape == "square" else 1
    letter = size * 0.66 * scale
    rule_height = max(1, round(size * 0.05 * scale))
    return f"""<!doctype html>
<style>
  @font-face {{ font-family: Playfair; font-weight: 700;
               src: url(data:font/woff2;base64,{font_data}) format("woff2"); }}
  html, body {{ margin: 0; background: transparent; }}
  .tile {{ position: relative; width: {size}px; height: {size}px; background: {TILE};
           border-radius: {radius}px; overflow: hidden; }}
  .letter {{ position: absolute; left: 0; right: 0; top: {size * (0.5 - 0.091 * scale)}px; transform: translateY(-50%);
             text-align: center; font: 700 {letter}px/1 Playfair, Georgia, serif; color: {PAPER}; }}
  .rule {{ position: absolute; left: 50%; top: {size * (0.5 + 0.236 * scale)}px; transform: translateX(-50%);
           width: {round(size * 0.38 * scale)}px; height: {rule_height}px; background: {PAPER}; }}
</style>
<div class="tile"><div class="letter">A</div><div class="rule"></div></div>"""


def render(browser, size, shape, font_data):
    page = browser.new_page(viewport={"width": size, "height": size})
    page.set_content(page_html(size, shape, font_data))
    page.evaluate("document.fonts.ready.then(() => true)")
    png = page.locator(".tile").screenshot(omit_background=True)
    page.close()
    return png


def write_ico(path, pictures):
    """favicon.ico is a small header, a list, then the PNG files themselves."""
    header = struct.pack("<HHH", 0, 1, len(pictures))
    offset = 6 + 16 * len(pictures)
    entries, data = b"", b""
    for size, png in pictures:
        entries += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    path.write_bytes(header + entries + data)


def main():
    ICONS.mkdir(exist_ok=True)
    font_data = base64.b64encode(FONT.read_bytes()).decode()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        for name, size, shape in PNGS:
            (ICONS / name).write_bytes(render(browser, size, shape, font_data))
            print("saved", name)
        write_ico(ICONS / "favicon.ico", [(size, render(browser, size, "rounded", font_data)) for size in ICO_SIZES])
        print("saved favicon.ico")
        browser.close()


if __name__ == "__main__":
    main()
