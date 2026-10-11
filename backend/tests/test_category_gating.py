import pytest

from tests.conftest import idem_headers, job_form


@pytest.mark.parametrize("cat", ["upper_body", "full_body"])
async def test_fake_mode_allowed(client, auth, cat):
    r = await client.post(
        "/v1/jobs",
        headers=idem_headers(auth()),
        **job_form(metadata={"garment_category": cat}),
    )
    assert r.status_code == 202, r.text


@pytest.mark.parametrize("cat", ["lower_body", "shoes", "outer", "auto"])
async def test_fake_mode_rejected(client, auth, cat):
    r = await client.post(
        "/v1/jobs",
        headers=idem_headers(auth()),
        **job_form(metadata={"garment_category": cat}),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "category_unavailable"


async def test_live_mode_category_outside_enabled_422(client, auth, deps):
    deps.settings.provider_mode = "live"
    deps.settings.daily_paid_attempt_cap = 10
    r = await client.post(
        "/v1/jobs",
        headers=idem_headers(auth()),
        **job_form(metadata={"garment_category": "lower_body"}),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "category_unavailable"


async def test_live_mode_with_enabled_category_202(client, auth, deps, fake_generator):
    deps.settings.provider_mode = "live"
    deps.settings.daily_paid_attempt_cap = 10
    deps.contracts.categories["enabled"] = ["upper_body"]
    deps.generator = fake_generator  # stub provider injected
    r = await client.post(
        "/v1/jobs",
        headers=idem_headers(auth()),
        **job_form(metadata={"garment_category": "upper_body"}),
    )
    assert r.status_code == 202, r.text
