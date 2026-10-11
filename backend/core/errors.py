SAFE_MESSAGES: dict[str, str] = {
    "invalid_image": "That image couldn't be used. Try a different JPEG or PNG photo.",
    "unsupported_reference": "That reference photo can't be used for a try-on.",
    "analysis_unavailable": "Photo analysis isn't available now. You can still pick manually.",
    "active_job_exists": "A try-on is already in progress.",
    "quota_exceeded": "You've reached today's limit. Try again tomorrow.",
    "idempotency_conflict": "This request was already sent with different details.",
    "provider_rejected": "The preview service couldn't accept this request.",
    "generation_status_unknown": "We couldn't confirm this preview. Start a new try-on.",
    "generation_timeout": "The preview took too long. Start a new try-on to try again.",
    "result_expired": "This preview has expired.",
    "job_canceled": "This try-on was canceled.",
    "unauthenticated": "Sign in to continue.",
    "not_found": "Not found.",
    "invalid_request": "The request couldn't be processed.",
    "category_unavailable": "That garment type isn't supported yet.",
    "service_unavailable": "The service is unavailable right now. Try again later.",
}


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str | None = None,
        retryable: bool = False,
        job_id: str | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = (message or SAFE_MESSAGES.get(code) or SAFE_MESSAGES["invalid_request"])[
            :300
        ]
        self.retryable = retryable
        self.job_id = job_id

    def body(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            },
            "job_id": self.job_id,
        }
