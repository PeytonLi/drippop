from tests.conftest import idem_headers, job_form


async def _create(client, headers):
    r = await client.post("/v1/jobs", headers=headers, **job_form())
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


async def test_other_owner_gets_404(client, auth, uid):
    job_id = await _create(client, idem_headers(auth(uid)))
    r1 = await client.get(f"/v1/jobs/{job_id}", headers=auth())
    assert r1.status_code == 404
    r2 = await client.get("/v1/jobs/" + "z" * 20, headers=auth())
    assert r2.status_code == 404
    assert r1.content == r2.content


async def test_other_owner_delete_and_result_404(client, auth, uid):
    job_id = await _create(client, idem_headers(auth(uid)))
    for method, url in (
        ("DELETE", f"/v1/jobs/{job_id}"),
        ("GET", f"/v1/jobs/{job_id}/result"),
    ):
        r = await client.request(method, url, headers=auth())
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"


async def test_malformed_job_id_404(client, auth):
    for bad in ("short", "has space in id 123456", "x" * 100):
        r = await client.get(f"/v1/jobs/{bad}", headers=auth())
        assert r.status_code == 404
