"""The app icon: every size exists, every page points at it, and the manifest is right."""
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from .conftest import log_in_as

ICONS = Path(__file__).parent.parent / "akda" / "static" / "icons"
STATIC = ICONS.parent


@pytest.mark.parametrize("name,size", [
    ("icon-32.png", 32), ("icon-192.png", 192), ("icon-512.png", 512),
    ("icon-maskable-512.png", 512), ("apple-touch-icon.png", 180),
])
def test_every_icon_has_its_size(name, size):
    with Image.open(ICONS / name) as icon:
        assert icon.format == "PNG" and icon.size == (size, size)


@pytest.mark.parametrize("name", ["icon-32.png", "icon-192.png", "icon-512.png"])
def test_tab_and_app_icons_have_rounded_see_through_corners(name):
    with Image.open(ICONS / name) as icon:
        rgba = icon.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0
        assert rgba.getpixel((rgba.width // 2, rgba.height // 2))[3] == 255


@pytest.mark.parametrize("name", ["icon-maskable-512.png", "apple-touch-icon.png"])
def test_phone_icons_fill_every_corner(name):
    """iPhones round the corners themselves, and Android crops a maskable icon."""
    with Image.open(ICONS / name) as icon:
        rgba = icon.convert("RGBA")
        for corner in ((0, 0), (rgba.width - 1, 0), (0, rgba.height - 1), (rgba.width - 1, rgba.height - 1)):
            assert rgba.getpixel(corner)[3] == 255


def test_the_maskable_drawing_stays_in_the_safe_middle():
    """Android may crop to a circle of 80%, so the letter and its rule must stay inside it."""
    with Image.open(ICONS / "icon-maskable-512.png") as icon:
        rgb = icon.convert("RGB")
        light = [(x, y) for y in range(0, 512, 2) for x in range(0, 512, 2) if min(rgb.getpixel((x, y))) > 200]
    centre, radius = 256, 512 * 0.4
    assert light and all((x - centre) ** 2 + (y - centre) ** 2 < radius ** 2 for x, y in light)


def test_favicon_ico_holds_three_sizes():
    with Image.open(ICONS / "favicon.ico") as icon:
        assert icon.info["sizes"] == {(16, 16), (32, 32), (48, 48)}


def test_favicon_address_at_the_root(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.mimetype == "image/vnd.microsoft.icon"
    assert response.data == (ICONS / "favicon.ico").read_bytes()


@pytest.mark.parametrize("url", ["/", "/login", "/about", "/desk/"])
def test_every_kind_of_page_points_at_the_icons(app, client, author_id, url):
    if url.startswith("/desk"):
        log_in_as(client, author_id)
    page = client.get(url).data
    for part in (b'rel="icon" href="/static/icons/favicon.ico"', b'href="/static/icons/icon-32.png"',
                 b'rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png"',
                 b'rel="manifest" href="/static/site.webmanifest"', b'name="theme-color"'):
        assert part in page, part


def test_every_icon_link_on_the_page_works(client):
    page = client.get("/").data.decode()
    links = re.findall(r'<link rel="(?:icon|apple-touch-icon|manifest)"[^>]*href="([^"]+)"', page)
    assert len(links) == 4
    for link in links:
        assert client.get(link).status_code == 200, link


def test_the_manifest_is_served_as_a_manifest_and_names_real_icons(client):
    response = client.get("/static/site.webmanifest")
    assert response.mimetype == "application/manifest+json"
    manifest = json.loads(response.data)
    assert manifest["name"] == "Akda" and manifest["start_url"] == "/"
    purposes = set()
    for entry in manifest["icons"]:
        width, height = (int(n) for n in entry["sizes"].split("x"))
        with Image.open(STATIC / entry["src"]) as icon:
            assert icon.size == (width, height), entry["src"]
        purposes.add(entry["purpose"])
    assert purposes == {"any", "maskable"}
