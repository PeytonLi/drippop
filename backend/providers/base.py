# Verbatim from contracts/interfaces/providers.md; deviations: (1) SubmitRejected.__init__
# body stores safe_code/retryable attributes the worker needs; (2) DetectionResponse is
# resolvable for mypy via TYPE_CHECKING import of the TypedDict in core/contracts.py.
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
