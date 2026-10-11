import os
import time

import pytest

from core.dispatch import WorkerDeps, reconcile
from providers.fake import FakeGenerationProvider
from tests.conftest import idem_headers, job_form


@pytest.fixture
def wdeps(deps):
    return WorkerDeps(
        settings=deps.settings,
        pool=deps.pool,
        store=deps.store,
        generator=deps.generator,
        detector=deps.detector,
        contracts=deps.contracts,
    )


async def _create(client, h, **kw):
    r = await client.post("/v1/jobs", headers=h, **job_form(**kw))
    assert r.status_code == 202
    return r.json()["job_id"]


async def test_result_409_not_ready_queued(client, auth, uid):
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    r = await client.get(f"/v1/jobs/{jid}/result", headers=h)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "result_not_ready"
    assert err["retryable"] is True


async def test_result_410_expired(client, auth, uid, deps, drain_fn):
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    await drain_fn()
    async with deps.pool.connection() as conn:
        await conn.execute(
            "update jobs set expires_at = now() - interval '1s' where job_id=%s", (jid,)
        )
    r = await client.get(f"/v1/jobs/{jid}/result", headers=h)
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "result_expired"


async def test_reconcile_enqueues_cleanup(client, auth, uid, deps, drain_fn, wdeps):
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    await drain_fn()
    async with deps.pool.connection() as conn:
        await conn.execute(
            "update jobs set expires_at = now() - interval '1s' where job_id=%s", (jid,)
        )
    await reconcile(wdeps)
    async with deps.pool.connection() as conn:
        d = await (
            await conn.execute(
                "select * from job_dispatch where job_id=%s and kind='cleanup'"
                " and completed_at is null",
                (jid,),
            )
        ).fetchone()
        assert d is not None
    await drain_fn()
    objs = await deps.store.list_prefix(f"jobs/{jid}/", 10)
    assert objs == []


async def test_deadline_past_while_polling(client, auth, uid, deps, drain_fn, wdeps):
    deps.generator = FakeGenerationProvider(pending_checks=1000)
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    await drain_fn(max_steps=4)
    async with deps.pool.connection() as conn:
        await conn.execute(
            "update jobs set deadline_at = now() - interval '1s' where job_id=%s", (jid,)
        )
    await reconcile(wdeps)
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select status, error_code from jobs where job_id=%s", (jid,))
        ).fetchone()
    assert job["status"] == "failed" and job["error_code"] == "generation_timeout"


async def test_exhausted_dispatch_fails_job(client, auth, uid, deps, wdeps):
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    async with deps.pool.connection() as conn:
        await conn.execute(
            "update job_dispatch set attempts = max_attempts, lease_expires_at = null,"
            " lease_token = null where job_id=%s",
            (jid,),
        )
    await reconcile(wdeps)
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select status, error_code from jobs where job_id=%s", (jid,))
        ).fetchone()
    assert job["status"] == "failed" and job["error_code"] == "service_unavailable"


async def test_records_expired_purged(client, auth, uid, deps, wdeps):
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    async with deps.pool.connection() as conn:
        await conn.execute(
            "update jobs set records_expire_at = now() - interval '1s' where job_id=%s", (jid,)
        )
    await reconcile(wdeps)
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select count(*) c from jobs where job_id=%s", (jid,))
        ).fetchone()
    assert job["c"] == 0


async def test_orphan_object_deleted(deps, wdeps):
    store = deps.store
    await store.put("jobs/unknownjob1234567/person.jpg", b"x", "image/jpeg")
    path = store.root / "jobs/unknownjob1234567/person.jpg"
    old = time.time() - 3700
    os.utime(path, (old, old))
    counts = await reconcile(wdeps)
    assert counts["orphans_deleted"] == 1
    assert await store.list_prefix("jobs/", 10) == []
