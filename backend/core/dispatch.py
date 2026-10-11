import asyncio
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from PIL import Image
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from core.contracts import ContractSchemas
from core.errors import SAFE_MESSAGES, ApiError
from core.images import validate_and_prepare
from core.logging import log
from core.settings import Settings
from core.state import TERMINAL
from core.storage import ObjectStore
from providers.base import (
    DetectionProvider,
    Failed,
    GenerationProvider,
    Pending,
    PreparedImage,
    ProviderTicket,
    SubmitAmbiguous,
    SubmitRejected,
    Succeeded,
)

VALID_ERROR_CODES = set(SAFE_MESSAGES)


@dataclass
class WorkerDeps:
    settings: Settings
    pool: AsyncConnectionPool[AsyncConnection[DictRow]]
    store: ObjectStore
    generator: GenerationProvider | None
    detector: DetectionProvider | None
    contracts: ContractSchemas


_CLAIM_SQL = """
with c as (
  select id from job_dispatch
  where completed_at is null and run_after <= now()
    and (lease_expires_at is null or lease_expires_at < now())
    and attempts < max_attempts
  order by run_after, id
  for update skip locked
  limit 1)
update job_dispatch d set lease_token = gen_random_uuid(),
    lease_expires_at = now() + make_interval(secs => %(lease_s)s),
    attempts = d.attempts + 1
from c where d.id = c.id returning d.*;
"""


async def claim(conn: AsyncConnection[DictRow], lease_s: int) -> dict[str, Any] | None:
    cur = await conn.execute(_CLAIM_SQL, {"lease_s": lease_s})
    row = await cur.fetchone()
    return dict(row) if row else None


async def _load_job(conn: AsyncConnection[DictRow], job_id: str) -> dict[str, Any] | None:
    cur = await conn.execute("select * from jobs where job_id=%s", (job_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def _fence(conn: AsyncConnection[DictRow], dispatch: dict[str, Any]) -> dict[str, Any] | None:
    """Lock the dispatch row by lease token and return the locked job, else None."""
    cur = await conn.execute(
        """
        select id from job_dispatch
        where id=%(id)s and lease_token=%(tok)s and completed_at is null
        for update
        """,
        {"id": dispatch["id"], "tok": dispatch["lease_token"]},
    )
    if await cur.fetchone() is None:
        return None
    cur = await conn.execute("select * from jobs where job_id=%s for update", (dispatch["job_id"],))
    row = await cur.fetchone()
    return dict(row) if row else None


async def _complete_and_next(
    conn: AsyncConnection[DictRow],
    dispatch: dict[str, Any],
    new_version: int,
    next_kind: str | None,
    run_after_sql: str = "now()",
    max_attempts: int = 5,
) -> None:
    await conn.execute(
        "update job_dispatch set completed_at=now(), lease_token=null where id=%s",
        (dispatch["id"],),
    )
    if next_kind:
        sql = (
            "insert into job_dispatch (job_id, kind, phase_version, run_after, max_attempts) "  # noqa: S608
            f"values (%(job_id)s, %(kind)s, %(v)s, {run_after_sql}, %(max)s)"
        )
        await conn.execute(
            sql,
            {
                "job_id": dispatch["job_id"],
                "kind": next_kind,
                "v": new_version,
                "max": max_attempts,
            },
        )


def _safe_code(code: str | None) -> str:
    return code if code in VALID_ERROR_CODES else "provider_rejected"


async def _fail_job(
    conn: AsyncConnection[DictRow],
    dispatch: dict[str, Any],
    job: dict[str, Any],
    code: str,
    internal: str = "failed",
    reservation: str | None = None,
) -> None:
    new_version = job["phase_version"] + 1
    await conn.execute(
        """
        update jobs set status='failed', internal_state=%(internal)s, error_code=%(code)s,
            phase_version=%(v)s, provider_output_url=null, finished_at=now(), updated_at=now()
        where job_id=%(job_id)s
        """,
        {"internal": internal, "code": code, "v": new_version, "job_id": job["job_id"]},
    )
    if reservation:
        await conn.execute(
            "update budget_reservations set status=%(s)s, updated_at=now() where job_id=%(j)s",
            {"s": reservation, "j": job["job_id"]},
        )
        if reservation == "released":
            await conn.execute(
                """
                update budget_days set paid_attempts = greatest(paid_attempts - 1, 0)
                where day = (now() at time zone 'utc')::date
                """,
                {},
            )
    await _complete_and_next(conn, dispatch, new_version, None)


async def _handle_queued(
    deps: WorkerDeps,
    conn: AsyncConnection[DictRow],
    dispatch: dict[str, Any],
    job: dict[str, Any],
) -> str:
    now_cur = await conn.execute("select now() as now")
    now_row = await now_cur.fetchone()
    if now_row is None:
        raise RuntimeError("unreachable")
    now = now_row["now"]
    if job["tombstoned_at"] is not None or job["status"] == "canceled":
        await _complete_and_next(conn, dispatch, job["phase_version"], None)
        return "no_op"
    if now > job["deadline_at"]:
        await _fail_job(conn, dispatch, job, "generation_timeout")
        return "timeout"

    enabled = set(deps.contracts.categories.get("enabled", []))
    if deps.settings.provider_mode == "fake":
        enabled |= set(deps.contracts.categories.get("fake_mode_enabled", []))
    if job["garment_category"] not in enabled:
        await _fail_job(conn, dispatch, job, "category_unavailable")
        return "category_unavailable"

    cap = deps.settings.daily_paid_attempt_cap
    if deps.settings.provider_mode == "fake" and cap == 0:
        pass  # fake mode with no cap needs no reservation
    else:
        if cap <= 0:
            await _fail_job(conn, dispatch, job, "service_unavailable")
            return "service_unavailable"
        cur = await conn.execute(
            """
            insert into budget_days (day, paid_attempts)
            values ((now() at time zone 'utc')::date, 1)
            on conflict (day) do update
              set paid_attempts = budget_days.paid_attempts + 1
              where budget_days.paid_attempts < %(cap)s
            returning paid_attempts
            """,
            {"cap": cap},
        )
        if await cur.fetchone() is None:
            await _fail_job(conn, dispatch, job, "quota_exceeded")
            return "quota_exceeded"
        await conn.execute(
            """
            insert into budget_reservations (job_id, day, status)
            values (%(j)s, (now() at time zone 'utc')::date, 'reserved')
            on conflict (job_id) do nothing
            """,
            {"j": job["job_id"]},
        )

    new_version = job["phase_version"] + 1
    await conn.execute(
        """
        update jobs set status='processing', phase='preparing', internal_state='ready_to_submit',
            phase_version=%(v)s, updated_at=now() where job_id=%(j)s
        """,
        {"v": new_version, "j": job["job_id"]},
    )
    await _complete_and_next(
        conn, dispatch, new_version, "advance", max_attempts=deps.settings.dispatch_max_attempts
    )
    return "ready"


def object_path(job_id: str, kind: str, mime: str) -> str:
    ext = "jpg" if mime == "image/jpeg" else "png"
    return f"jobs/{job_id}/{kind}.{ext}"


async def handle_dispatch(deps: WorkerDeps, dispatch: dict[str, Any]) -> str:
    """Execute one claimed dispatch. Returns a short outcome string for logging."""
    settings = deps.settings
    try:
        async with asyncio.timeout(settings.handler_timeout_s):
            if dispatch["kind"] == "cleanup":
                return await _handle_cleanup(deps, dispatch)

            async with deps.pool.connection() as conn:
                job = await _load_job(conn, dispatch["job_id"])
            if job is None:
                async with deps.pool.connection() as conn, conn.transaction():
                    await _complete_and_next(conn, dispatch, dispatch["phase_version"], None)
                return "no_job"

            state = job["internal_state"]
            # Stale or terminal job: complete dispatch as no-op.
            if job["phase_version"] != dispatch["phase_version"] or state in TERMINAL:
                async with deps.pool.connection() as conn, conn.transaction():
                    fenced = await _fence(conn, dispatch)
                    if fenced is not None:
                        await _complete_and_next(conn, dispatch, dispatch["phase_version"], None)
                return "stale"

            if state == "queued":
                async with deps.pool.connection() as conn, conn.transaction():
                    fenced = await _fence(conn, dispatch)
                    if fenced is None:
                        log("lease_lost", job_id=dispatch["job_id"], dispatch_id=dispatch["id"])
                        return "lease_lost"
                    return await _handle_queued(deps, conn, dispatch, fenced)
            if state == "ready_to_submit":
                return await _handle_submit(deps, dispatch, job)
            if state == "submitting":
                async with deps.pool.connection() as conn, conn.transaction():
                    fenced = await _fence(conn, dispatch)
                    if fenced is None:
                        return "lease_lost"
                    await _fail_job(
                        conn,
                        dispatch,
                        fenced,
                        "generation_status_unknown",
                        internal="submission_unknown",
                    )
                return "submission_unknown"
            if state == "polling":
                return await _handle_check(deps, dispatch, job)
            if state == "finalizing":
                return await _handle_finalize(deps, dispatch, job)
            return "unknown_state"
    except TimeoutError:
        await _reschedule(deps, dispatch, "handler_timeout")
        return "handler_timeout"
    except Exception as exc:
        log("handler_error", level=40, error=exc.__class__.__name__, dispatch_id=dispatch["id"])
        await _reschedule(deps, dispatch, "internal_error")
        return "internal_error"


async def _handle_submit(deps: WorkerDeps, dispatch: dict[str, Any], job: dict[str, Any]) -> str:
    settings = deps.settings
    # Read inputs BEFORE the marker commit; on failure reschedule without marking.
    async with deps.pool.connection() as conn:
        cur = await conn.execute(
            "select path, kind, mime from stored_objects where job_id=%s and deleted_at is null",
            (job["job_id"],),
        )
        objects = await cur.fetchall()
    paths = {o["kind"]: o["path"] for o in objects}
    mimes = {o["kind"]: o["mime"] for o in objects}
    try:
        person_data = await deps.store.get(paths["person"])
        reference_data = await deps.store.get(paths["reference"])
    except Exception:
        await _reschedule(deps, dispatch, "storage_error")
        return "storage_error"

    def dims(data: bytes) -> tuple[int, int]:
        with Image.open(io.BytesIO(data)) as im:
            return im.size

    pw, ph = dims(person_data)
    rw, rh = dims(reference_data)
    person = PreparedImage(person_data, mimes["person"], pw, ph)
    reference = PreparedImage(reference_data, mimes["reference"], rw, rh)

    # tx1: fence + submission marker + recovery dispatch
    new_version = job["phase_version"] + 1
    async with deps.pool.connection() as conn, conn.transaction():
        fenced = await _fence(conn, dispatch)
        if fenced is None:
            return "lease_lost"
        if fenced["internal_state"] != "ready_to_submit":
            await _complete_and_next(conn, dispatch, dispatch["phase_version"], None)
            return "stale"
        await conn.execute(
            """
            update jobs set internal_state='submitting', phase='generating',
                submission_marker_at=now(), phase_version=%(v)s, updated_at=now()
            where job_id=%(j)s
            """,
            {"v": new_version, "j": job["job_id"]},
        )
        await _complete_and_next(
            conn,
            dispatch,
            new_version,
            "advance",
            run_after_sql=f"now() + make_interval(secs => {settings.lease_s})",
            max_attempts=settings.dispatch_max_attempts,
        )

    submit_error: BaseException | None = None
    ticket = None
    try:
        if deps.generator is None:
            raise SubmitRejected("service_unavailable")
        ticket = await deps.generator.submit(person, reference, job["garment_category"])
    except SubmitRejected as exc:
        submit_error = exc
    except SubmitAmbiguous as exc:
        submit_error = exc
    except TimeoutError as exc:
        submit_error = exc
    except Exception as exc:
        submit_error = SubmitAmbiguous(str(exc))

    # tx2: fence the recovery dispatch for the new version
    async with deps.pool.connection() as conn, conn.transaction():
        cur = await conn.execute(
            """
            select * from job_dispatch where job_id=%(j)s and kind='advance'
              and phase_version=%(v)s and completed_at is null for update
            """,
            {"j": job["job_id"], "v": new_version},
        )
        recovery = await cur.fetchone()
        cur2 = await conn.execute("select * from jobs where job_id=%s for update", (job["job_id"],))
        current_row = await cur2.fetchone()
        current = dict(current_row) if current_row is not None else None
        if (
            recovery is None
            or current is None
            or current["internal_state"] != "submitting"
            or current["phase_version"] != new_version
        ):
            log("lease_lost", job_id=job["job_id"], dispatch_id=dispatch["id"])
            return "lease_lost"
        recovery = dict(recovery)
        v2 = new_version + 1
        if ticket is not None:
            await conn.execute(
                """
                update jobs set provider=%(p)s, provider_task_id=%(t)s,
                    internal_state='polling', phase_version=%(v)s, updated_at=now()
                where job_id=%(j)s
                """,
                {"p": ticket.provider, "t": ticket.task_id, "v": v2, "j": job["job_id"]},
            )
            await _complete_and_next(
                conn,
                recovery,
                v2,
                "advance",
                run_after_sql=f"now() + make_interval(secs => {settings.check_interval_s})",
                max_attempts=settings.dispatch_max_attempts,
            )
            return "submitted"
        if isinstance(submit_error, SubmitRejected):
            await conn.execute(
                """
                update jobs set status='failed', internal_state='failed',
                    error_code=%(code)s, phase_version=%(v)s, finished_at=now(), updated_at=now()
                where job_id=%(j)s
                """,
                {"code": _safe_code(submit_error.safe_code), "v": v2, "j": job["job_id"]},
            )
            await conn.execute(
                "update budget_reservations set status='released',"
                " updated_at=now() where job_id=%s",
                (job["job_id"],),
            )
            await conn.execute(
                """
                update budget_days set paid_attempts = greatest(paid_attempts - 1, 0)
                where day = (now() at time zone 'utc')::date
                """
            )
            await _complete_and_next(conn, recovery, v2, None)
            return "rejected"
        await conn.execute(
            """
            update jobs set status='failed', internal_state='submission_unknown',
                error_code='generation_status_unknown', phase_version=%(v)s,
                finished_at=now(), updated_at=now()
            where job_id=%(j)s
            """,
            {"v": v2, "j": job["job_id"]},
        )
        await _complete_and_next(conn, recovery, v2, None)
        return "submission_unknown"


async def _handle_check(deps: WorkerDeps, dispatch: dict[str, Any], job: dict[str, Any]) -> str:
    settings = deps.settings

    result = None
    check_exc: Exception | None = None
    try:
        if deps.generator is None or job["provider_task_id"] is None:
            raise RuntimeError("no provider")
        result = await deps.generator.check(
            ProviderTicket(job["provider"] or "fake", job["provider_task_id"])
        )
    except Exception as exc:
        check_exc = exc

    if check_exc is not None:
        await _reschedule(deps, dispatch, "check_error")
        return "check_error"

    async with deps.pool.connection() as conn, conn.transaction():
        fenced = await _fence(conn, dispatch)
        if fenced is None:
            return "lease_lost"
        if (
            fenced["phase_version"] != dispatch["phase_version"]
            or fenced["internal_state"] != "polling"
        ):
            await _complete_and_next(conn, dispatch, dispatch["phase_version"], None)
            return "stale"
        new_version = fenced["phase_version"] + 1
        await conn.execute(
            "update jobs set phase_version=%(v)s where job_id=%(j)s",
            {"v": new_version, "j": job["job_id"]},
        )
        now_cur = await conn.execute("select now() as now")
        now_row = await now_cur.fetchone()
        if now_row is None:
            raise RuntimeError("unreachable")
        now = now_row["now"]

        if isinstance(result, Pending):
            check_count = fenced["check_count"] + 1
            if check_count >= settings.max_checks or now > fenced["deadline_at"]:
                await conn.execute(
                    "update budget_reservations set status='consumed',"
                    " updated_at=now() where job_id=%s",
                    (job["job_id"],),
                )
                await _fail_job(conn, dispatch, fenced, "generation_timeout")
                return "timeout"
            await conn.execute(
                "update jobs set check_count=%(c)s, updated_at=now() where job_id=%(j)s",
                {"c": check_count, "j": job["job_id"]},
            )
            await _complete_and_next(
                conn,
                dispatch,
                new_version,
                "advance",
                run_after_sql=f"now() + make_interval(secs => {settings.check_interval_s})",
                max_attempts=settings.dispatch_max_attempts,
            )
            return "pending"
        if isinstance(result, Failed):
            await conn.execute(
                "update budget_reservations set status='consumed',"
                " updated_at=now() where job_id=%s",
                (job["job_id"],),
            )
            await _fail_job(conn, dispatch, fenced, _safe_code(result.safe_code))
            return "failed"
        if isinstance(result, Succeeded):
            await conn.execute(
                """
                update jobs set internal_state='finalizing', phase='finalizing',
                    provider_output_url=%(u)s, phase_version=%(v)s, updated_at=now()
                where job_id=%(j)s
                """,
                {"u": result.output_url, "v": new_version, "j": job["job_id"]},
            )
            await conn.execute(
                "update budget_reservations set status='consumed',"
                " updated_at=now() where job_id=%s",
                (job["job_id"],),
            )
            await _complete_and_next(
                conn,
                dispatch,
                new_version,
                "advance",
                max_attempts=settings.dispatch_max_attempts,
            )
            return "succeeded"
        raise RuntimeError("unknown check result")


async def _handle_finalize(deps: WorkerDeps, dispatch: dict[str, Any], job: dict[str, Any]) -> str:
    settings = deps.settings
    data = None
    prepared = None
    try:
        if deps.generator is None or not job["provider_output_url"]:
            raise RuntimeError("no provider output")
        data = await deps.generator.download(job["provider_output_url"], settings.max_result_bytes)
        prepared = validate_and_prepare(data, role="frame", settings=settings)
    except (ApiError, ValueError):
        # Content-invalid output: bad image, oversize, disallowed scheme.
        async with deps.pool.connection() as conn, conn.transaction():
            fenced = await _fence(conn, dispatch)
            if fenced is None:
                return "lease_lost"
            await _fail_job(conn, dispatch, fenced, "provider_rejected")
        return "finalize_failed"
    except Exception:
        # Transient download/store failure: retry bounded by attempts/max_attempts.
        await _reschedule(deps, dispatch, "download_error")
        return "download_error"

    result_path = f"jobs/{job['job_id']}/result.{'jpg' if prepared.mime == 'image/jpeg' else 'png'}"
    await deps.store.put(result_path, prepared.data, prepared.mime)

    delete_written = False
    async with deps.pool.connection() as conn, conn.transaction():
        fenced = await _fence(conn, dispatch)
        if fenced is None:
            delete_written = True
        else:
            now_cur = await conn.execute("select now() as now")
            now_row = await now_cur.fetchone()
            if now_row is None:
                raise RuntimeError("unreachable")
            now = now_row["now"]
            eligible = (
                fenced["status"] != "canceled"
                and fenced["tombstoned_at"] is None
                and now < fenced["expires_at"]
                and fenced["internal_state"] == "finalizing"
                and fenced["phase_version"] == dispatch["phase_version"]
            )
            if eligible:
                new_version = fenced["phase_version"] + 1
                await conn.execute(
                    """
                    update jobs set status='succeeded', internal_state='succeeded',
                        result_object_path=%(p)s, result_mime=%(m)s,
                        provider_output_url=null, finished_at=now(),
                        phase_version=%(v)s, updated_at=now()
                    where job_id=%(j)s
                    """,
                    {"p": result_path, "m": prepared.mime, "v": new_version, "j": job["job_id"]},
                )
                await conn.execute(
                    """
                    insert into stored_objects (path, job_id, kind, mime, byte_size, sha256)
                    values (%(p)s, %(j)s, 'result', %(m)s, %(b)s, %(s)s)
                    on conflict (path) do nothing
                    """,
                    {
                        "p": result_path,
                        "j": job["job_id"],
                        "m": prepared.mime,
                        "b": len(prepared.data),
                        "s": hashlib.sha256(prepared.data).hexdigest(),
                    },
                )
                await _complete_and_next(conn, dispatch, new_version, None)
                return "published"
            delete_written = True
            await _complete_and_next(conn, dispatch, dispatch["phase_version"], None)
    if delete_written:
        await deps.store.delete(result_path)
        return "discarded"
    return "published"


async def _handle_cleanup(deps: WorkerDeps, dispatch: dict[str, Any]) -> str:
    try:
        async with deps.pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "select path from stored_objects where job_id=%s and deleted_at is null",
                (dispatch["job_id"],),
            )
            rows = await cur.fetchall()
        for row in rows:
            try:
                await deps.store.delete(row["path"])
            except Exception:
                log("cleanup_delete_error", job_id=dispatch["job_id"])
        async with deps.pool.connection() as conn, conn.transaction():
            fenced = await _fence(conn, dispatch)
            if fenced is None:
                return "lease_lost"
            await conn.execute(
                "update stored_objects set deleted_at=now() where job_id=%s",
                (dispatch["job_id"],),
            )
            await conn.execute(
                "update jobs set result_object_path=null where job_id=%s",
                (dispatch["job_id"],),
            )
            await _complete_and_next(conn, dispatch, dispatch["phase_version"], None)
        return "cleaned"
    except Exception:
        await _reschedule(deps, dispatch, "cleanup_error")
        return "cleanup_error"


async def _reschedule(deps: WorkerDeps, dispatch: dict[str, Any], code: str) -> None:
    async with deps.pool.connection() as conn, conn.transaction():
        await conn.execute(
            """
            update job_dispatch set lease_token=null, lease_expires_at=null,
                run_after = now() + make_interval(secs => least(power(2, attempts), 60)),
                last_error=%(c)s
            where id=%(id)s and lease_token=%(tok)s and completed_at is null
            """,
            {"c": code, "id": dispatch["id"], "tok": dispatch["lease_token"]},
        )


async def drain(deps: WorkerDeps, max_steps: int | None = None) -> int:
    """Process dispatches until none are claimable. Returns number handled."""
    handled = 0
    while max_steps is None or handled < max_steps:
        async with deps.pool.connection() as conn, conn.transaction():
            dispatch = await claim(conn, deps.settings.lease_s)
        if dispatch is None:
            break
        outcome = await handle_dispatch(deps, dispatch)
        log(
            "dispatch_handled",
            dispatch_id=dispatch["id"],
            job_id=dispatch["job_id"],
            outcome=outcome,
        )
        handled += 1
    return handled


async def reconcile(deps: WorkerDeps, limit: int = 100) -> dict[str, int]:
    settings = deps.settings
    counts: dict[str, int] = {}
    async with deps.pool.connection() as conn, conn.transaction():
        # 1. non-terminal jobs past deadline
        cur = await conn.execute(
            """
            select * from jobs
            where status in ('queued','processing') and deadline_at < now()
            limit %s for update skip locked
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        for job in rows:
            internal = "submission_unknown" if job["internal_state"] == "submitting" else "failed"
            code = (
                "generation_status_unknown"
                if internal == "submission_unknown"
                else "generation_timeout"
            )
            new_v = job["phase_version"] + 1
            await conn.execute(
                """
                update jobs set status='failed', internal_state=%(i)s, error_code=%(c)s,
                    provider_output_url=null, finished_at=now(), phase_version=%(v)s,
                    updated_at=now() where job_id=%(j)s
                """,
                {"i": internal, "c": code, "v": new_v, "j": job["job_id"]},
            )
            await conn.execute(
                """
                update job_dispatch set completed_at=now()
                where job_id=%s and kind='advance' and completed_at is null
                """,
                (job["job_id"],),
            )
        counts["deadline_failed"] = len(rows)

        # 2. exhausted dispatches
        cur = await conn.execute(
            """
            select d.*, j.internal_state, j.phase_version as job_version from job_dispatch d
            join jobs j on j.job_id = d.job_id
            where d.completed_at is null and d.attempts >= d.max_attempts
              and (d.lease_expires_at is null or d.lease_expires_at < now())
            limit %s for update of d skip locked
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        for d in rows:
            if d["kind"] == "advance":
                internal = "submission_unknown" if d["internal_state"] == "submitting" else "failed"
                code = (
                    "generation_status_unknown"
                    if internal == "submission_unknown"
                    else "service_unavailable"
                )
                await conn.execute(
                    """
                    update jobs set status='failed', internal_state=%(i)s, error_code=%(c)s,
                        provider_output_url=null, finished_at=now(),
                        phase_version=phase_version+1, updated_at=now()
                    where job_id=%(j)s and status not in ('succeeded','failed','canceled')
                    """,
                    {"i": internal, "c": code, "j": d["job_id"]},
                )
                await conn.execute(
                    "update job_dispatch set completed_at=now() where id=%s", (d["id"],)
                )
            else:
                log("cleanup_exhausted", job_id=d["job_id"], dispatch_id=d["id"])
                await conn.execute(
                    """
                    update job_dispatch set attempts=0, run_after=now()+interval '1 hour',
                        lease_token=null, lease_expires_at=null
                    where id=%s
                    """,
                    (d["id"],),
                )
        counts["exhausted"] = len(rows)

        # 3. expired jobs needing cleanup
        cur = await conn.execute(
            """
            select j.job_id, j.phase_version from jobs j
            where j.expires_at < now()
              and exists (select 1 from stored_objects s
                          where s.job_id=j.job_id and s.deleted_at is null)
              and not exists (select 1 from job_dispatch d
                              where d.job_id=j.job_id and d.kind='cleanup'
                                and d.completed_at is null)
            limit %s for update of j skip locked
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        for job in rows:
            new_v = job["phase_version"] + 1
            await conn.execute(
                "update jobs set phase_version=%(v)s, updated_at=now() where job_id=%(j)s",
                {"v": new_v, "j": job["job_id"]},
            )
            await conn.execute(
                """
                insert into job_dispatch (job_id, kind, phase_version, max_attempts)
                values (%(j)s, 'cleanup', %(v)s, %(m)s)
                on conflict (job_id, kind, phase_version) do nothing
                """,
                {"j": job["job_id"], "v": new_v, "m": settings.dispatch_max_attempts},
            )
        counts["cleanup_enqueued"] = len(rows)

        # 4. purge expired records
        cur = await conn.execute(
            "delete from jobs where job_id in"
            " (select job_id from jobs where records_expire_at < now() limit %s)",
            (limit,),
        )
        counts["purged"] = cur.rowcount

    # 5. orphan objects
    orphans = 0
    try:
        infos = await deps.store.list_prefix("jobs/", limit)
    except Exception:
        infos = []
    async with deps.pool.connection() as conn:
        for info in infos:
            parts = info.name.split("/")
            if len(parts) < 2:
                continue
            job_id = parts[1]
            cur = await conn.execute("select 1 from jobs where job_id=%s", (job_id,))
            if await cur.fetchone() is None:
                if info.updated_at < datetime.now(UTC) - timedelta(hours=1):
                    try:
                        await deps.store.delete(info.name)
                        orphans += 1
                    except Exception:
                        log("orphan_delete_failed", job_id=job_id)
    counts["orphans_deleted"] = orphans
    return counts
