"""Make an uploaded picture small and safe before it goes into the database.

A phone photo is 3-8 MB. We shrink it to at most 1400 px on the long side and
save it as WebP (about 100-200 KB), because the free database is small and
Render's free disk is wiped on every restart. Saving a fresh copy also drops
the EXIF data, which can hold the GPS place where the photo was taken.
"""
import io

from PIL import Image as PillowImage, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select

from .models import Image

MAX_SIDE = 1400
QUALITY = 78
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "MPO"}  # MPO = some phone cameras' JPEG
# A "decompression bomb" is a tiny file that opens into a gigantic picture.
# Pillow refuses anything over this many pixels (about 50 megapixels).
PillowImage.MAX_IMAGE_PIXELS = 50_000_000
# So one account can't fill the free database.
MAX_PER_USER = 300
MAX_FOR_DEMO = 10


class PictureError(ValueError):
    """The upload isn't a picture we can use. The message is for the person."""


def process(raw):
    """Upload bytes -> (webp bytes, width, height). Raises PictureError."""
    if not raw:
        raise PictureError("Choose a picture first.")
    try:
        with PillowImage.open(io.BytesIO(raw)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise PictureError("Use a JPG, PNG, WebP or GIF picture.")
            image.load()
            # Phones save photos sideways plus a "turn me" note; apply it.
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            image.save(out, "WEBP", quality=QUALITY, method=4)
            return out.getvalue(), image.width, image.height
    except PictureError:
        raise
    except PillowImage.DecompressionBombError:
        raise PictureError("That picture is too big. Try a smaller one.") from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise PictureError("That file isn't a picture we can read.") from None


def add(s, user, raw):
    """Upload bytes -> a new Image row. Raises PictureError. The caller commits."""
    limit = MAX_FOR_DEMO if user.is_demo else MAX_PER_USER
    with s.no_autoflush:  # the caller may be halfway through changing a post
        used = s.scalar(select(func.count()).select_from(Image).where(Image.owner_id == user.id))
    if used >= limit:
        raise PictureError(f"You have reached the limit of {limit} pictures.")
    data, width, height = process(raw)
    image = Image(owner_id=user.id, data=data, mime="image/webp", width=width, height=height, size=len(data))
    s.add(image)
    return image
