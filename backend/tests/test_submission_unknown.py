from core.dispatch import WorkerDeps, reconcile
from providers.base import SubmitAmbiguous
from providers.fake import FakeGenerationProvider
from tests.conftest import idem_headers, job_form


async def test_submit_ambiguous(client, auth, uid, deps, drain_fn):
    deps.generator = FakeGenerationProvider(submit_error=SubmitAmbiguous())
    r = await client.post("/v1/jobs", headers=idem_headers(auth(uid)), **job_form())
    assert r.status_code == 202
    jid = r.json()["job_id"]
    await drain_fn()
    g = await client.get(f"/v1/jobs/{jid}", headers=auth(uid))
    assert g.json()["status"] == "failed"
    assert g.json()["error"]["code"] == "generation_status_unknown"
    assert g.json()["error"]["retryable"] is False
    # further drains/reconcile do not resubmit
    await drain_fn()
    wd = WorkerDeps(
        settings=deps.settings,
        pool=deps.pool,
        store=deps.store,
        generator=deps.generator,
        detector=deps.detector,
        contracts=deps.contracts,
    )
    await reconcile(wd)
    assert deps.generator.submit_calls == 1


async def test_submit_timeout(client, auth, uid, deps, drain_fn):
    deps.generator = FakeGenerationProvider(submit_error=TimeoutError())
    r = await client.post("/v1/jobs", headers=idem_headers(auth(uid)), **job_form())
    jid = r.json()["job_id"]
    await drain_fn()
    g = await client.get(f"/v1/jobs/{jid}", headers=auth(uid))
    assert g.json()["status"] == "failed"
    assert g.json()["error"]["code"] == "generation_status_unknown"
