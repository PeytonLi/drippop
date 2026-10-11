from tests.conftest import idem_headers, job_form


async def test_rows_exist_after_202(client, auth, uid, deps):
    r = await client.post("/v1/jobs", headers=idem_headers(auth(uid)), **job_form())
    assert r.status_code == 202
    jid = r.json()["job_id"]
    async with deps.pool.connection() as conn:
        job = await (await conn.execute("select * from jobs where job_id=%s", (jid,))).fetchone()
        assert job is not None
        idem = await (
            await conn.execute("select * from idempotency_records where job_id=%s", (jid,))
        ).fetchone()
        assert idem is not None
        disp = await (
            await conn.execute("select * from job_dispatch where job_id=%s", (jid,))
        ).fetchall()
        assert len(disp) == 1 and disp[0]["kind"] == "advance"
        objs = await (
            await conn.execute("select * from stored_objects where job_id=%s", (jid,))
        ).fetchall()
        assert len(objs) == 2


async def test_tx_failure_rolls_back_and_deletes_objects(client, auth, uid, deps, monkeypatch):
    # Break dispatch inserts: make the SQL for job_dispatch fail via a wrapper conn.

    orig = deps.pool.connection

    class BrokenConn:
        def __init__(self, cm):
            self._cm = cm

        async def __aenter__(self):
            self._conn = await self._cm.__aenter__()
            return self

        async def __aexit__(self, *a):
            return await self._cm.__aexit__(*a)

        def transaction(self):
            return self._conn.transaction()

        async def execute(self, sql, params=None):
            if "insert into job_dispatch" in sql:
                raise RuntimeError("boom")
            return await self._conn.execute(sql, params)

    def connection():
        return BrokenConn(orig())

    monkeypatch.setattr(deps.pool, "connection", connection)
    r = await client.post("/v1/jobs", headers=idem_headers(auth(uid)), **job_form())
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "service_unavailable"
    async with deps.pool.connection() as conn:
        assert (await (await conn.execute("select count(*) c from jobs")).fetchone())["c"] == 0
        assert (
            await (await conn.execute("select count(*) c from idempotency_records")).fetchone()
        )["c"] == 0
    infos = await deps.store.list_prefix("jobs/", 100)
    assert infos == []
