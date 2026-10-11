import logging
import time
from typing import Any

import httpx
import jwt

from core.errors import ApiError
from core.logging import log
from core.settings import Settings

_JWKS_TIMEOUT = httpx.Timeout(connect=3, read=5, write=5, pool=3)
_CACHE_TTL_S = 600.0
_REFETCH_MIN_INTERVAL_S = 30.0


def _derived_alg(jwk: dict[str, Any]) -> str | None:
    """The only algorithm a JWK may be used for, derived from its key type."""
    if jwk.get("kty") == "EC" and jwk.get("crv") == "P-256":
        return "ES256"
    if jwk.get("kty") == "RSA":
        return "RS256"
    return None


class JwksCache:
    def __init__(
        self,
        jwks_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.jwks_url = jwks_url
        self._client = client
        self._keys: dict[str, tuple[jwt.PyJWK, dict[str, Any]]] = {}
        self._fetched_at = 0.0
        self._last_refetch = 0.0

    async def _fetch(self) -> None:
        if self._client is not None:
            resp = await self._client.get(self.jwks_url)
        else:
            async with httpx.AsyncClient(timeout=_JWKS_TIMEOUT) as client:
                resp = await client.get(self.jwks_url)
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        keys: dict[str, tuple[jwt.PyJWK, dict[str, Any]]] = {}
        for jwk in body.get("keys", []):
            try:
                key = jwt.PyJWK.from_dict(jwk)
            except (jwt.PyJWTError, KeyError, ValueError, TypeError):
                log("jwks_bad_key", level=logging.WARNING)
                continue
            if key.key_id:
                keys[key.key_id] = (key, jwk)
        self._keys = keys
        self._fetched_at = time.monotonic()

    async def get_key(self, kid: str) -> tuple[jwt.PyJWK, dict[str, Any]] | None:
        now = time.monotonic()
        if not self._keys or now - self._fetched_at > _CACHE_TTL_S:
            try:
                await self._fetch()
            except (httpx.HTTPError, ValueError, KeyError):
                log("jwks_unavailable", level=logging.WARNING)
                if not self._keys:
                    return None
        entry = self._keys.get(kid)
        if entry is None and now - self._last_refetch > _REFETCH_MIN_INTERVAL_S:
            self._last_refetch = now
            try:
                await self._fetch()
            except (httpx.HTTPError, ValueError, KeyError):
                log("jwks_unavailable", level=logging.WARNING)
                return None
            entry = self._keys.get(kid)
        return entry


class TokenVerifier:
    def __init__(self, settings: Settings, jwks: JwksCache | None = None) -> None:
        self.settings = settings
        self.jwks = jwks or JwksCache(settings.supabase_jwks_url)

    async def verify(self, token: str) -> str:
        unauthorized = ApiError(401, "unauthenticated")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise unauthorized from None
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise unauthorized
        entry = await self.jwks.get_key(kid)
        if entry is None:
            raise unauthorized
        key, jwk_dict = entry
        derived = _derived_alg(jwk_dict)
        if derived is None:
            raise unauthorized
        jwk_alg = jwk_dict.get("alg")
        if isinstance(jwk_alg, str) and jwk_alg != derived:
            raise unauthorized
        if header.get("alg") != derived:
            raise unauthorized

        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[derived],
                audience=self.settings.supabase_jwt_audience,
                issuer=self.settings.supabase_jwt_issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
                leeway=30,
            )
        except jwt.PyJWTError:
            raise unauthorized from None

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub or len(sub) > 128:
            raise unauthorized
        return sub
