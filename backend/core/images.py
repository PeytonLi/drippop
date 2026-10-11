import io
import warnings
from typing import Literal

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

from core.errors import ApiError
from core.settings import Settings
from providers.base import PreparedImage

ImageFile.LOAD_TRUNCATED_IMAGES = False

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

Role = Literal["frame", "person", "reference"]


def _invalid(status: int = 422, code: str = "invalid_image") -> ApiError:
    return ApiError(status, code)


def validate_and_prepare(data: bytes, *, role: Role, settings: Settings) -> PreparedImage:
    if len(data) == 0:
        raise _invalid()
    if len(data) > settings.max_image_bytes:
        raise _invalid(413)

    if data[:3] == _JPEG_MAGIC:
        expected = "JPEG"
    elif data[:8] == _PNG_MAGIC:
        expected = "PNG"
    else:
        raise _invalid()

    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG"]) as probe:
                if probe.format != expected:
                    raise _invalid()
                width, height = probe.size
                if getattr(probe, "is_animated", False):
                    raise _invalid()
                if (
                    width * height > settings.max_image_pixels
                    or max(width, height) > settings.max_image_side
                ):
                    raise _invalid(413)
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG"]) as im:
                im.load()
                upright = ImageOps.exif_transpose(im)
    except ApiError:
        raise
    except Image.DecompressionBombError:
        raise _invalid(413) from None
    except (OSError, SyntaxError, ValueError, UnidentifiedImageError) as exc:
        if isinstance(exc, Image.DecompressionBombError):
            raise _invalid(413) from None
        raise _invalid() from None

    width, height = upright.size
    if width * height > settings.max_image_pixels or max(width, height) > settings.max_image_side:
        raise _invalid(413)

    if role in ("person", "reference"):
        short, long_ = min(width, height), max(width, height)
        if short < settings.min_gen_short_side or long_ < settings.min_gen_long_side:
            code = "unsupported_reference" if role == "reference" else "invalid_image"
            raise _invalid(422, code)
    else:
        if min(width, height) < 32:
            raise _invalid()

    if expected == "JPEG":
        out = upright.convert("RGB")
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=92)
        mime: Literal["image/jpeg", "image/png"] = "image/jpeg"
    else:
        has_alpha = upright.mode in ("RGBA", "LA", "PA") or (
            upright.mode == "P" and "transparency" in upright.info
        )
        out = upright.convert("RGBA" if has_alpha else "RGB")
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        mime = "image/png"

    return PreparedImage(data=buf.getvalue(), mime=mime, width=width, height=height)
