from providers.base import SubmitAmbiguous, SubmitRejected
from providers.fake import FakeGenerationProvider
from tests.conftest import idem_headers, job_form


async def test_live_cap0_503(client, auth, deps, fake_generator):
    deps.settings.provider_mode = "live"
    deps.settings.daily_paid_attempt_cap = 0
    deps.contracts.categories["enabled"] = ["upper_body"]
    deps.generator = fake_generator
    r = await client.post("/v1/jobs", headers=idem_headers(auth()), **job_form())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "service_unavailable"
    assert r.json()["error"]["retryable"] is False


async def test_fake_cap1_second_429(client, auth, uid, deps):
    deps.settings.daily_paid_attempt_cap = 1
    h = auth(uid)
    r1 = await client.post("/v1/jobs", headers=idem_headers(h), **job_form())
    assert r1.status_code == 202
    async with deps.pool.connection() as conn:
        await conn.execute(
            "insert into budget_days (day, paid_attempts)"
            " values ((now() at time zone 'utc')::date, 1)"
        )
    r2 = await client.post("/v1/jobs", headers=idem_headers(h), **job_form())
    assert r2.status_code == 429
    assert r2.json()["error"]["code"] == "quota_exceeded"
    assert r2.json()["error"]["retryable"] is True


async def test_reservation_race_one_reserved(client, auth, deps, drain_fn):
    deps.settings.provider_mode = "live"
    deps.settings.daily_paid_attempt_cap = 1
    deps.contracts.categories["enabled"] = ["upper_body"]
    r1 = await client.post("/v1/jobs", headers=idem_headers(auth("ra")), **job_form())
    r2 = await client.post("/v1/jobs", headers=idem_headers(auth("rb")), **job_form())
    assert r1.status_code == 202 and r2.status_code == 202
    await drain_fn()
    async with deps.pool.connection() as conn:
        jobs = await (
            await conn.execute("select status, error_code from jobs order by created_at")
        ).fetchall()
    statuses = sorted(j["status"] for j in jobs)
    assert statuses == ["failed", "succeeded"], statuses
    failed = next(j for j in jobs if j["status"] == "failed")
    assert failed["error_code"] == "quota_exceeded"


async def test_submit_rejected_releases_reservation(client, auth, deps, drain_fn):
    deps.settings.provider_mode = "live"
    deps.settings.daily_paid_attempt_cap = 5
    deps.contracts.categories["enabled"] = ["upper_body"]
    deps.generator = FakeGenerationProvider(submit_error=SubmitRejected("provider_rejected"))
    r = await client.post("/v1/jobs", headers=idem_headers(auth("rj")), **job_form())
    assert r.status_code == 202
    await drain_fn()
    async with deps.pool.connection() as conn:
        job = await (await conn.execute("select * from jobs")).fetchone()
        assert job["status"] == "failed" and job["error_code"] == "provider_rejected"
        res = await (await conn.execute("select * from budget_reservations")).fetchone()
        assert res["status"] == "released"


async def test_ambiguous_keeps_reservation(client, auth, deps, drain_fn):
    deps.settings.provider_mode = "live"
    deps.settings.daily_paid_attempt_cap = 5
    deps.contracts.categories["enabled"] = ["upper_body"]
    deps.generator = FakeGenerationProvider(submit_error=SubmitAmbiguous())
    r = await client.post("/v1/jobs", headers=idem_headers(auth("am")), **job_form())
    assert r.status_code == 202
    await drain_fn()
    async with deps.pool.connection() as conn:
        job = await (await conn.execute("select * from jobs")).fetchone()
        assert job["status"] == "failed"
        assert job["internal_state"] == "submission_unknown"
        res = await (await conn.execute("select * from budget_reservations")).fetchone()
        assert res["status"] == "reserved"
