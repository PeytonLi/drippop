import io
import secrets
from collections.abc import Awaitable, Callable

from PIL import Image, ImageDraw

from core.contracts import DetectionResponse
from providers.base import (
    Category,
    CheckResult,
    Failed,
    Pending,
    PreparedImage,
    ProviderTicket,
    Succeeded,
)


class FakeDetectionProvider:
    async def detect(self, frame: PreparedImage) -> DetectionResponse:
        return DetectionResponse(
            image_width=frame.width,
            image_height=frame.height,
            coordinate_space="normalized_upright_xyxy",
            persons=[
                {
                    "id": "p1",
                    "box": [0.1, 0.05, 0.9, 0.98],
                    "garments": [
                        {
                            "id": "g1",
                            "category": "upper_body",
                            "box": [0.2, 0.25, 0.8, 0.6],
                        },
                        {
                            "id": "g2",
                            "category": "lower_body",
                            "box": [0.25, 0.55, 0.75, 0.95],
                        },
                    ],
                }
            ],
            manual_selection_required=False,
        )


def _decode(image: PreparedImage) -> Image.Image:
    return Image.open(io.BytesIO(image.data)).convert("RGB")


def _watermark(im: Image.Image) -> Image.Image:
    out = im.convert("RGBA")
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = out.size
    text = "FAKE PREVIEW"
    scale = max(2, min(w, h) // 20)
    bbox = draw.textbbox((0, 0), text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Tile a semi-transparent diagonal banner across the image.
    banner = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(banner)
    step = int(max(tw + scale * 6, 1))
    for y in range(-h, h * 2, step):
        bdraw.line((0, y, w, y - w), fill=(255, 32, 32, 90), width=max(4, scale // 2))
    for x in range(-h, w + h, step):
        for y in range(0, h, step):
            bdraw.text((x + y // 2, y), text, fill=(255, 255, 255, 200), font_size=scale * 4)
    overlay = Image.alpha_composite(overlay, banner)
    draw.rectangle(
        (w - tw - scale * 4, h - th - scale * 4, w - scale, h - scale), fill=(0, 0, 0, 120)
    )
    draw.text((w - tw - scale * 3, h - th - scale * 3), text, fill=(255, 255, 0, 255))
    return Image.alpha_composite(out, overlay).convert("RGB")


class FakeGenerationProvider:
    def __init__(
        self,
        *,
        submit_error: BaseException | None = None,
        pending_checks: int = 0,
        on_download: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.submit_error = submit_error
        self.pending_checks = pending_checks
        self.on_download = on_download
        self.submit_calls = 0
        self.check_calls = 0
        self.download_calls = 0
        self._objects: dict[str, bytes] = {}
        self._pending_left: dict[str, int] = {}

    async def submit(
        self, person: PreparedImage, reference: PreparedImage, category: Category
    ) -> ProviderTicket:
        self.submit_calls += 1
        if self.submit_error is not None:
            raise self.submit_error
        task_id = f"fake_{secrets.token_urlsafe(12)}"
        person_img = _decode(person)
        person_img.thumbnail((1024, 1024))
        ref_img = _decode(reference)
        ref_img.thumbnail((person_img.width // 3, person_img.height // 3))
        composite = person_img.copy()
        composite.paste(
            ref_img, (composite.width - ref_img.width - 8, composite.height - ref_img.height - 8)
        )
        composite = _watermark(composite)
        buf = io.BytesIO()
        composite.save(buf, format="JPEG", quality=90)
        self._objects[task_id] = buf.getvalue()
        self._pending_left[task_id] = self.pending_checks
        return ProviderTicket("fake", task_id)

    async def check(self, ticket: ProviderTicket) -> CheckResult:
        self.check_calls += 1
        if ticket.task_id not in self._objects:
            return Failed("provider_rejected")
        if self._pending_left.get(ticket.task_id, 0) > 0:
            self._pending_left[ticket.task_id] -= 1
            return Pending()
        return Succeeded(output_url=f"fake://{ticket.task_id}")

    async def download(self, output_url: str, max_bytes: int) -> bytes:
        self.download_calls += 1
        if self.on_download is not None:
            await self.on_download()
        if not output_url.startswith("fake://"):
            raise ValueError("disallowed output url scheme")
        task_id = output_url[len("fake://") :]
        data = self._objects.get(task_id)
        if data is None:
            raise ValueError("unknown output url")
        if len(data) > max_bytes:
            raise ValueError("result exceeds max_bytes")
        return data
