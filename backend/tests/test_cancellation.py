import secrets

from providers.fake import FakeGenerationProvider
from tests.conftest import idem_headers, job_form


async def _create(client, h):
    r = await client.post("/v1/jobs", headers=idem_headers(h), **job_form())
    assert r.status_code == 202
    return r.json()["job_id"]


async def test_cancel_queued(client, auth, uid, deps, drain_fn, fake_generator):
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    r = await client.delete(f"/v1/jobs/{jid}", headers=h)
    assert r.status_code == 202 and r.json()["status"] == "canceled"
    await drain_fn()
    assert fake_generator.submit_calls == 0
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select status from jobs where job_id=%s", (jid,))
        ).fetchone()
        assert job["status"] == "canceled"
        objs = await (
            await conn.execute(
                "select count(*) c from stored_objects where job_id=%s and deleted_at is null",
                (jid,),
            )
        ).fetchone()
        assert objs["c"] == 0


async def test_cancel_while_polling(client, auth, uid, deps, drain_fn, fake_generator):
    deps.generator = FakeGenerationProvider(pending_checks=1000)
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    # step until polling: queued -> ready -> submit -> first check(pending)
    await drain_fn(max_steps=4)
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select internal_state from jobs where job_id=%s", (jid,))
        ).fetchone()
    assert job["internal_state"] == "polling"
    await client.delete(f"/v1/jobs/{jid}", headers=h)
    calls = fake_generator.check_calls
    await drain_fn()
    assert fake_generator.check_calls == calls  # no further checks
    async with deps.pool.connection() as conn:
        objs = await (
            await conn.execute(
                "select count(*) c from stored_objects where job_id=%s and deleted_at is null",
                (jid,),
            )
        ).fetchone()
        assert objs["c"] == 0


async def test_cancel_during_finalize(client, auth, uid, deps, drain_fn, app, fake_generator):
    h = auth(uid)

    async def on_download():
        await client.delete(f"/v1/jobs/{jid}", headers=h)

    deps.generator = FakeGenerationProvider(on_download=on_download)
    jid = await _create(client, idem_headers(h))
    await drain_fn()
    async with deps.pool.connection() as conn:
        job = await (
            await conn.execute("select status from jobs where job_id=%s", (jid,))
        ).fetchone()
        assert job["status"] == "canceled"
    objs = await deps.store.list_prefix(f"jobs/{jid}/", 10)
    assert not any("result" in o.name for o in objs)
    r = await client.get(f"/v1/jobs/{jid}/result", headers=h)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "job_canceled"


async def test_delete_twice_202_same_body(client, auth, uid):
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    r1 = await client.delete(f"/v1/jobs/{jid}", headers=h)
    r2 = await client.delete(f"/v1/jobs/{jid}", headers=h)
    assert r1.status_code == 202 and r2.status_code == 202
    assert r1.json() == r2.json()


async def test_delete_after_succeeded(client, auth, uid, deps, drain_fn):
    h = auth(uid)
    jid = await _create(client, idem_headers(h))
    await drain_fn()
    r = await client.delete(f"/v1/jobs/{jid}", headers=h)
    assert r.status_code == 202
    rr = await client.get(f"/v1/jobs/{jid}/result", headers=h)
    assert rr.status_code == 409
    assert rr.json()["error"]["code"] == "job_canceled"
    await drain_fn()
    objs = await deps.store.list_prefix(f"jobs/{jid}/", 10)
    assert objs == []


async def test_replay_key_after_cancel(client, auth, uid, deps, drain_fn, fake_generator):
    key = "k-" + secrets.token_urlsafe(16)
    h = idem_headers(auth(uid), key)
    form = job_form()
    r1 = await client.post("/v1/jobs", headers=h, **form)
    jid = r1.json()["job_id"]
    await client.delete(f"/v1/jobs/{jid}", headers=auth(uid))
    r2 = await client.post("/v1/jobs", headers=h, **form)
    assert r2.status_code == 202
    assert r2.json()["job_id"] == jid
    assert r2.json()["status"] == "canceled"
    await drain_fn()
    assert fake_generator.submit_calls == 0
