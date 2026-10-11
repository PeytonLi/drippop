# Provider adapter interface (frozen)

Owner: lane 2D (backend/providers/). Consumers: backend/api (detect) and backend/worker (submit/check).
Workers own job state, retries, leases and budget; adapters own only one bounded upstream call each.

```python
# backend/providers/base.py  (coordinator-owned signature; lane 1C/2D implements)
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from core.contracts import DetectionResponse
else:
    DetectionResponse = dict[str, Any]

Category = Literal["upper_body", "full_body", "lower_body", "shoes", "outer", "auto"]


@dataclass(frozen=True)
class PreparedImage:
    data: bytes  # validated, re-encoded, EXIF-stripped, upright
    mime: Literal["image/jpeg", "image/png"]
    width: int
    height: int


@dataclass(frozen=True)
class ProviderTicket:
    provider: str  # "youcam_clothes_v4" | "fake"
    task_id: str  # backend-only; never returned to clients


@dataclass(frozen=True)
class Pending: ...


@dataclass(frozen=True)
class Succeeded:
    output_url: str  # backend-only; validate scheme/host allowlist before download


@dataclass(frozen=True)
class Failed:
    safe_code: str  # one of contracts/schemas/error.schema.json codes


CheckResult = Pending | Succeeded | Failed


class SubmitRejected(Exception):
    """Upstream definitely did NOT accept the task (4xx validation, auth, insufficient units)."""

    def __init__(self, safe_code: str, retryable: bool = False):
        super().__init__(safe_code)
        self.safe_code = safe_code
        self.retryable = retryable


class SubmitAmbiguous(Exception):
    """Upstream MAY have accepted the task (timeout after send, 5xx, connection reset,
    unparseable 2xx).
    The worker moves the job to internal submission_unknown and NEVER resubmits automatically."""


class DetectionProvider(Protocol):
    async def detect(self, frame: PreparedImage) -> "DetectionResponse": ...

    # Returns contract-valid DetectionResponse (normalized_upright_xyxy, validated, no confidence).
    # Malformed/out-of-range model output -> empty persons + manual_selection_required=True.


class GenerationProvider(Protocol):
    async def submit(
        self, person: PreparedImage, reference: PreparedImage, category: Category
    ) -> ProviderTicket: ...
    async def check(self, ticket: ProviderTicket) -> CheckResult: ...
    async def download(
        self, output_url: str, max_bytes: int
    ) -> bytes: ...  # host allowlist enforced here
```

### Adapter-level exceptions
Besides the base types above, adapters raise these from their own modules; the worker/API must handle them:
- `DetectionUnavailable(safe_code, retryable)`: `detect()` could not get a usable answer (transport error, non-2xx, broken envelope). The API maps it to 503 `analysis_unavailable` and the client falls back to manual selection. A malformed-but-parsed model answer is NOT an exception: it returns `persons=[]`, `manual_selection_required=true`.
- `DownloadError(safe_code, retryable)`: `download()` refused or failed (disallowed scheme/host/port/userinfo, any 3xx, oversize, non-2xx). `403/404/410` is `result_expired` with retryable=true, meaning re-run `check()` for a fresh URL; never resubmit.
`DetectionResponse` is the TypedDict in `backend/core/contracts.py` that mirrors `contracts/schemas/detection_response.schema.json`.

Rules
- Every HTTP call has explicit connect/read/write/pool timeouts (httpx.Timeout) and no automatic retry inside the adapter.
- Never log image bytes, provider keys, raw model text or output URLs. Log opaque job IDs, safe codes, durations, units.
- A `FakeGenerationProvider` / `FakeDetectionProvider` lives in backend/providers/fake.py and is selected by `PROVIDER_MODE=fake`. Fake results are visibly watermarked "FAKE PREVIEW".
