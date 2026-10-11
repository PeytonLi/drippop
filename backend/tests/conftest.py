import json
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from httpx import ASGITransport
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from api.deps import AppDeps
from api.main import create_app
from core.auth import JwksCache, TokenVerifier
from core.contracts import ContractSchemas
from core.db import apply_migrations, make_pool
from core.dispatch import WorkerDeps, drain
from core.settings import Settings
from core.storage import LocalObjectStore
from providers.fake import FakeDetectionProvider, FakeGenerationProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/postgres"
)

SCHEMAS = {p.name: json.loads(p.read_text()) for p in (CONTRACTS_DIR / "schemas").glob("*.json")}

REGISTRY = Registry().with_resources(
    [(s["$id"], Resource.from_contents(s)) for s in SCHEMAS.values()]
    + [(name, Resource.from_contents(s)) for name, s in SCHEMAS.items()]
)


def validate_schema(name: str, doc: Any) -> None:
    Draft202012Validator(SCHEMAS[name], registry=REGISTRY).validate(doc)


@pytest.fixture(scope="session")
def test_db_name() -> str:
    return f"drippop_test_{secrets.token_hex(6)}"


@pytest.fixture(scope="session")
def test_database_url(test_db_name, tmp_path_factory):
    admin = TEST_DATABASE_URL
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'create database "{test_db_name}"')
    except psycopg.OperationalError as exc:
        pytest.fail(f"test postgres unreachable at {admin}: {exc}")
    db_url = admin.rsplit("/", 1)[0] + "/" + test_db_name
    import asyncio

    asyncio.run(apply_migrations(db_url, MIGRATIONS_DIR))
    yield db_url
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'drop database "{test_db_name}" with (force)')


@pytest.fixture
async def pool(test_database_url):
    async with await psycopg.AsyncConnection.connect(test_database_url, autocommit=True) as conn:
        await conn.execute(
            "truncate jobs, idempotency_records, job_dispatch, budget_days,"
            " budget_reservations, usage_counters, stored_objects restart identity cascade"
        )
    p = make_pool(test_database_url)
    await p.open()
    yield p
    await p.close()


# --- JWT helpers -------------------------------------------------------------


@pytest.fixture(scope="session")
def ec_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk_from_private(priv, kid: str) -> dict:
    pub = (
        jwt.algorithms.ECAlgorithm.to_jwk(priv.public_key())
        if isinstance(priv, ec.EllipticCurvePrivateKey)
        else jwt.algorithms.RSAAlgorithm.to_jwk(priv.public_key())
    )
    jwk = json.loads(pub)
    jwk["kid"] = kid
    jwk["use"] = "sig"
    return jwk


@pytest.fixture(scope="session")
def jwks_doc(ec_key, rsa_key):
    return {
        "keys": [
            _jwk_from_private(ec_key, "ec-kid"),
            _jwk_from_private(rsa_key, "rsa-kid"),
        ]
    }


@pytest.fixture
def jwks_client(jwks_doc):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=jwks_doc)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


ISSUER = "https://testproject.supabase.co/auth/v1"
AUD = "authenticated"


def make_token(
    sub: str = "user-" + uuid.uuid4().hex[:12],
    *,
    priv=None,
    kid: str = "ec-kid",
    alg: str = "ES256",
    iss: str = ISSUER,
    aud: str = AUD,
    exp_offset: int = 3600,
    secret: str | None = None,
) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "exp": now + exp_offset,
        "iat": now,
        "role": "authenticated",
    }
    if alg == "HS256":
        return jwt.encode(claims, secret or "", algorithm="HS256", headers={"kid": kid})
    assert priv is not None
    return jwt.encode(claims, priv, algorithm=alg, headers={"kid": kid})


@pytest.fixture
def settings(tmp_path):
    return Settings(
        provider_mode="fake",
        supabase_url="https://testproject.supabase.co",
        local_storage_dir=tmp_path / "storage",
        contracts_dir=CONTRACTS_DIR,
        check_interval_s=0,
        worker_idle_sleep_s=0.01,
        lease_s=60,
        handler_timeout_s=30,
    )


@pytest.fixture
def fake_detector():
    return FakeDetectionProvider()


@pytest.fixture
def fake_generator():
    return FakeGenerationProvider()


@pytest.fixture
async def deps(settings, pool, tmp_path, jwks_client, fake_detector, fake_generator):
    verifier = TokenVerifier(settings, JwksCache(settings.supabase_jwks_url, client=jwks_client))
    d = AppDeps(
        settings=settings,
        pool=pool,
        store=LocalObjectStore(tmp_path / "storage"),
        detector=fake_detector,
        generator=fake_generator,
        contracts=ContractSchemas(CONTRACTS_DIR),
        verifier=verifier,
    )
    return d


@pytest.fixture
async def app(deps):
    return create_app(deps)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def auth(ec_key):
    def _headers(sub: str | None = None) -> dict[str, str]:
        token = make_token(sub or "user-" + uuid.uuid4().hex[:12], priv=ec_key)
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
def uid() -> str:
    return "user-" + uuid.uuid4().hex[:12]


def make_jpeg(w: int = 800, h: int = 1000, color=(120, 80, 200)) -> bytes:
    import io

    from PIL import Image

    im = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def make_png(w: int = 800, h: int = 1000, color=(30, 160, 90, 255)) -> bytes:
    import io

    from PIL import Image

    im = Image.new("RGBA", (w, h), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def job_form(
    person: bytes | None = None,
    reference: bytes | None = None,
    metadata: dict | None = None,
) -> dict:
    return {
        "files": {
            "person_photo": ("person.jpg", person or make_jpeg(), "image/jpeg"),
            "reference_photo": (
                "ref.jpg",
                reference or make_jpeg(600, 800, (200, 60, 60)),
                "image/jpeg",
            ),
        },
        "data": {"metadata": json.dumps(metadata or {"garment_category": "upper_body"})},
    }


def idem_headers(auth_headers: dict[str, str], key: str | None = None) -> dict[str, str]:
    return {**auth_headers, "Idempotency-Key": key or secrets.token_urlsafe(24)}


@pytest.fixture
async def drain_fn(deps):
    async def _drain(max_steps: int | None = None):
        wd = WorkerDeps(
            settings=deps.settings,
            pool=deps.pool,
            store=deps.store,
            generator=deps.generator,
            detector=deps.detector,
            contracts=deps.contracts,
        )
        return await drain(wd, max_steps)

    return _drain
