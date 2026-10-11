import asyncio
import json

from tests.conftest import CONTRACTS_DIR, make_jpeg, validate_schema


def _post(client, h, **files):
    return client.post(
        "/v1/garments:detect",
        headers=h,
        files={"frame": ("f.jpg", make_jpeg(640, 480), "image/jpeg")},
    )


async def test_fake_detect_valid(client, auth):
    r = await _post(client, auth())
    assert r.status_code == 200
    body = r.json()
    validate_schema("detection_response.schema.json", body)
    assert len(body["persons"]) == 1
    assert body["image_width"] == 640 and body["image_height"] == 480


class StubDetector:
    def __init__(self, doc=None, exc=None, delay=0.0):
        self.doc = doc
        self.exc = exc
        self.delay = delay

    async def detect(self, frame):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.doc


def _fixture(path):
    return json.loads(path.read_text())


async def test_valid_fixtures_pass_through(client, auth, deps):
    h = auth()
    for f in sorted((CONTRACTS_DIR / "fixtures" / "valid").glob("detection_response.*")):
        doc = _fixture(f)
        doc["image_width"], doc["image_height"] = 640, 480
        deps.detector = StubDetector(doc)
        r = await _post(client, h)
        assert r.status_code == 200
        body = r.json()
        assert body == doc, f.name


async def test_invalid_fixtures_fallback(client, auth, deps):
    h = auth()
    for sub in ("invalid", "semantic_invalid"):
        for f in sorted((CONTRACTS_DIR / "fixtures" / sub).glob("detection_response.*")):
            deps.detector = StubDetector(_fixture(f))
            r = await _post(client, h)
            assert r.status_code == 200
            body = r.json()
            assert body["persons"] == [], f.name
            assert body["manual_selection_required"] is True
            assert body["image_width"] == 640


async def test_provider_exception_fallback(client, auth, deps):
    deps.detector = StubDetector(exc=RuntimeError("boom"))
    r = await _post(client, auth())
    assert r.status_code == 200
    assert r.json()["manual_selection_required"] is True


async def test_provider_timeout_fallback(client, auth, deps):
    deps.settings.detect_timeout_s = 0.05
    deps.detector = StubDetector(doc={}, delay=0.5)
    r = await _post(client, auth())
    assert r.status_code == 200
    assert r.json()["manual_selection_required"] is True


async def test_live_no_provider_503(client, auth, deps):
    deps.detector = None
    deps.settings.provider_mode = "live"
    r = await _post(client, auth())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "analysis_unavailable"


async def test_uid_quota_429(client, auth, uid, deps):
    deps.settings.detect_daily_cap_per_uid = 2
    deps.settings.detect_daily_cap_project = 100
    h = auth(uid)
    for _ in range(2):
        assert (await _post(client, h)).status_code == 200
    r = await _post(client, h)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "quota_exceeded"


async def test_nothing_persisted_except_counters(client, auth, deps):
    r = await _post(client, auth())
    assert r.status_code == 200
    async with deps.pool.connection() as conn:
        assert (await (await conn.execute("select count(*) c from jobs")).fetchone())["c"] == 0
        counters = await (await conn.execute("select * from usage_counters")).fetchall()
        assert len(counters) == 2
