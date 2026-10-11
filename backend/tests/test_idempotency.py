import asyncio
import secrets

from tests.conftest import idem_headers, job_form, make_jpeg


async def _create(client, headers, **form_kwargs):
    return await client.post("/v1/jobs", headers=headers, **job_form(**form_kwargs))


async def test_replay_same_key_same_bytes(client, auth, uid, drain_fn):
    h = idem_headers(auth(uid), "key-" + secrets.token_urlsafe(16))
    form = job_form(person=make_jpeg())
    r1 = await client.post("/v1/jobs", headers=h, **form)
    assert r1.status_code == 202
    jid = r1.json()["job_id"]
    # while active
    r2 = await client.post("/v1/jobs", headers=h, **form)
    assert r2.status_code == 202 and r2.json()["job_id"] == jid
    # after succeeded
    await drain_fn()
    r3 = await client.post("/v1/jobs", headers=h, **form)
    assert r3.status_code == 202 and r3.json()["job_id"] == jid
    # after cancel
    await client.delete(f"/v1/jobs/{jid}", headers=auth(uid))
    r4 = await client.post("/v1/jobs", headers=h, **form)
    assert r4.status_code == 202 and r4.json()["job_id"] == jid
    assert r4.json()["status"] == "canceled"


async def test_replay_at_quota(client, auth, uid, deps):
    deps.settings.daily_paid_attempt_cap = 1
    h = idem_headers(auth(uid), "key-" + secrets.token_urlsafe(16))
    form = job_form(person=make_jpeg())
    r1 = await client.post("/v1/jobs", headers=h, **form)
    assert r1.status_code == 202
    async with deps.pool.connection() as conn:
        await conn.execute(
            "insert into budget_days (day, paid_attempts)"
            " values ((now() at time zone 'utc')::date, 1)"
        )
    r2 = await client.post("/v1/jobs", headers=h, **form)
    assert r2.status_code == 202 and r2.json()["job_id"] == r1.json()["job_id"]


async def test_same_key_different_bytes_409(client, auth, uid):
    h = idem_headers(auth(uid), "key-" + secrets.token_urlsafe(16))
    r1 = await _create(client, h, person=make_jpeg(color=(1, 2, 3)))
    assert r1.status_code == 202
    r2 = await _create(client, h, person=make_jpeg(color=(9, 9, 9)))
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "idempotency_conflict"
    assert r2.json()["job_id"] is None


async def test_same_key_different_category_409(client, auth, uid):
    h = idem_headers(auth(uid), "key-" + secrets.token_urlsafe(16))
    p = make_jpeg()
    r1 = await _create(client, h, person=p, metadata={"garment_category": "upper_body"})
    assert r1.status_code == 202
    r2 = await _create(client, h, person=p, metadata={"garment_category": "full_body"})
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "idempotency_conflict"


async def test_different_owners_same_key(client, auth):
    key = "key-" + secrets.token_urlsafe(16)
    r1 = await _create(client, idem_headers(auth("owner-a"), key))
    r2 = await _create(client, idem_headers(auth("owner-b"), key))
    assert r1.status_code == 202 and r2.status_code == 202
    assert r1.json()["job_id"] != r2.json()["job_id"]


async def test_concurrent_same_key(client, auth, uid, deps):
    h = idem_headers(auth(uid), "key-" + secrets.token_urlsafe(16))
    form = job_form(person=make_jpeg())
    results = await asyncio.gather(*[client.post("/v1/jobs", headers=h, **form) for _ in range(5)])
    codes = [r.status_code for r in results]
    job_ids = {r.json()["job_id"] for r in results if r.status_code == 202}
    assert all(c == 202 for c in codes), codes
    assert len(job_ids) == 1
    async with deps.pool.connection() as conn:
        cur = await conn.execute("select count(*) c from jobs")
        assert (await cur.fetchone())["c"] == 1
