import base64
import hashlib
import hmac
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from core.auth import JwksCache, TokenVerifier
from tests.conftest import AUD, ISSUER, make_jpeg, make_token


async def _verify(settings, client, token):
    verifier = TokenVerifier(settings, JwksCache(settings.supabase_jwks_url, client=client))
    return await verifier.verify(token)


async def test_valid_es256(settings, jwks_client, ec_key):
    sub = await _verify(settings, jwks_client, make_token("u1", priv=ec_key))
    assert sub == "u1"


async def test_valid_rs256(settings, jwks_client, rsa_key):
    sub = await _verify(
        settings, jwks_client, make_token("u2", priv=rsa_key, kid="rsa-kid", alg="RS256")
    )
    assert sub == "u2"


async def _rejects(settings, jwks_client, token):
    from core.errors import ApiError

    with pytest.raises(ApiError) as ei:
        await _verify(settings, jwks_client, token)
    assert ei.value.status == 401


async def test_expired(settings, jwks_client, ec_key):
    await _rejects(settings, jwks_client, make_token("u", priv=ec_key, exp_offset=-100))


async def test_wrong_aud(settings, jwks_client, ec_key):
    await _rejects(settings, jwks_client, make_token("u", priv=ec_key, aud="other"))


async def test_wrong_iss(settings, jwks_client, ec_key):
    await _rejects(settings, jwks_client, make_token("u", priv=ec_key, iss="https://evil/auth/v1"))


async def test_unknown_kid_refetch_then_reject(settings, jwks_doc, ec_key):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=jwks_doc)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await _rejects(settings, client, make_token("u", priv=ec_key, kid="nope"))
    assert calls["n"] >= 1


async def test_alg_none(settings, jwks_client, ec_key):
    token = jwt.encode(
        {"sub": "u", "iss": ISSUER, "aud": AUD, "exp": int(time.time()) + 60},
        None,  # type: ignore[arg-type]
        algorithm="none",
    )
    await _rejects(settings, jwks_client, token)


async def test_hs256_always_rejected(settings, jwks_client):
    await _rejects(
        settings,
        jwks_client,
        make_token("u", alg="HS256", secret="shh"),  # noqa: S106
    )


async def test_rs256_header_against_ec_jwk(settings, jwks_client, rsa_key):
    # Confusion attempt: header says RS256, kid points at an ES256 JWK.
    await _rejects(
        settings,
        jwks_client,
        make_token("u", priv=rsa_key, kid="ec-kid", alg="RS256"),
    )


def _hs256_token(sub: str, secret: bytes, kid: str) -> str:
    # PyJWT refuses asymmetric-key bytes as an HMAC secret, so sign by hand to
    # build the classic RS/HS confusion token anyway.
    def b64(d: bytes) -> bytes:
        return base64.urlsafe_b64encode(d).rstrip(b"=")

    header = {"alg": "HS256", "typ": "JWT", "kid": kid}
    claims = {
        "sub": sub,
        "iss": ISSUER,
        "aud": AUD,
        "exp": int(time.time()) + 60,
        "iat": int(time.time()),
    }
    signing = b64(json.dumps(header).encode()) + b"." + b64(json.dumps(claims).encode())
    sig = hmac.new(secret, signing, hashlib.sha256).digest()
    return (signing + b"." + b64(sig)).decode()


async def test_hs256_with_ec_public_pem_as_hmac_secret(settings, jwks_client, ec_key):
    # Classic RS/HS confusion: HMAC secret = EC public key PEM.
    pem = ec_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    await _rejects(settings, jwks_client, _hs256_token("u", pem, "ec-kid"))


async def test_jwk_alg_mismatch_on_ec_key(settings, jwks_doc, ec_key):
    doc = {"keys": [{**k, "alg": "RS256"} if k.get("kty") == "EC" else k for k in jwks_doc["keys"]]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=doc)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await _rejects(settings, client, make_token("u", priv=ec_key))


async def test_missing_header(client):
    r = await client.get("/v1/jobs/abcdefghijklmnop")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"
    assert r.headers.get("www-authenticate") == "Bearer"


async def test_malformed_header(client):
    r = await client.get("/v1/jobs/abcdefghijklmnop", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


async def test_every_endpoint_requires_token(client):
    form = {"files": {"frame": ("f.jpg", make_jpeg(64, 64), "image/jpeg")}}
    checks = [
        ("POST", "/v1/garments:detect", form),
        ("POST", "/v1/jobs", {}),
        ("GET", "/v1/jobs/abcdefghijklmnop", None),
        ("DELETE", "/v1/jobs/abcdefghijklmnop", None),
        ("GET", "/v1/jobs/abcdefghijklmnop/result", None),
    ]
    for method, url, kwargs in checks:
        r = await client.request(method, url, **(kwargs or {}))
        assert r.status_code == 401, (method, url, r.status_code)
        assert r.json()["error"]["code"] == "unauthenticated"
