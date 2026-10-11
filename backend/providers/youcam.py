import json
import logging
import time
from typing import Any, Literal, cast
from urllib.parse import quote, urlsplit

import httpx

from providers.base import (
    Category,
    CheckResult,
    Failed,
    Pending,
    PreparedImage,
    ProviderTicket,
    SubmitAmbiguous,
    SubmitRejected,
    Succeeded,
)

DEFAULT_OUTPUT_HOSTS = frozenset({"yce-us.s3-accelerate.amazonaws.com"})
DEFAULT_UPLOAD_HOSTS = frozenset({"yce-us.s3-accelerate.amazonaws.com"})
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_SIDE = 4096
SUPPORTED_CATEGORIES = frozenset(
    {"full_body", "lower_body", "upper_body", "shoes", "auto", "outer"}
)

ENGINE_ERROR_CODES = {
    "error_pose": "unsupported_reference",
    "error_no_face": "unsupported_reference",
    "error_face_parsing": "unsupported_reference",
    "error_invalid_ref": "unsupported_reference",
    "error_invalid_src": "unsupported_reference",
    "error_apply_region_mismatch": "unsupported_reference",
    "error_multi_person": "unsupported_reference",
    "error_multiple_people": "unsupported_reference",
    "error_no_shoulder": "unsupported_reference",
    "error_large_face_angle": "unsupported_reference",
    "error_unsupport_ratio": "unsupported_reference",
    "error_below_min_image_size": "unsupported_reference",
    "error_exceed_max_image_size": "unsupported_reference",
    "exceed_max_filesize": "unsupported_reference",
    "error_decode_image": "unsupported_reference",
}

logger = logging.getLogger("drippop.providers.youcam")


class DownloadError(Exception):
    def __init__(self, safe_code: str, retryable: bool):
        self.safe_code = safe_code
        self.retryable = retryable
        super().__init__(safe_code, retryable)


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        value = response.json()
    except (ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


class YouCamGenerationProvider:
    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://yce-api-01.makeupar.com",
        output_hosts: frozenset[str] = DEFAULT_OUTPUT_HOSTS,
        upload_hosts: frozenset[str] = DEFAULT_UPLOAD_HOSTS,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        filter_multi_person: Literal["off", "normal", "strict"] = "normal",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.output_hosts = frozenset(host.lower() for host in output_hosts)
        self.upload_hosts = frozenset(host.lower() for host in upload_hosts)
        self.timeout = timeout
        self.filter_multi_person = filter_multi_person
        self.client = client or httpx.AsyncClient(follow_redirects=False, timeout=timeout)
        self.client.headers.pop("Authorization", None)

    def _log(self, stage: str, status: int | None, code: str, started: float) -> None:
        logger.info(
            "stage=%s status=%s safe_code=%s duration_ms=%d",
            stage,
            status,
            code,
            int((time.perf_counter() - started) * 1000),
        )

    def _allowed_url(self, url: str, hosts: frozenset[str]) -> bool:
        try:
            parsed = urlsplit(url)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.scheme.lower() == "https"
            and hostname is not None
            and hostname.lower() in hosts
            and parsed.username is None
            and parsed.password is None
            and port in (None, 443)
        )

    def _reject_file_status(self, status: int) -> SubmitRejected:
        if status in (401, 403):
            return SubmitRejected("service_unavailable", False)
        if status == 429 or status >= 500:
            return SubmitRejected("service_unavailable", True)
        if 400 <= status < 500:
            return SubmitRejected("provider_rejected", False)
        return SubmitRejected("provider_rejected", False)

    async def _upload(self, image: PreparedImage, file_name: str) -> str:
        started = time.perf_counter()
        status: int | None = None
        try:
            response = await self.client.post(
                f"{self.base_url}/s2s/v2.0/file",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "files": [
                        {
                            "content_type": "image/jpg"
                            if image.mime == "image/jpeg"
                            else "image/png",
                            "file_name": file_name,
                            "file_size": len(image.data),
                        }
                    ]
                },
                timeout=self.timeout,
                follow_redirects=False,
            )
            status = response.status_code
            if not 200 <= status < 300:
                error = self._reject_file_status(status)
                self._log("file_create", status, error.args[0], started)
                raise error
            payload = _json_object(response)
            files = payload.get("data", {}).get("files") if payload else None
            item = files[0] if isinstance(files, list) and files else None
            requests = item.get("requests") if isinstance(item, dict) else None
            request = requests[0] if isinstance(requests, list) and requests else None
            file_id = item.get("file_id") if isinstance(item, dict) else None
            upload_url = request.get("url") if isinstance(request, dict) else None
            method = request.get("method") if isinstance(request, dict) else None
            headers = request.get("headers") if isinstance(request, dict) else None
            if method is not None and method != "PUT":
                self._log("file_create", status, "provider_rejected", started)
                raise SubmitRejected("provider_rejected", False)
            if (
                isinstance(upload_url, str)
                and upload_url
                and not self._allowed_url(upload_url, self.upload_hosts)
            ):
                self._log("file_create", status, "provider_rejected", started)
                raise SubmitRejected("provider_rejected", False)
            if (
                not isinstance(file_id, str)
                or not file_id
                or method != "PUT"
                or not isinstance(upload_url, str)
                or not upload_url
                or not isinstance(headers, dict)
                or any(
                    not isinstance(key, str) or not isinstance(value, str)
                    for key, value in headers.items()
                )
            ):
                self._log("file_create", status, "service_unavailable", started)
                raise SubmitRejected("service_unavailable", True)
        except SubmitRejected:
            raise
        except httpx.TransportError as exc:
            self._log("file_create", status, "service_unavailable", started)
            raise SubmitRejected("service_unavailable", True) from exc
        except (TypeError, AttributeError, IndexError):
            self._log("file_create", status, "service_unavailable", started)
            raise SubmitRejected("service_unavailable", True) from None

        upload_started = time.perf_counter()
        upload_status: int | None = None
        try:
            uploaded = await self.client.put(
                upload_url,
                content=image.data,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=False,
                auth=cast(Any, None),
            )
            upload_status = uploaded.status_code
            if not 200 <= upload_status < 300:
                error = self._reject_file_status(upload_status)
                self._log("file_upload", upload_status, error.args[0], upload_started)
                raise error
        except SubmitRejected:
            raise
        except httpx.TransportError as exc:
            self._log("file_upload", upload_status, "service_unavailable", upload_started)
            raise SubmitRejected("service_unavailable", True) from exc
        self._log("file_upload", upload_status, "ok", upload_started)
        self._log("file_create", status, "ok", started)
        return file_id

    async def submit(
        self, person: PreparedImage, reference: PreparedImage, category: Category
    ) -> ProviderTicket:
        if category not in SUPPORTED_CATEGORIES:
            raise SubmitRejected("category_unavailable", False)
        if any(
            len(image.data) >= MAX_IMAGE_BYTES or max(image.width, image.height) > MAX_IMAGE_SIDE
            for image in (person, reference)
        ):
            raise SubmitRejected("invalid_image", False)

        src_file_id = await self._upload(person, "person.jpg")
        ref_file_id = await self._upload(reference, "reference.png")
        started = time.perf_counter()
        status: int | None = None
        url = f"{self.base_url}/s2s/v2.0/task/cloth-v4"
        try:
            response = await self.client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "src_file_id": src_file_id,
                    "ref_file_id": ref_file_id,
                    "garment_category": category,
                    "filter_multi_person": self.filter_multi_person,
                },
                timeout=self.timeout,
                follow_redirects=False,
            )
            status = response.status_code
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            self._log("task_submit", None, "service_unavailable", started)
            raise SubmitRejected("service_unavailable", True) from exc
        except httpx.TransportError as exc:
            self._log("task_submit", None, "submission_ambiguous", started)
            raise SubmitAmbiguous() from exc

        if 200 <= status < 300:
            payload = _json_object(response)
            data = payload.get("data") if payload else None
            task_id = data.get("task_id") if isinstance(data, dict) else None
            if isinstance(task_id, str) and task_id:
                self._log("task_submit", status, "ok", started)
                return ProviderTicket("youcam_clothes_v4", task_id)
            self._log("task_submit", status, "submission_ambiguous", started)
            raise SubmitAmbiguous()
        if status == 400:
            payload = _json_object(response)
            code = (
                "quota_exceeded"
                if payload and payload.get("error_code") == "CreditInsufficiency"
                else "provider_rejected"
            )
            self._log("task_submit", status, code, started)
            raise SubmitRejected(code, False)
        if status in (401, 403):
            self._log("task_submit", status, "service_unavailable", started)
            raise SubmitRejected("service_unavailable", False)
        if status == 429:
            self._log("task_submit", status, "service_unavailable", started)
            raise SubmitRejected("service_unavailable", True)
        if 400 <= status < 500:
            self._log("task_submit", status, "provider_rejected", started)
            raise SubmitRejected("provider_rejected", False)
        self._log("task_submit", status, "submission_ambiguous", started)
        raise SubmitAmbiguous()

    async def check(self, ticket: ProviderTicket) -> CheckResult:
        started = time.perf_counter()
        status: int | None = None
        task_id = quote(ticket.task_id, safe="")
        try:
            response = await self.client.get(
                f"{self.base_url}/s2s/v2.0/task/cloth-v4/{task_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
                follow_redirects=False,
            )
            status = response.status_code
        except httpx.TransportError:
            self._log("task_check", None, "pending", started)
            return Pending()

        if status == 400:
            self._log("task_check", status, "generation_status_unknown", started)
            return Failed("generation_status_unknown")
        if status == 500:
            payload = _json_object(response)
            error = payload.get("error") if payload else None
            if isinstance(error, str) and "timed out" in error.lower():
                self._log("task_check", status, "generation_timeout", started)
                return Failed("generation_timeout")
        if status != 200:
            self._log("task_check", status, "pending", started)
            return Pending()

        payload = _json_object(response)
        data = payload.get("data") if payload else None
        if not isinstance(data, dict):
            self._log("task_check", status, "pending", started)
            return Pending()
        task_status = data.get("task_status")
        result: CheckResult = Pending()
        if task_status == "running":
            result = Pending()
        elif task_status == "success":
            results = data.get("results")
            output_url = results.get("url") if isinstance(results, dict) else None
            result = (
                Succeeded(output_url) if isinstance(output_url, str) and output_url else Pending()
            )
        elif task_status == "error":
            error = data.get("error")
            safe_code = (
                ENGINE_ERROR_CODES.get(error, "provider_rejected")
                if isinstance(error, str)
                else "provider_rejected"
            )
            result = Failed(safe_code)
        else:
            result = Pending()
        code = (
            result.safe_code
            if isinstance(result, Failed)
            else "ok"
            if not isinstance(result, Pending)
            else "pending"
        )
        self._log("task_check", status, code, started)
        return result

    async def download(self, output_url: str, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if not self._allowed_url(output_url, self.output_hosts):
            raise DownloadError("provider_rejected", False)

        started = time.perf_counter()
        status: int | None = None
        try:
            async with self.client.stream(
                "GET",
                output_url,
                timeout=self.timeout,
                follow_redirects=False,
                auth=None,
            ) as response:
                status = response.status_code
                if 300 <= status < 400:
                    self._log("result_download", status, "provider_rejected", started)
                    raise DownloadError("provider_rejected", False)
                if status in (403, 404, 410):
                    self._log("result_download", status, "result_expired", started)
                    raise DownloadError("result_expired", True)
                if status != 200:
                    self._log("result_download", status, "service_unavailable", started)
                    raise DownloadError("service_unavailable", True)
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        too_large = int(content_length) > max_bytes
                    except ValueError:
                        too_large = False
                    if too_large:
                        self._log("result_download", status, "provider_rejected", started)
                        raise DownloadError("provider_rejected", False)
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        self._log("result_download", status, "provider_rejected", started)
                        raise DownloadError("provider_rejected", False)
                    chunks.append(chunk)
                self._log("result_download", status, "ok", started)
                return b"".join(chunks)
        except DownloadError:
            raise
        except httpx.TransportError as exc:
            self._log("result_download", status, "service_unavailable", started)
            raise DownloadError("service_unavailable", True) from exc
