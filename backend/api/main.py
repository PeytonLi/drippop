import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from psycopg.errors import UniqueViolation
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.deps import AppDeps, OwnerUid, get_deps
from core.auth import TokenVerifier
from core.budget import reserve_detection
from core.contracts import ContractSchemas, validate_detection
from core.db import make_pool
from core.dispatch import object_path
from core.errors import ApiError
from core.images import validate_and_prepare
from core.jobs import (
    cancel_job,
    get_owned_job,
    lookup_idempotency,
    new_job_id,
    render_job_response,
    request_hash,
    sha256_hex,
)
from core.logging import configure_logging, log
from core.settings import Settings
from core.state import public_error_code
from core.storage import LocalObjectStore, SupabaseObjectStore
from providers.base import PreparedImage
from providers.fake import FakeDetectionProvider, FakeGenerationProvider
from providers.live import aclose_providers, build_live_providers

_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_IDEM_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

MAX_MULTIPART_FIELDS = 3
MAX_MULTIPART_FILES = 2
MAX_PART_SIZE = 16_384


def _error_response(exc: ApiError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
    return JSONResponse(status_code=exc.status, content=exc.body(), headers=headers)


async def _read_upload(upload: UploadFile, limit: int) -> bytes:
    data = await upload.read(limit + 1)
    return data


async def _parse_form(request: Request, settings: Settings, fields: set[str]) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared = int(content_length)
        except ValueError:
            raise ApiError(422, "invalid_request") from None
        if declared > 2 * settings.max_image_bytes + 65536:
            raise ApiError(413, "invalid_image")
    try:
        form = await request.form(
            max_files=MAX_MULTIPART_FILES,
            max_fields=MAX_MULTIPART_FIELDS,
            max_part_size=MAX_PART_SIZE,
        )
    except Exception:
        raise ApiError(422, "invalid_request") from None
    keys = set(form.keys())
    if keys != fields:
        raise ApiError(422, "invalid_request")
    return dict(form)


def _detect_fallback(prepared: PreparedImage) -> dict[str, Any]:
    return {
        "image_width": prepared.width,
        "image_height": prepared.height,
        "coordinate_space": "normalized_upright_xyxy",
        "persons": [],
        "manual_selection_required": True,
    }


def create_app(deps: AppDeps | None = None) -> FastAPI:
    configure_logging()
    if deps is None:
        settings = Settings()
        contracts = ContractSchemas(settings.contracts_dir)
        pool = make_pool(settings.database_url)
        store: Any
        if settings.storage_backend == "supabase":
            store = SupabaseObjectStore(
                settings.supabase_url, settings.supabase_secret_key, settings.storage_bucket
            )
        else:
            store = LocalObjectStore(settings.local_storage_dir)
        if settings.provider_mode == "fake":
            detector: Any = FakeDetectionProvider()
            generator: Any = FakeGenerationProvider()
        else:
            detector, generator = build_live_providers(settings)
        deps = AppDeps(
            settings=settings,
            pool=pool,
            store=store,
            detector=detector,
            generator=generator,
            contracts=contracts,
            verifier=TokenVerifier(settings),
        )
        deps.pool_needs_open = True

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if getattr(deps, "pool_needs_open", False):
            await deps.pool.open()
        yield
        if getattr(deps, "pool_needs_open", False):
            await deps.pool.close()
            await aclose_providers(deps.detector, deps.generator)

    app = FastAPI(
        title="DripPop API",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.deps = deps

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(ApiError(422, "invalid_request"))

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error_response(ApiError(404, "not_found"))
        if exc.status_code == 405:
            return _error_response(ApiError(405, "invalid_request"))
        return _error_response(ApiError(exc.status_code, "invalid_request"))

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/garments:detect")
    async def detect(request: Request, owner_uid: OwnerUid) -> JSONResponse:
        d = get_deps(request)
        form = await _parse_form(request, d.settings, {"frame"})
        frame_upload = form["frame"]
        if not isinstance(frame_upload, UploadFile):
            raise ApiError(422, "invalid_request")
        data = await _read_upload(frame_upload, d.settings.max_image_bytes)
        prepared = validate_and_prepare(data, role="frame", settings=d.settings)
        async with d.pool.connection() as conn, conn.transaction():
            await reserve_detection(conn, owner_uid, d.settings)
        if d.detector is None:
            raise ApiError(503, "analysis_unavailable")
        result: dict[str, Any]
        try:
            async with asyncio.timeout(d.settings.detect_timeout_s):
                raw = await d.detector.detect(prepared)
            result = dict(raw)
            if (
                result.get("image_width") != prepared.width
                or result.get("image_height") != prepared.height
            ):
                result = _detect_fallback(prepared)
            elif not validate_detection(d.contracts, result):
                result = _detect_fallback(prepared)
        except Exception:
            result = _detect_fallback(prepared)
        return JSONResponse(result)

    @app.post("/v1/jobs", status_code=202)
    async def create_job(request: Request, owner_uid: OwnerUid) -> JSONResponse:
        d = get_deps(request)
        settings = d.settings
        key = request.headers.get("idempotency-key", "")
        if not key:
            raise ApiError(400, "invalid_request")
        if not _IDEM_KEY_RE.match(key):
            raise ApiError(400, "invalid_request")

        form = await _parse_form(request, settings, {"person_photo", "reference_photo", "metadata"})
        person_upload = form["person_photo"]
        reference_upload = form["reference_photo"]
        metadata_field = form["metadata"]
        if not isinstance(person_upload, UploadFile) or not isinstance(
            reference_upload, UploadFile
        ):
            raise ApiError(422, "invalid_request")
        try:
            metadata = json.loads(str(metadata_field))
        except (json.JSONDecodeError, TypeError):
            raise ApiError(422, "invalid_request") from None
        if not d.contracts.is_valid("generation_metadata.schema.json", metadata):
            raise ApiError(422, "invalid_request")

        person = validate_and_prepare(
            await _read_upload(person_upload, settings.max_image_bytes),
            role="person",
            settings=settings,
        )
        reference = validate_and_prepare(
            await _read_upload(reference_upload, settings.max_image_bytes),
            role="reference",
            settings=settings,
        )
        rhash = request_hash(person, reference, metadata)
        key_hash = sha256_hex(key)
        category = metadata["garment_category"]

        async with d.pool.connection() as conn:
            existing = await lookup_idempotency(conn, owner_uid, key_hash)
        if existing is not None:
            if existing["idem_request_hash"] == rhash:
                return JSONResponse(
                    status_code=202,
                    content=render_job_response(existing, settings.poll_after_ms),
                )
            raise ApiError(409, "idempotency_conflict")

        enabled = set(d.contracts.categories.get("enabled", []))
        if settings.provider_mode == "fake":
            enabled |= set(d.contracts.categories.get("fake_mode_enabled", []))
        if category not in enabled:
            raise ApiError(422, "category_unavailable")
        if d.generator is None:
            raise ApiError(503, "service_unavailable")

        cap = settings.daily_paid_attempt_cap
        if settings.provider_mode != "fake" and cap == 0:
            raise ApiError(503, "service_unavailable")
        if cap > 0:
            async with d.pool.connection() as conn:
                cur = await conn.execute(
                    "select paid_attempts from budget_days"
                    " where day = (now() at time zone 'utc')::date"
                )
                row = await cur.fetchone()
                if row and row["paid_attempts"] >= cap:
                    raise ApiError(429, "quota_exceeded", retryable=True)

        async with d.pool.connection() as conn:
            active = await conn.execute(
                "select job_id from jobs where owner_uid=%(u)s"
                " and status in ('queued','processing')",
                {"u": owner_uid},
            )
            active_row = await active.fetchone()
        if active_row:
            async with d.pool.connection() as conn:
                again = await lookup_idempotency(conn, owner_uid, key_hash)
            if again is not None and again["idem_request_hash"] == rhash:
                return JSONResponse(
                    status_code=202,
                    content=render_job_response(again, settings.poll_after_ms),
                )
            raise ApiError(409, "active_job_exists", job_id=active_row["job_id"])

        job_id = new_job_id()
        person_path = object_path(job_id, "person", person.mime)
        reference_path = object_path(job_id, "reference", reference.mime)
        written = False
        try:
            await d.store.put(person_path, person.data, person.mime)
            await d.store.put(reference_path, reference.data, reference.mime)
            written = True
            async with d.pool.connection() as conn, conn.transaction():
                await conn.execute(
                    """
                    insert into jobs (job_id, owner_uid, status, phase, internal_state,
                        garment_category, request_hash, deadline_at, expires_at, records_expire_at)
                    values (%(j)s, %(u)s, 'queued', 'queued', 'queued', %(cat)s, %(rh)s,
                        now() + make_interval(secs => %(dl)s),
                        now() + make_interval(secs => %(ttl)s),
                        now() + make_interval(secs => %(rttl)s))
                    """,
                    {
                        "j": job_id,
                        "u": owner_uid,
                        "cat": category,
                        "rh": rhash,
                        "dl": settings.job_deadline_s,
                        "ttl": settings.image_ttl_s,
                        "rttl": settings.record_ttl_s,
                    },
                )
                for path, kind, img in (
                    (person_path, "person", person),
                    (reference_path, "reference", reference),
                ):
                    await conn.execute(
                        """
                        insert into stored_objects (path, job_id, kind, mime, byte_size, sha256)
                        values (%(p)s, %(j)s, %(k)s, %(m)s, %(b)s, %(s)s)
                        """,
                        {
                            "p": path,
                            "j": job_id,
                            "k": kind,
                            "m": img.mime,
                            "b": len(img.data),
                            "s": hashlib.sha256(img.data).hexdigest(),
                        },
                    )
                await conn.execute(
                    """
                    insert into idempotency_records
                        (owner_uid, key_hash, request_hash, job_id, expires_at)
                    values (%(u)s, %(kh)s, %(rh)s, %(j)s,
                        now() + make_interval(secs => %(rttl)s))
                    """,
                    {
                        "u": owner_uid,
                        "kh": key_hash,
                        "rh": rhash,
                        "j": job_id,
                        "rttl": settings.record_ttl_s,
                    },
                )
                await conn.execute(
                    """
                    insert into job_dispatch (job_id, kind, phase_version, max_attempts)
                    values (%(j)s, 'advance', 0, %(m)s)
                    """,
                    {"j": job_id, "m": settings.dispatch_max_attempts},
                )
        except UniqueViolation as exc:
            if written:
                for p in (person_path, reference_path):
                    try:
                        await d.store.delete(p)
                    except Exception:
                        log("cleanup_object_failed", job_id=job_id)
            constraint = getattr(getattr(exc, "diag", None), "constraint_name", "") or ""
            async with d.pool.connection() as conn:
                existing = await lookup_idempotency(conn, owner_uid, key_hash)
            if existing is not None:
                if existing["idem_request_hash"] == rhash:
                    return JSONResponse(
                        status_code=202,
                        content=render_job_response(existing, settings.poll_after_ms),
                    )
                raise ApiError(409, "idempotency_conflict") from None
            if constraint == "idempotency_records_pkey":
                raise ApiError(409, "idempotency_conflict") from None
            if constraint == "jobs_one_active_per_owner":
                async with d.pool.connection() as conn:
                    cur = await conn.execute(
                        "select job_id from jobs where owner_uid=%(u)s"
                        " and status in ('queued','processing')",
                        {"u": owner_uid},
                    )
                    row = await cur.fetchone()
                raise ApiError(
                    409, "active_job_exists", job_id=row["job_id"] if row else None
                ) from None
            raise ApiError(503, "service_unavailable", retryable=True) from None
        except Exception:
            if written:
                for p in (person_path, reference_path):
                    try:
                        await d.store.delete(p)
                    except Exception:
                        log("cleanup_object_failed", job_id=job_id)
            log("job_create_failed", job_id=job_id)
            raise ApiError(503, "service_unavailable", retryable=True) from None

        async with d.pool.connection() as conn:
            job = await get_owned_job(conn, job_id, owner_uid)
        return JSONResponse(
            status_code=202, content=render_job_response(job, settings.poll_after_ms)
        )

    def _check_job_id(job_id: str) -> None:
        if not _JOB_ID_RE.match(job_id):
            raise ApiError(404, "not_found")

    @app.get("/v1/jobs/{job_id}")
    async def get_job(request: Request, job_id: str, owner_uid: OwnerUid) -> JSONResponse:
        _check_job_id(job_id)
        d = get_deps(request)
        async with d.pool.connection() as conn:
            job = await get_owned_job(conn, job_id, owner_uid)
        return JSONResponse(render_job_response(job, d.settings.poll_after_ms))

    @app.delete("/v1/jobs/{job_id}", status_code=202)
    async def delete_job(request: Request, job_id: str, owner_uid: OwnerUid) -> JSONResponse:
        _check_job_id(job_id)
        d = get_deps(request)
        async with d.pool.connection() as conn:
            job = await cancel_job(conn, job_id, owner_uid)
        return JSONResponse(
            status_code=202, content=render_job_response(job, d.settings.poll_after_ms)
        )

    @app.get("/v1/jobs/{job_id}/result")
    async def get_result(request: Request, job_id: str, owner_uid: OwnerUid) -> Response:
        _check_job_id(job_id)
        d = get_deps(request)
        async with d.pool.connection() as conn:
            job = await get_owned_job(conn, job_id, owner_uid)
        if job["tombstoned_at"] is not None or job["status"] == "canceled":
            raise ApiError(409, "job_canceled")
        if datetime.now(UTC) >= job["expires_at"]:
            raise ApiError(410, "result_expired")
        if job["status"] == "failed":
            raise ApiError(409, public_error_code(job) or "service_unavailable")
        if job["status"] in ("queued", "processing"):
            raise ApiError(409, "result_not_ready", retryable=True)
        if not job["result_object_path"]:
            raise ApiError(503, "service_unavailable", retryable=True)
        try:
            data = await d.store.get(job["result_object_path"])
        except Exception:
            raise ApiError(503, "service_unavailable", retryable=True) from None
        return Response(
            content=data,
            media_type=job["result_mime"] or "image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    return app
