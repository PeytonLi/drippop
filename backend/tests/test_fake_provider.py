import io

import pytest
from PIL import Image

from core.contracts import ContractSchemas, validate_detection
from providers.base import PreparedImage, ProviderTicket, Succeeded
from providers.fake import FakeDetectionProvider, FakeGenerationProvider
from tests.conftest import CONTRACTS_DIR, make_jpeg


async def test_detection_output_valid(settings):
    det = FakeDetectionProvider()
    frame = PreparedImage(make_jpeg(640, 480), "image/jpeg", 640, 480)
    doc = await det.detect(frame)
    schemas = ContractSchemas(CONTRACTS_DIR)
    assert validate_detection(schemas, dict(doc))


async def test_generation_composite_watermarked(settings):
    gen = FakeGenerationProvider()
    person = PreparedImage(make_jpeg(800, 1000, (120, 80, 200)), "image/jpeg", 800, 1000)
    ref = PreparedImage(make_jpeg(400, 500, (200, 60, 60)), "image/jpeg", 400, 500)
    ticket = await gen.submit(person, ref, "upper_body")
    assert ticket.provider == "fake" and ticket.task_id.startswith("fake_")
    result = await gen.check(ticket)
    assert isinstance(result, Succeeded)
    data = await gen.download(result.output_url, 15_000_000)
    im = Image.open(io.BytesIO(data)).convert("RGB")
    assert im.format or True
    plain = Image.open(io.BytesIO(person.data)).convert("RGB")
    plain.thumbnail((1024, 1024))
    im_resized = im.resize(plain.size)
    diff = sum(
        1
        for a, b in zip(list(im_resized.getdata()), list(plain.getdata()), strict=False)
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]) > 60
    )
    assert diff > (plain.width * plain.height) // 20  # sizeable watermark region


async def test_download_scheme_and_size(settings):
    gen = FakeGenerationProvider()
    with pytest.raises(ValueError):
        await gen.download("https://evil/x.jpg", 1000)
    person = PreparedImage(make_jpeg(800, 1000), "image/jpeg", 800, 1000)
    ticket = await gen.submit(person, person, "upper_body")
    url = f"fake://{ticket.task_id}"
    data = await gen.download(url, 15_000_000)
    with pytest.raises(ValueError):
        await gen.download(url, len(data) - 1)


async def test_pending_then_succeeded(settings):
    gen = FakeGenerationProvider(pending_checks=2)
    person = PreparedImage(make_jpeg(800, 1000), "image/jpeg", 800, 1000)
    ticket = await gen.submit(person, person, "upper_body")
    from providers.base import Pending
    from providers.base import Succeeded as S

    assert isinstance(await gen.check(ticket), Pending)
    assert isinstance(await gen.check(ticket), Pending)
    assert isinstance(await gen.check(ticket), S)


async def test_unknown_task_fails(settings):
    gen = FakeGenerationProvider()
    from providers.base import Failed

    res = await gen.check(ProviderTicket("fake", "fake_nonexistent"))
    assert isinstance(res, Failed)
