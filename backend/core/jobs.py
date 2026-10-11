import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from core.errors import SAFE_MESSAGES, ApiError
from core.state import public_error_code
from providers.base import PreparedImage


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def request_hash(person: PreparedImage, reference: PreparedImage, metadata: dict[str, Any]) -> str:
    canonical = {
        "person": sha256_hex(person.data),
        "reference": sha256_hex(reference.data),
        "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    }
    return sha256_hex(json.dumps(canonical, sort_keys=True, separators=(",", ":")))


def new_job_id() -> str:
    return secrets.token_urlsafe(18)


def _rfc3339(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


def render_job_response(job: dict[str, Any], poll_after_ms: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    result_available = (
        job["status"] == "succeeded" and job["tombstoned_at"] is None and now < job["expires_at"]
    )
    error: dict[str, Any] | None = None
    if job["status"] == "failed":
        code = public_error_code(job) or "service_unavailable"
        error = {
            "code": code,
            "message": SAFE_MESSAGES[code],
            "retryable": code == "service_unavailable",
        }
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "phase": job["phase"],
        "created_at": _rfc3339(job["created_at"]),
        "expires_at": _rfc3339(job["expires_at"]),
        "poll_after_ms": poll_after_ms,
        "result_available": result_available,
        "error": error,
    }


async def get_owned_job(
    conn: AsyncConnection[DictRow], job_id: str, owner_uid: str
) -> dict[str, Any]:
    cur = await conn.execute(
        "select * from jobs where job_id = %(job_id)s and owner_uid = %(uid)s",
        {"job_id": job_id, "uid": owner_uid},
    )
    row = await cur.fetchone()
    if row is None:
        raise ApiError(404, "not_found")
    return dict(row)


async def get_active_job(conn: AsyncConnection[DictRow], owner_uid: str) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select * from jobs where owner_uid = %(uid)s and status in ('queued','processing')",
        {"uid": owner_uid},
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def lookup_idempotency(
    conn: AsyncConnection[DictRow], owner_uid: str, key_hash: str
) -> dict[str, Any] | None:
    cur = await conn.execute(
        """
        select j.*, i.request_hash as idem_request_hash from idempotency_records i
        join jobs j on j.job_id = i.job_id
        where i.owner_uid = %(uid)s and i.key_hash = %(kh)s
        """,
        {"uid": owner_uid, "kh": key_hash},
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def cancel_job(conn: AsyncConnection[DictRow], job_id: str, owner_uid: str) -> dict[str, Any]:
    async with conn.transaction():
        cur = await conn.execute(
            "select * from jobs where job_id = %(job_id)s and owner_uid = %(uid)s for update",
            {"job_id": job_id, "uid": owner_uid},
        )
        row = await cur.fetchone()
        if row is None:
            raise ApiError(404, "not_found")
        job = dict(row)
        if job["tombstoned_at"] is None:
            new_version = job["phase_version"] + 1
            await conn.execute(
                """
                update jobs set status='canceled', internal_state='canceled',
                    canceled_at=now(), tombstoned_at=now(), provider_output_url=null,
                    phase_version=%(v)s, updated_at=now()
                where job_id=%(job_id)s
                """,
                {"v": new_version, "job_id": job_id},
            )
            await conn.execute(
                """
                update job_dispatch set completed_at=now()
                where job_id=%(job_id)s and kind='advance' and completed_at is null
                """,
                {"job_id": job_id},
            )
            await conn.execute(
                """
                insert into job_dispatch (job_id, kind, phase_version, max_attempts)
                select %(job_id)s, 'cleanup', %(v)s, 50
                where not exists (
                    select 1 from job_dispatch
                    where job_id=%(job_id)s and kind='cleanup' and completed_at is null)
                """,
                {"job_id": job_id, "v": new_version},
            )
            cur2 = await conn.execute(
                "select * from jobs where job_id = %(job_id)s", {"job_id": job_id}
            )
            row2 = await cur2.fetchone()
            if row2 is None:
                raise ApiError(404, "not_found")
            job = dict(row2)
    return job
