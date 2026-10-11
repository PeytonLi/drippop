import json
import logging
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
import respx

from providers.base import (
    Failed,
    Pending,
    PreparedImage,
    ProviderTicket,
    SubmitAmbiguous,
    SubmitRejected,
    Succeeded,
)
from providers.youcam import (
    DEFAULT_OUTPUT_HOSTS,
    ENGINE_ERROR_CODES,
    DownloadError,
    YouCamGenerationProvider,
)

ROOT = Path(__file__).parent / "fixtures" / "youcam"
BASE_URL = "https://yce-api-01.makeupar.com"
PERSON = PreparedImage(b"person!!", "image/jpeg", 10, 20)
REFERENCE = PreparedImage(b"refbytes", "image/png", 30, 40)
TICKET = ProviderTicket("youcam_clothes_v4", "synthetic-task-id")
AUTH = {"Authorization": "Bearer sentinel-key"}


def body(name: str) -> dict:
    return json.loads((ROOT / name).read_text())


def file_response(
    url: str = "https://yce-us.s3-accelerate.amazonaws.com/synthetic/upload",
    file_id: str = "synthetic-file-id",
    content_type: str = "image/jpg",
) -> dict:
    value = body("file_upload.json")
    item = value["data"]["files"][0]
    item["requests"][0]["url"] = url
    item["requests"][0]["headers"]["Content-Type"] = content_type
    item["content_type"] = content_type
    item["file_id"] = file_id
    return value


def register_uploads(mock: respx.MockRouter, *, upload_status: int = 200):
    file_route = mock.post(f"{BASE_URL}/s2s/v2.0/file").mock(
        side_effect=[
            httpx.Response(
                200,
                json=file_response(
                    "https://yce-us.s3-accelerate.amazonaws.com/synthetic/person",
                    "synthetic-person-file-id",
                ),
            ),
            httpx.Response(
                200,
                json=file_response(
                    "https://yce-us.s3-accelerate.amazonaws.com/synthetic/reference",
                    "synthetic-reference-file-id",
                    "image/png",
                ),
            ),
        ]
    )
    person_route = mock.put("https://yce-us.s3-accelerate.amazonaws.com/synthetic/person").mock(
        return_value=httpx.Response(upload_status)
    )
    reference_route = mock.put(
        "https://yce-us.s3-accelerate.amazonaws.com/synthetic/reference"
    ).mock(return_value=httpx.Response(upload_status))
    return file_route, person_route, reference_route


async def make_provider() -> YouCamGenerationProvider:
    return YouCamGenerationProvider("sentinel-key", client=httpx.AsyncClient())


@pytest.mark.asyncio
async def test_submit_uploads_both_images_then_submits_task() -> None:
    with respx.mock(assert_all_called=True) as mock:
        file_route, person_route, reference_route = register_uploads(mock)
        task = mock.post(f"{BASE_URL}/s2s/v2.0/task/cloth-v4").mock(
            return_value=httpx.Response(200, json=body("task_created.json"))
        )
        provider = await make_provider()
        try:
            result = await provider.submit(PERSON, REFERENCE, "upper_body")
        finally:
            await provider.client.aclose()

    assert result == TICKET
    assert [call.request.read() for call in file_route.calls] == [
        b'{"files":[{"content_type":"image/jpg","file_name":"person.jpg","file_size":8}]}',
        b'{"files":[{"content_type":"image/png","file_name":"reference.png","file_size":8}]}',
    ]
    assert all(
        call.request.headers["Authorization"] == "Bearer sentinel-key" for call in file_route.calls
    )
    task_call = task.calls[0]
    assert json.loads(task_call.request.content) == {
        "src_file_id": "synthetic-person-file-id",
        "ref_file_id": "synthetic-reference-file-id",
        "garment_category": "upper_body",
        "filter_multi_person": "normal",
    }
    assert task_call.request.headers["Authorization"] == "Bearer sentinel-key"
    person_put = person_route.calls[0].request
    reference_put = reference_route.calls[0].request
    assert person_put.headers["Content-Type"] == "image/jpg"
    assert person_put.headers["Content-Length"] == str(len(PERSON.data))
    assert reference_put.headers["Content-Type"] == "image/png"
    assert reference_put.headers["Content-Length"] == "8"
    assert "Authorization" not in person_put.headers
    assert "Authorization" not in reference_put.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "safe_code", "retryable"),
    [
        (400, "provider_rejected", False),
        (401, "service_unavailable", False),
        (403, "service_unavailable", False),
        (429, "service_unavailable", True),
        (500, "service_unavailable", True),
    ],
)
async def test_file_endpoint_failure_is_definite_rejection(status, safe_code, retryable) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE_URL}/s2s/v2.0/file").mock(return_value=httpx.Response(status, json={}))
        provider = await make_provider()
        try:
            with pytest.raises(SubmitRejected) as caught:
                await provider.submit(PERSON, REFERENCE, "upper_body")
        finally:
            await provider.client.aclose()
    assert caught.value.args == (safe_code,) and caught.value.retryable == retryable


@pytest.mark.asyncio
async def test_file_stage_transport_and_malformed_success_are_retryable() -> None:
    for response in (
        httpx.Response(200, json={"data": {"files": []}}),
        httpx.Response(200, content=b"not-json"),
    ):
        with respx.mock(assert_all_called=False) as mock:
            mock.post(f"{BASE_URL}/s2s/v2.0/file").mock(return_value=response)
            provider = await make_provider()
            try:
                with pytest.raises(SubmitRejected) as caught:
                    await provider.submit(PERSON, REFERENCE, "upper_body")
            finally:
                await provider.client.aclose()
        assert caught.value.args == ("service_unavailable",) and caught.value.retryable is True
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE_URL}/s2s/v2.0/file").mock(side_effect=httpx.ConnectError("offline"))
        provider = await make_provider()
        try:
            with pytest.raises(SubmitRejected) as caught:
                await provider.submit(PERSON, REFERENCE, "upper_body")
        finally:
            await provider.client.aclose()
    assert caught.value.args == ("service_unavailable",) and caught.value.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connect"),
        httpx.ReadTimeout("read"),
        httpx.WriteError("write"),
    ],
)
async def test_presigned_put_transport_failure_is_retryable(error) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE_URL}/s2s/v2.0/file").mock(
            return_value=httpx.Response(
                200,
                json=file_response("https://yce-us.s3-accelerate.amazonaws.com/synthetic/person"),
            )
        )
        mock.put("https://yce-us.s3-accelerate.amazonaws.com/synthetic/person").mock(
            side_effect=error
        )
        provider = await make_provider()
        try:
            with pytest.raises(SubmitRejected) as caught:
                await provider.submit(PERSON, REFERENCE, "upper_body")
        finally:
            await provider.client.aclose()
    assert caught.value.args == ("service_unavailable",) and caught.value.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "safe_code", "retryable"),
    [
        (400, "provider_rejected", False),
        (401, "service_unavailable", False),
        (403, "service_unavailable", False),
        (429, "service_unavailable", True),
        (500, "service_unavailable", True),
    ],
)
async def test_presigned_put_failure_is_a_definite_rejection(status, safe_code, retryable) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE_URL}/s2s/v2.0/file").mock(
            return_value=httpx.Response(
                200,
                json=file_response("https://yce-us.s3-accelerate.amazonaws.com/synthetic/person"),
            )
        )
        mock.put("https://yce-us.s3-accelerate.amazonaws.com/synthetic/person").mock(
            return_value=httpx.Response(status)
        )
        provider = await make_provider()
        try:
            with pytest.raises(SubmitRejected) as caught:
                await provider.submit(PERSON, REFERENCE, "upper_body")
        finally:
            await provider.client.aclose()
    assert caught.value.args == (safe_code,) and caught.value.retryable == retryable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upload_url", "method", "safe_code"),
    [
        ("https://evil.example/upload", "PUT", "provider_rejected"),
        (
            "https://yce-us.s3-accelerate.amazonaws.com/upload",
            "POST",
            "provider_rejected",
        ),
    ],
)
async def test_file_stage_rejects_bad_upload_endpoint(upload_url, method, safe_code) -> None:
    response = file_response(upload_url)
    response["data"]["files"][0]["requests"][0]["method"] = method
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE_URL}/s2s/v2.0/file").mock(return_value=httpx.Response(200, json=response))
        provider = await make_provider()
        try:
            with pytest.raises(SubmitRejected) as caught:
                await provider.submit(PERSON, REFERENCE, "upper_body")
        finally:
            await provider.client.aclose()
    assert caught.value.args == (safe_code,) and caught.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("person", "reference", "category"),
    [
        (PERSON, REFERENCE, "not-a-category"),
        (
            PreparedImage(b"x" * (10 * 1024 * 1024), "image/jpeg", 1, 1),
            REFERENCE,
            "upper_body",
        ),
        (PreparedImage(b"tiny", "image/png", 4097, 1), REFERENCE, "upper_body"),
        (PERSON, PreparedImage(b"x" * (10 * 1024 * 1024), "image/png", 1, 1), "outer"),
    ],
)
async def test_prechecks_reject_without_requests(person, reference, category) -> None:
    with respx.mock(assert_all_called=False) as mock:
        provider = await make_provider()
        try:
            with pytest.raises(SubmitRejected):
                await provider.submit(person, reference, category)
        finally:
            await provider.client.aclose()
        assert mock.calls.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "ambiguous"),
    [
        (httpx.ConnectError("connect"), False),
        (httpx.ConnectTimeout("connect timeout"), False),
        (httpx.PoolTimeout("pool timeout"), False),
        (httpx.ReadTimeout("read timeout"), True),
        (httpx.WriteTimeout("write timeout"), True),
        (httpx.RemoteProtocolError("protocol"), True),
        (httpx.ReadError("read"), True),
        (httpx.WriteError("write"), True),
    ],
)
async def test_task_transport_error_classification(exception, ambiguous) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_uploads(mock)
        mock.post(f"{BASE_URL}/s2s/v2.0/task/cloth-v4").mock(side_effect=exception)
        provider = await make_provider()
        try:
            expected = SubmitAmbiguous if ambiguous else SubmitRejected
            with pytest.raises(expected) as caught:
                await provider.submit(PERSON, REFERENCE, "upper_body")
        finally:
            await provider.client.aclose()
    if not ambiguous:
        assert isinstance(caught.value, SubmitRejected)
        assert caught.value.args == ("service_unavailable",) and caught.value.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302),
        httpx.Response(500),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"data": {}}),
        httpx.Response(200, json={"data": {"task_id": ""}}),
    ],
)
async def test_task_uncertain_responses_are_ambiguous(response) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_uploads(mock)
        mock.post(f"{BASE_URL}/s2s/v2.0/task/cloth-v4").mock(return_value=response)
        provider = await make_provider()
        try:
            with pytest.raises(SubmitAmbiguous):
                await provider.submit(PERSON, REFERENCE, "upper_body")
        finally:
            await provider.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "payload", "safe_code", "retryable"),
    [
        (400, {"error_code": "CreditInsufficiency"}, "quota_exceeded", False),
        (400, {"error_code": "InvalidParameters"}, "provider_rejected", False),
        (401, {}, "service_unavailable", False),
        (403, {}, "service_unavailable", False),
        (429, {}, "service_unavailable", True),
        (422, {}, "provider_rejected", False),
    ],
)
async def test_task_definite_rejection_responses(status, payload, safe_code, retryable) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_uploads(mock)
        mock.post(f"{BASE_URL}/s2s/v2.0/task/cloth-v4").mock(
            return_value=httpx.Response(status, json=payload)
        )
        provider = await make_provider()
        try:
            with pytest.raises(SubmitRejected) as caught:
                await provider.submit(PERSON, REFERENCE, "upper_body")
        finally:
            await provider.client.aclose()
    assert caught.value.args == (safe_code,) and caught.value.retryable == retryable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (body("task_running.json"), Pending()),
        (
            body("task_success.json"),
            Succeeded("https://yce-us.s3-accelerate.amazonaws.com/synthetic/result"),
        ),
        ({"data": {"task_status": "success", "results": {}}}, Pending()),
        (body("task_error.json"), Failed("unsupported_reference")),
        (
            {"data": {"task_status": "error", "error": "unknown"}},
            Failed("provider_rejected"),
        ),
        ({"data": {"task_status": "future"}}, Pending()),
        ({"data": {}}, Pending()),
    ],
)
async def test_check_task_states(payload, expected) -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/s2s/v2.0/task/cloth-v4/synthetic-task-id").mock(
            return_value=httpx.Response(200, json=payload)
        )
        provider = await make_provider()
        try:
            result = await provider.check(TICKET)
        finally:
            await provider.client.aclose()
    assert result == expected
    assert route.calls[0].request.headers["Authorization"] == "Bearer sentinel-key"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            httpx.Response(400, json={"error_code": "InvalidTaskId"}),
            Failed("generation_status_unknown"),
        ),
        (
            httpx.Response(500, json={"error": "Task execution timed out"}),
            Failed("generation_timeout"),
        ),
        (httpx.Response(503), Pending()),
        (httpx.Response(200, content=b"bad-json"), Pending()),
        (httpx.Response(401), Pending()),
        (httpx.Response(403), Pending()),
        (httpx.Response(429), Pending()),
    ],
)
async def test_check_error_responses(response, expected) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/s2s/v2.0/task/cloth-v4/synthetic-task-id").mock(return_value=response)
        provider = await make_provider()
        try:
            result = await provider.check(TICKET)
        finally:
            await provider.client.aclose()
    assert result == expected


@pytest.mark.asyncio
async def test_check_transport_timeout_is_pending() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/s2s/v2.0/task/cloth-v4/synthetic-task-id").mock(
            side_effect=httpx.ReadTimeout("timeout")
        )
        provider = await make_provider()
        try:
            result = await provider.check(TICKET)
        finally:
            await provider.client.aclose()
    assert result == Pending()


@pytest.mark.asyncio
async def test_check_quotes_task_id_before_request() -> None:
    task_id = "id/with space?&"
    encoded_id = quote(task_id, safe="")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}/s2s/v2.0/task/cloth-v4/{encoded_id}").mock(
            return_value=httpx.Response(200, json=body("task_running.json"))
        )
        provider = await make_provider()
        try:
            result = await provider.check(ProviderTicket("youcam_clothes_v4", task_id))
        finally:
            await provider.client.aclose()
    assert result == Pending()
    assert str(route.calls[0].request.url).endswith(encoded_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("engine_error", "expected"),
    [(code, safe_code) for code, safe_code in ENGINE_ERROR_CODES.items()]
    + [
        (None, "provider_rejected"),
        ("unrecognized", "provider_rejected"),
        ([], "provider_rejected"),
        ({"future": "error"}, "provider_rejected"),
    ],
)
async def test_engine_error_codes_map_safely(engine_error, expected) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{BASE_URL}/s2s/v2.0/task/cloth-v4/synthetic-task-id").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"task_status": "error", "error": engine_error}},
            )
        )
        provider = await make_provider()
        try:
            result = await provider.check(TICKET)
        finally:
            await provider.client.aclose()
    assert result == Failed(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://yce-us.s3-accelerate.amazonaws.com/result",
        "https://evil.example/result",
        "https://yce-us.s3-accelerate.amazonaws.com.evil.example/result",
        "https://user:pass@yce-us.s3-accelerate.amazonaws.com/result",
        "https://yce-us.s3-accelerate.amazonaws.com:444/result",
    ],
)
async def test_download_rejects_unsafe_urls_without_request(url) -> None:
    with respx.mock(assert_all_called=False) as mock:
        provider = await make_provider()
        try:
            with pytest.raises(DownloadError) as caught:
                await provider.download(url, 100)
        finally:
            await provider.client.aclose()
        assert caught.value.safe_code == "provider_rejected"
        assert caught.value.retryable is False
        assert mock.calls.call_count == 0


@pytest.mark.asyncio
async def test_download_ok_and_rejects_redirect_expired_and_oversize() -> None:
    allowed = next(iter(DEFAULT_OUTPUT_HOSTS))
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"https://{allowed}/ok").mock(return_value=httpx.Response(200, content=b"image"))
        mock.get(f"https://{allowed}/redirect").mock(return_value=httpx.Response(302))
        mock.get(f"https://{allowed}/expired").mock(return_value=httpx.Response(403))
        mock.get(f"https://{allowed}/missing").mock(return_value=httpx.Response(404))
        mock.get(f"https://{allowed}/gone").mock(return_value=httpx.Response(410))
        mock.get(f"https://{allowed}/large").mock(
            return_value=httpx.Response(200, headers={"Content-Length": "101"}, content=b"")
        )
        provider = await make_provider()
        try:
            assert await provider.download(f"https://{allowed}/ok", 6) == b"image"
            for url, code in (
                (f"https://{allowed}/redirect", "provider_rejected"),
                (f"https://{allowed}/expired", "result_expired"),
                (f"https://{allowed}/missing", "result_expired"),
                (f"https://{allowed}/gone", "result_expired"),
                (f"https://{allowed}/large", "provider_rejected"),
            ):
                with pytest.raises(DownloadError) as caught:
                    await provider.download(url, 100)
                assert caught.value.safe_code == code
        finally:
            await provider.client.aclose()


class ChunkedBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"1234"
        yield b"5678"

    async def aclose(self) -> None:
        return None


class ReadMarkerBody(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.read = False

    async def __aiter__(self):
        self.read = True
        yield b"x"

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_download_stops_chunked_body_at_limit_and_maps_timeout() -> None:
    allowed = next(iter(DEFAULT_OUTPUT_HOSTS))
    large_body = ReadMarkerBody()
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"https://{allowed}/chunked").mock(
            return_value=httpx.Response(200, stream=ChunkedBody())
        )
        mock.get(f"https://{allowed}/timeout").mock(side_effect=httpx.ReadTimeout("timeout"))
        mock.get(f"https://{allowed}/large-header").mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Length": "100"},
                stream=large_body,
            )
        )
        provider = await make_provider()
        try:
            with pytest.raises(DownloadError) as caught:
                await provider.download(f"https://{allowed}/chunked", 5)
            assert caught.value.safe_code == "provider_rejected"
            with pytest.raises(DownloadError) as caught:
                await provider.download(f"https://{allowed}/timeout", 50)
            assert caught.value.safe_code == "service_unavailable"
            assert caught.value.retryable is True
            with pytest.raises(DownloadError):
                await provider.download(f"https://{allowed}/large-header", 50)
            assert large_body.read is False
            with pytest.raises(ValueError):
                await provider.download(f"https://{allowed}/timeout", 0)
        finally:
            await provider.client.aclose()


@pytest.mark.asyncio
async def test_logging_never_includes_keys_urls_or_task_ids(caplog) -> None:
    caplog.set_level(logging.INFO, logger="drippop.providers.youcam")
    sentinel_url = "https://yce-us.s3-accelerate.amazonaws.com/private-output"
    ticket = ProviderTicket("youcam_clothes_v4", "sentinel-task-id")
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/s2s/v2.0/task/cloth-v4/sentinel-task-id").mock(
            return_value=httpx.Response(200, json=body("task_running.json"))
        )
        result_route = mock.get(sentinel_url).mock(return_value=httpx.Response(200, content=b"ok"))
        provider = YouCamGenerationProvider("sentinel-key", client=httpx.AsyncClient())
        try:
            await provider.check(ticket)
            await provider.download(sentinel_url, 20)
        finally:
            await provider.client.aclose()
    result_request = result_route.calls[0].request
    assert "Authorization" not in result_request.headers
    assert "sentinel-key" not in caplog.text
    assert sentinel_url not in caplog.text
    assert "sentinel-task-id" not in caplog.text
