import json
from pathlib import Path

import httpx
import respx
from httpx import ASGITransport

import worker
from api.deps import AppDeps
from api.main import create_app
from core.auth import JwksCache, TokenVerifier
from core.contracts import ContractSchemas
from core.settings import Settings
from core.storage import LocalObjectStore
from providers.gemini import GeminiDetectionProvider
from providers.live import aclose_providers, build_live_providers
from providers.youcam import YouCamGenerationProvider
from tests.conftest import CONTRACTS_DIR, make_jpeg, validate_schema

GEMINI_ENVELOPE = json.loads(
    (
        Path(__file__).parent / "providers" / "fixtures" / "gemini" / "detection_response.json"
    ).read_text()
)


def _live_settings(tmp_path, monkeypatch=None, **overrides) -> Settings:
    if monkeypatch is not None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        monkeypatch.delenv("YOUCAM_API_KEY", raising=False)
    return Settings(
        provider_mode="live",
        supabase_url="https://testproject.supabase.co",
        storage_backend="local",
        local_storage_dir=tmp_path / "storage",
        contracts_dir=CONTRACTS_DIR,
        check_interval_s=0,
        worker_idle_sleep_s=0.01,
        lease_s=60,
        handler_timeout_s=30,
        **overrides,
    )


def test_build_live_providers_no_keys(tmp_path, monkeypatch) -> None:
    settings = _live_settings(tmp_path, monkeypatch)
    detector, generator = build_live_providers(settings)
    assert detector is None and generator is None


def test_build_live_providers_with_keys(tmp_path) -> None:
    settings = _live_settings(
        tmp_path, gemini_api_key="gem-key", youcam_api_key="yc-key", gemini_model="gemini-9.9-pro"
    )
    detector, generator = build_live_providers(settings)
    assert isinstance(detector, GeminiDetectionProvider)
    assert isinstance(generator, YouCamGenerationProvider)
    assert detector.model == "gemini-9.9-pro"


async def test_live_detect_with_gemini_key(tmp_path, pool, jwks_client, auth, ec_key) -> None:
    settings = _live_settings(tmp_path, gemini_api_key="gem-key")
    detector, generator = build_live_providers(settings)
    assert isinstance(detector, GeminiDetectionProvider)
    deps = AppDeps(
        settings=settings,
        pool=pool,
        store=LocalObjectStore(tmp_path / "storage"),
        detector=detector,
        generator=generator,
        contracts=ContractSchemas(CONTRACTS_DIR),
        verifier=TokenVerifier(settings, JwksCache(settings.supabase_jwks_url, client=jwks_client)),
    )
    app = create_app(deps)
    try:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post(
                detector.base_url + f"/v1beta/models/{detector.model}:generateContent"
            ).mock(return_value=httpx.Response(200, json=GEMINI_ENVELOPE))
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                r = await c.post(
                    "/v1/garments:detect",
                    headers=auth(),
                    files={"frame": ("f.jpg", make_jpeg(640, 480), "image/jpeg")},
                )
        assert route.called
        assert r.status_code == 200
        body = r.json()
        validate_schema("detection_response.schema.json", body)
        assert len(body["persons"]) == 1
        assert body["persons"][0]["garments"][0]["category"] == "upper_body"
        assert body["image_width"] == 640 and body["image_height"] == 480
    finally:
        await aclose_providers(detector, generator)


async def test_live_detect_without_gemini_key(
    tmp_path, pool, jwks_client, auth, monkeypatch
) -> None:
    settings = _live_settings(tmp_path, monkeypatch)
    deps = AppDeps(
        settings=settings,
        pool=pool,
        store=LocalObjectStore(tmp_path / "storage"),
        detector=None,
        generator=None,
        contracts=ContractSchemas(CONTRACTS_DIR),
        verifier=TokenVerifier(settings, JwksCache(settings.supabase_jwks_url, client=jwks_client)),
    )
    app = create_app(deps)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/garments:detect",
            headers=auth(),
            files={"frame": ("f.jpg", make_jpeg(640, 480), "image/jpeg")},
        )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "analysis_unavailable"


def test_worker_build_deps_live_youcam(tmp_path, test_database_url, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = _live_settings(tmp_path, youcam_api_key="yc-key", database_url=test_database_url)
    deps = worker.build_deps(settings)
    assert isinstance(deps.generator, YouCamGenerationProvider)
    assert deps.detector is None
