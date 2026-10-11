import asyncio
import secrets

from tests.conftest import idem_headers, job_form


async def test_second_key_while_active_409(client, auth, uid):
    r1 = await client.post("/v1/jobs", headers=idem_headers(auth(uid)), **job_form())
    assert r1.status_code == 202
    jid = r1.json()["job_id"]
    r2 = await client.post("/v1/jobs", headers=idem_headers(auth(uid)), **job_form())
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "active_job_exists"
    assert r2.json()["job_id"] == jid


async def test_allowed_after_canceled(client, auth, uid):
    h = auth(uid)
    r1 = await client.post("/v1/jobs", headers=idem_headers(h), **job_form())
    jid = r1.json()["job_id"]
    await client.delete(f"/v1/jobs/{jid}", headers=h)
    r2 = await client.post("/v1/jobs", headers=idem_headers(h), **job_form())
    assert r2.status_code == 202


async def test_allowed_after_terminal(client, auth, uid, drain_fn):
    h = auth(uid)
    r1 = await client.post("/v1/jobs", headers=idem_headers(h), **job_form())
    assert r1.status_code == 202
    await drain_fn()
    r2 = await client.post("/v1/jobs", headers=idem_headers(h), **job_form())
    assert r2.status_code == 202


async def test_concurrent_new_keys_one_202(client, auth, uid):
    h = auth(uid)
    results = await asyncio.gather(
        *[
            client.post(
                "/v1/jobs",
                headers=idem_headers(h, secrets.token_urlsafe(24)),
                **job_form(),
            )
            for _ in range(5)
        ]
    )
    codes = [r.status_code for r in results]
    assert codes.count(202) == 1, codes
    assert codes.count(409) == 4
