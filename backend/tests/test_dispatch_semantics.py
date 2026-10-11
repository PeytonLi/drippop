import asyncio

from core.dispatch import claim
from tests.conftest import idem_headers, job_form


async def _create_job(client, h):
    r = await client.post("/v1/jobs", headers=h, **job_form())
    assert r.status_code == 202
    return r.json()["job_id"]


async def test_duplicate_delivery_no_extra_calls(client, auth, uid, deps, drain_fn, fake_generator):
    h = auth(uid)
    jid = await _create_job(client, idem_headers(h))
    await drain_fn()
    async with deps.pool.connection() as conn:
        await conn.execute("update job_dispatch set completed_at=null where job_id=%s", (jid,))
    await drain_fn()
    assert fake_generator.submit_calls == 1
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select status, internal_state from jobs where job_id=%s", (jid,))
        ).fetchone()
    assert job["status"] == "succeeded"


async def test_stale_version_dispatch_noop(client, auth, uid, deps, drain_fn, fake_generator):
    h = auth(uid)
    jid = await _create_job(client, idem_headers(h))
    await drain_fn()
    async with deps.pool.connection() as conn:
        await conn.execute(
            "insert into job_dispatch (job_id, kind, phase_version, max_attempts)"
            " values (%s, 'advance', 999, 5)",
            (jid,),
        )
    await drain_fn()
    assert fake_generator.submit_calls == 1


async def test_lease_takeover_and_fence(client, auth, uid, deps):
    h = auth(uid)
    await _create_job(client, idem_headers(h))
    async with deps.pool.connection() as conn, conn.transaction():
        d1 = await claim(conn, 60)
    assert d1 is not None
    # expire lease
    async with deps.pool.connection() as conn, conn.transaction():
        await conn.execute(
            "update job_dispatch set lease_expires_at = now() - interval '1s' where id=%s",
            (d1["id"],),
        )
        d2 = await claim(conn, 60)
    assert d2 is not None and d2["lease_token"] != d1["lease_token"]
    # lease A commit attempt rejected: fence on d1 fails
    async with deps.pool.connection() as conn, conn.transaction():
        from core.dispatch import _fence

        fenced = await _fence(conn, d1)
        assert fenced is None


async def test_reschedule_is_fenced(client, auth, uid, deps):
    """A stale worker's _reschedule must not wipe the new lease holder."""
    from core.dispatch import _reschedule

    h = auth(uid)
    await _create_job(client, idem_headers(h))
    async with deps.pool.connection() as conn, conn.transaction():
        a = await claim(conn, 60)
    assert a is not None
    async with deps.pool.connection() as conn, conn.transaction():
        await conn.execute(
            "update job_dispatch set lease_expires_at = now() - interval '1s' where id=%s",
            (a["id"],),
        )
        b = await claim(conn, 60)
    assert b is not None and b["lease_token"] != a["lease_token"]
    # A reschedules after losing the lease — must not touch B's row.
    await _reschedule(deps, a, "internal_error")
    async with deps.pool.connection() as conn:
        row = await (
            await conn.execute("select * from job_dispatch where id=%s", (a["id"],))
        ).fetchone()
    assert row["lease_token"] == b["lease_token"]
    assert row["lease_expires_at"] is not None
    # B can still complete.
    async with deps.pool.connection() as conn, conn.transaction():
        from core.dispatch import _complete_and_next, _fence

        fenced = await _fence(conn, b)
        assert fenced is not None
        await _complete_and_next(conn, b, fenced["phase_version"], None)
    async with deps.pool.connection() as conn:
        row = await (
            await conn.execute("select completed_at from job_dispatch where id=%s", (a["id"],))
        ).fetchone()
    assert row["completed_at"] is not None


async def test_skip_locked_one_row_total(client, auth, uid, deps):
    h = auth(uid)
    await _create_job(client, idem_headers(h))

    async def claimer():
        async with deps.pool.connection() as conn, conn.transaction():
            d = await claim(conn, 60)
            await asyncio.sleep(0.05)
            return d

    results = await asyncio.gather(claimer(), claimer())
    got = [r for r in results if r is not None]
    assert len(got) == 1
