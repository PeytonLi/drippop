from typing import Any

INTERNAL_STATES = (
    "queued",
    "ready_to_submit",
    "submitting",
    "polling",
    "finalizing",
    "succeeded",
    "failed",
    "submission_unknown",
    "canceled",
)

TERMINAL = {"succeeded", "failed", "submission_unknown", "canceled"}


def public_for(internal: str) -> tuple[str, str]:
    """Map internal state to (public status, public phase)."""
    return {
        "queued": ("queued", "queued"),
        "ready_to_submit": ("processing", "preparing"),
        "submitting": ("processing", "generating"),
        "polling": ("processing", "generating"),
        "finalizing": ("processing", "finalizing"),
        "succeeded": ("succeeded", "finalizing"),
        "failed": ("failed", "queued"),
        "submission_unknown": ("failed", "generating"),
        "canceled": ("canceled", "queued"),
    }[internal]


def public_error_code(job: dict[str, Any]) -> str | None:
    internal = job["internal_state"]
    if internal == "submission_unknown":
        return "generation_status_unknown"
    if internal == "failed":
        return job.get("error_code") or "service_unavailable"
    return None
