import io
import logging

from PIL import Image

from tests.conftest import idem_headers, job_form, make_token


async def test_fake_e2e(client, auth, uid, deps, drain_fn, fake_generator):
    h = auth(uid)
    r = await client.post("/v1/jobs", headers=idem_headers(h), **job_form())
    assert r.status_code == 202
    jid = r.json()["job_id"]
    g = await client.get(f"/v1/jobs/{jid}", headers=h)
    assert g.json()["status"] == "queued"
    await drain_fn()
    g = await client.get(f"/v1/jobs/{jid}", headers=h)
    body = g.json()
    assert body["status"] == "succeeded"
    assert body["result_available"] is True
    res = await client.get(f"/v1/jobs/{jid}/result", headers=h)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["content-type"].startswith("image/jpeg")
    im = Image.open(io.BytesIO(res.content))
    im.load()
    assert len(res.content) > 0
    async with deps.pool.connection() as conn:
        rows = await (
            await conn.execute(
                "select count(*) c from job_dispatch where job_id=%s and completed_at is null",
                (jid,),
            )
        ).fetchone()
        assert rows["c"] == 0
    assert fake_generator.submit_calls == 1


async def test_logs_do_not_leak(client, auth, uid, deps, drain_fn, caplog, ec_key):
    token = make_token(uid, priv=ec_key)
    h = {"Authorization": f"Bearer {token}"}
    with caplog.at_level(logging.INFO):
        r = await client.post("/v1/jobs", headers=idem_headers(h), **job_form())
        assert r.status_code == 202
        await drain_fn()
    text = "\n".join(rec.getMessage() + str(getattr(rec, "fields", "")) for rec in caplog.records)
    assert token not in text
    assert "fake://" not in text
    assert uid not in text
