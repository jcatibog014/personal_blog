"""Draw the demo posts' cover pictures (akda/seed_covers/*.webp).

Plain shapes in the site's own ink, paper and crimson colours, so no photo
licences are needed. Run it again only to change the pictures:

    .venv\\Scripts\\python docs\\make_covers.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent.parent / "akda" / "seed_covers"
WIDTH, HEIGHT = 1200, 800
SCALE = 2  # draw big, then shrink, for smooth edges

INK = "#141414"
PAPER = "#f3efe4"
CRIMSON = "#a4161a"
SAND = "#d9c9a8"
SLATE = "#3b4a54"


def canvas(colour):
    image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), colour)
    return image, ImageDraw.Draw(image)


def scaled(*points):
    return [point * SCALE for point in points]


def lines_of_writing():
    """Handwriting: pen strokes across a page."""
    image, draw = canvas(PAPER)
    for row, width in enumerate((880, 980, 760, 930, 610, 840)):
        y = 170 + row * 85
        draw.rounded_rectangle(scaled(130, y, 130 + width, y + 16), radius=8 * SCALE, fill=INK)
    draw.ellipse(scaled(840, 520, 1060, 740), fill=CRIMSON)
    return image


def morning_hills():
    """Sun over layered hills."""
    image, draw = canvas(SAND)
    draw.ellipse(scaled(730, 130, 1000, 400), fill=CRIMSON)
    draw.polygon(scaled(0, 520, 300, 330, 620, 540, 880, 400, 1200, 560, 1200, 800, 0, 800), fill=SLATE)
    draw.polygon(scaled(0, 660, 360, 500, 760, 680, 1020, 560, 1200, 640, 1200, 800, 0, 800), fill=INK)
    return image


def road_at_night():
    """A straight road running into the distance."""
    image, draw = canvas(INK)
    draw.polygon(scaled(530, 280, 670, 280, 1120, 800, 80, 800), fill=SLATE)
    for start, length in ((300, 40), (390, 70), (520, 110), (680, 120)):
        half = 3 + (start - 280) // 40
        draw.rectangle(scaled(600 - half, start, 600 + half, start + length), fill=PAPER)
    draw.ellipse(scaled(555, 150, 645, 240), fill=CRIMSON)
    return image


def stack_of_books():
    """Books lying in a pile."""
    image, draw = canvas(CRIMSON)
    books = [(250, 950, INK), (300, 860, PAPER), (220, 900, SAND), (340, 880, SLATE)]
    y = 620
    for left, right, colour in books:
        draw.rectangle(scaled(left, y, right, y + 95), fill=colour)
        y -= 110
    return image


COVERS = {
    "writing": lines_of_writing,
    "hills": morning_hills,
    "road": road_at_night,
    "books": stack_of_books,
}


def main():
    OUT.mkdir(exist_ok=True)
    for name, draw_cover in COVERS.items():
        image = draw_cover().resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        path = OUT / f"{name}.webp"
        image.save(path, "WEBP", quality=80, method=6)
        print(path.name, path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
