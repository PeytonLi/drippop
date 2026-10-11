import pytest

from tests.conftest import idem_headers, job_form


class SimulatedCrash(BaseException):
    pass


async def _create(client, auth, uid, deps):
    r = await client.post("/v1/jobs", headers=idem_headers(auth(uid)), **job_form())
    assert r.status_code == 202
    return r.json()["job_id"]


async def test_crash_after_marker_no_resubmit(client, auth, uid, deps, drain_fn, fake_generator):
    jid = await _create(client, auth, uid, deps)

    orig_submit = fake_generator.submit
    calls = {"n": 0}

    async def crashing_submit(*a, **k):
        calls["n"] += 1
        raise SimulatedCrash("boom")

    fake_generator.submit = crashing_submit
    # BaseException bypasses handler's except Exception -> handler dies mid-tx2.
    # Simulate crash between tx1 commit and tx2: instead crash with a regular
    # Exception so submission_unknown is recorded via the ambiguous path? No —
    # crash AFTER marker commit means worker dies; emulate by raising
    # SimulatedCrash inside submit after tx1 (submit is called after tx1).
    with pytest.raises(SimulatedCrash):
        await drain_fn()
    fake_generator.submit = orig_submit
    # expire lease so recovery dispatch can be claimed
    async with deps.pool.connection() as conn:
        await conn.execute(
            "update job_dispatch set lease_expires_at = now() - interval '1s',"
            " run_after = now() - interval '1s' where completed_at is null"
        )
    await drain_fn()
    async with deps.pool.connection() as conn:
        job = await (await conn.execute("select * from jobs where job_id=%s", (jid,))).fetchone()
        res = await (
            await conn.execute("select * from budget_reservations where job_id=%s", (jid,))
        ).fetchone()
    assert job["status"] == "failed"
    assert job["internal_state"] == "submission_unknown"
    assert job["error_code"] == "generation_status_unknown"
    assert calls["n"] == 1
    if res is not None:  # live-mode reservation semantics; fake has none
        assert res["status"] == "reserved"


async def test_crash_in_check_retried(
    client, auth, uid, deps, drain_fn, fake_generator, monkeypatch
):
    jid = await _create(client, auth, uid, deps)
    orig = fake_generator.check
    called = {"n": 0}

    async def flaky_check(ticket):
        called["n"] += 1
        if called["n"] == 1:
            raise RuntimeError("transient")
        return await orig(ticket)

    monkeypatch.setattr(fake_generator, "check", flaky_check)
    await drain_fn()
    # first check raised -> dispatch rescheduled with backoff; expedite it
    async with deps.pool.connection() as conn:
        await conn.execute(
            "update job_dispatch set run_after = now() - interval '1s' where completed_at is null"
        )
    await drain_fn()
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select status from jobs where job_id=%s", (jid,))
        ).fetchone()
    assert job["status"] == "succeeded"
    assert called["n"] >= 2


async def test_transient_download_error_reschedules(
    client, auth, uid, deps, drain_fn, fake_generator, monkeypatch
):
    import httpx

    jid = await _create(client, auth, uid, deps)
    orig = fake_generator.download
    calls = {"n": 0}

    async def flaky_download(url, max_bytes):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("net down")
        return await orig(url, max_bytes)

    monkeypatch.setattr(fake_generator, "download", flaky_download)
    await drain_fn()
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select status, internal_state from jobs where job_id=%s", (jid,))
        ).fetchone()
        # transient -> rescheduled, still finalizing (not permanently failed)
        assert job["status"] == "processing" and job["internal_state"] == "finalizing"
        await conn.execute(
            "update job_dispatch set run_after = now() - interval '1s' where completed_at is null"
        )
    await drain_fn()
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select status from jobs where job_id=%s", (jid,))
        ).fetchone()
    assert job["status"] == "succeeded"
    assert calls["n"] == 2


async def test_invalid_output_fails_provider_rejected(
    client, auth, uid, deps, drain_fn, fake_generator, monkeypatch
):
    jid = await _create(client, auth, uid, deps)

    async def bad_download(url, max_bytes):
        return b"not-an-image"  # validate_and_prepare -> invalid_image -> provider_rejected

    monkeypatch.setattr(fake_generator, "download", bad_download)
    await drain_fn()
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select status, error_code from jobs where job_id=%s", (jid,))
        ).fetchone()
    assert job["status"] == "failed" and job["error_code"] == "provider_rejected"


async def test_crash_after_result_put_before_commit(
    client, auth, uid, deps, drain_fn, fake_generator, monkeypatch
):
    jid = await _create(client, auth, uid, deps)
    import core.dispatch as disp

    orig_fence = disp._fence
    state = {"crashed": False}

    async def flaky_fence(conn, dispatch):
        # crash only on the finalize fence AFTER the object was written
        job = await disp._load_job(conn, dispatch["job_id"])
        if (
            job
            and job["internal_state"] == "finalizing"
            and not state["crashed"]
            and dispatch["kind"] == "advance"
        ):
            objs = await deps.store.list_prefix(f"jobs/{jid}/", 10)
            if any("result" in o.name for o in objs):
                state["crashed"] = True
                raise SimulatedCrash("crash after put")
        return await orig_fence(conn, dispatch)

    monkeypatch.setattr(disp, "_fence", flaky_fence)
    with pytest.raises(SimulatedCrash):
        await drain_fn()
    async with deps.pool.connection() as conn:
        await conn.execute(
            "update job_dispatch set lease_expires_at = now() - interval '1s',"
            " run_after = now() - interval '1s' where completed_at is null"
        )
    monkeypatch.setattr(disp, "_fence", orig_fence)
    await drain_fn()
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute(
                "select status, result_object_path from jobs where job_id=%s", (jid,)
            )
        ).fetchone()
    assert job["status"] == "succeeded"
    objs = await deps.store.list_prefix(f"jobs/{jid}/", 10)
    assert len([o for o in objs if "result" in o.name]) == 1
