import io
import zlib

import pytest
from PIL import Image

from core.errors import ApiError
from core.images import validate_and_prepare
from tests.conftest import idem_headers, job_form, make_jpeg, make_png


def _png_bytes(w: int, h: int) -> bytes:
    """Minimal valid PNG header declaring w x h, 1-bit, zlib zeros."""
    import struct

    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 1, 0, 0, 0, 0))
    row_bytes = (w + 7) // 8 + 1
    raw = zlib.compress(b"\x00" * row_bytes * h)
    idat = chunk(b"IDAT", raw)
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


async def test_valid_jpeg(settings):
    p = validate_and_prepare(make_jpeg(500, 700), role="person", settings=settings)
    assert p.mime == "image/jpeg" and (p.width, p.height) == (500, 700)


async def test_valid_png(settings):
    p = validate_and_prepare(make_png(500, 700), role="person", settings=settings)
    assert p.mime == "image/png"


async def test_exif_orientation_swaps_dims_and_strips(settings):
    im = Image.new("RGB", (400, 200), (10, 20, 30))
    im.putpixel((0, 0), (255, 0, 0))
    exif = Image.Exif()
    exif[274] = 6  # orientation: rotate 90 CW
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)
    p = validate_and_prepare(buf.getvalue(), role="frame", settings=settings)
    assert (p.width, p.height) == (200, 400)
    out = Image.open(io.BytesIO(p.data))
    assert not out.info.get("exif")


async def test_gif_rejected(settings):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, format="GIF")
    with pytest.raises(ApiError) as e:
        validate_and_prepare(buf.getvalue(), role="frame", settings=settings)
    assert e.value.status == 422


async def test_webp_rejected(settings):
    try:
        buf = io.BytesIO()
        Image.new("RGB", (100, 100)).save(buf, format="WEBP")
    except Exception:
        pytest.skip("webp unsupported by pillow build")
    with pytest.raises(ApiError):
        validate_and_prepare(buf.getvalue(), role="frame", settings=settings)


async def test_declared_huge_png_413_fast(settings):
    data = _png_bytes(20000, 20000)
    assert len(data) < settings.max_image_bytes
    with pytest.raises(ApiError) as e:
        validate_and_prepare(data, role="frame", settings=settings)
    assert e.value.status == 413


async def test_too_many_bytes_413(settings):
    with pytest.raises(ApiError) as e:
        validate_and_prepare(b"x" * (settings.max_image_bytes + 1), role="frame", settings=settings)
    assert e.value.status == 413


async def test_truncated_jpeg_422(settings):
    data = make_jpeg(200, 200)
    with pytest.raises(ApiError) as e:
        validate_and_prepare(data[: len(data) // 3], role="frame", settings=settings)
    assert e.value.status == 422


async def test_random_bytes_422(settings):
    with pytest.raises(ApiError):
        validate_and_prepare(b"\x00" * 100, role="frame", settings=settings)


async def test_apng_rejected(settings):
    # minimal animated PNG signature: acTL chunk present -> is_animated

    im1 = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    buf = io.BytesIO()
    im1.save(
        buf,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGBA", (64, 64), (0, 255, 0, 255))],
    )
    data = buf.getvalue()
    assert b"acTL" in data
    with pytest.raises(ApiError):
        validate_and_prepare(data, role="frame", settings=settings)


async def test_tiny_person_422(settings):
    with pytest.raises(ApiError) as e:
        validate_and_prepare(make_jpeg(100, 100), role="person", settings=settings)
    assert e.value.status == 422 and e.value.code == "invalid_image"


async def test_tiny_reference_unsupported(settings):
    with pytest.raises(ApiError) as e:
        validate_and_prepare(make_jpeg(100, 100), role="reference", settings=settings)
    assert e.value.code == "unsupported_reference"


async def test_png_text_chunk_stripped(settings):
    from PIL import PngImagePlugin

    im = Image.new("RGB", (512, 600))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Comment", "secret-data")
    buf = io.BytesIO()
    im.save(buf, format="PNG", pnginfo=meta)
    p = validate_and_prepare(buf.getvalue(), role="person", settings=settings)
    out = Image.open(io.BytesIO(p.data))
    assert "Comment" not in out.info and "secret-data" not in str(out.info)


# --- via API -----------------------------------------------------------------


async def test_api_gif_422(client, auth):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, format="GIF")
    r = await client.post(
        "/v1/garments:detect",
        headers=auth(),
        files={"frame": ("f.gif", buf.getvalue(), "image/gif")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_image"


async def test_api_oversized_413(client, auth):
    big = b"\xff\xd8\xff" + b"0" * (9 * 1024 * 1024)
    r = await client.post(
        "/v1/garments:detect",
        headers=auth(),
        files={"frame": ("f.jpg", big, "image/jpeg")},
    )
    assert r.status_code == 413


async def test_api_metadata_extra_keys_422(client, auth):
    for meta in (
        {"garment_category": "upper_body", "reference_url": "https://x/y.jpg"},
        {"garment_category": "upper_body", "owner_uid": "abc"},
    ):
        r = await client.post("/v1/jobs", headers=idem_headers(auth()), **job_form(metadata=meta))
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "invalid_request"


async def test_api_missing_idempotency_key_400(client, auth):
    r = await client.post("/v1/jobs", headers=auth(), **job_form())
    assert r.status_code == 400


async def test_non_integer_content_length_422(settings):
    from unittest.mock import MagicMock

    from api.main import _parse_form

    request = MagicMock()
    request.headers = {"content-length": "not-a-number"}
    with pytest.raises(ApiError) as e:
        await _parse_form(request, settings, {"frame"})
    assert e.value.status == 422 and e.value.code == "invalid_request"


async def test_api_bad_idempotency_key_400(client, auth):
    r = await client.post("/v1/jobs", headers=idem_headers(auth(), "bad key!!"), **job_form())
    assert r.status_code == 400
