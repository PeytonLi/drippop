"""Coordinator-run live smoke check against a real Supabase project.

Read-only except a single smoke storage object. Never prints secrets or
key-carrying URLs. Run: uv run python -m core.smoke [--token <access token>]
"""

import argparse
import asyncio
import hashlib
import io
import secrets
from typing import Any

import httpx
import psycopg
from PIL import Image

from core.auth import JwksCache, TokenVerifier
from core.errors import ApiError
from core.settings import Settings
from core.storage import SupabaseObjectStore

APP_TABLES = (
    "jobs",
    "idempotency_records",
    "job_dispatch",
    "budget_days",
    "budget_reservations",
    "usage_counters",
    "stored_objects",
)

_results: list[tuple[str, bool, str]] = []


def _report(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))


async def check_db(settings: Settings) -> None:
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.database_url, prepare_threshold=None
        ) as conn:
            cur = await conn.execute(
                "select relname, relrowsecurity from pg_class c"
                " join pg_namespace n on n.oid = c.relnamespace"
                " where n.nspname='public' and c.relkind='r'"
            )
            rows = {r[0]: r[1] for r in await cur.fetchall()}
            missing = [t for t in APP_TABLES if t not in rows]
            _report("db.tables", not missing, f"missing: {missing}" if missing else "all present")
            no_rls = [t for t in APP_TABLES if t in rows and not rows[t]]
            _report(
                "db.rls_enabled",
                not no_rls,
                f"no RLS: {no_rls}" if no_rls else "all app tables",
            )
            cur = await conn.execute("select count(*) from pg_policies where schemaname='public'")
            pol_row = await cur.fetchone()
            pol = pol_row[0] if pol_row else 0
            _report("db.zero_policies", pol == 0, f"{pol} policies")
            try:
                cur = await conn.execute(
                    "select public from storage.buckets where id=%s",
                    (settings.storage_bucket,),
                )
                brow = await cur.fetchone()
            except Exception:
                brow = None
            bucket_ok = brow is not None and brow[0] is False
            _report(
                "db.bucket",
                bucket_ok,
                "private" if bucket_ok else "bucket missing or storage schema absent",
            )
    except Exception as exc:
        _report("db.connect", False, exc.__class__.__name__)


def _tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


async def check_storage(settings: Settings, client: httpx.AsyncClient | None = None) -> None:
    store = SupabaseObjectStore(
        settings.supabase_url,
        settings.supabase_secret_key,
        settings.storage_bucket,
        client=client,
    )
    path = f"smoke/{secrets.token_urlsafe(8)}.png"
    try:
        data = _tiny_png()
        await store.put(path, data, "image/png")
        got = await store.get(path)
        await store.delete(path)
        try:
            await store.get(path)
            gone = False
        except Exception:
            gone = True
        _report("storage.roundtrip", got == data and gone, "put/get/delete ok")
    except Exception as exc:
        _report("storage.roundtrip", False, exc.__class__.__name__)


async def check_jwks(settings: Settings, client: httpx.AsyncClient | None = None) -> None:
    try:
        if client is not None:
            resp = await client.get(settings.supabase_jwks_url)
        else:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as c:
                resp = await c.get(settings.supabase_jwks_url)
        resp.raise_for_status()
        keys: list[dict[str, Any]] = resp.json().get("keys", [])
        algs = sorted({k.get("alg", "?") for k in keys})
        kids = [k.get("kid", "?") for k in keys]
        _report("jwks", len(keys) >= 1, f"algs={algs} kids={kids}")
    except Exception as exc:
        _report("jwks", False, exc.__class__.__name__)


async def check_token(
    settings: Settings, token: str, client: httpx.AsyncClient | None = None
) -> None:
    try:
        verifier = TokenVerifier(settings, JwksCache(settings.supabase_jwks_url, client=client))
        sub = await verifier.verify(token)
        prefix = hashlib.sha256(sub.encode()).hexdigest()[:12]
        _report("auth.token", True, f"sub_hash={prefix}")
    except ApiError:
        _report("auth.token", False, "verification failed")


async def run_smoke(
    token: str | None,
    jwks_client: httpx.AsyncClient | None = None,
    storage_client: httpx.AsyncClient | None = None,
) -> int:
    settings = Settings()
    await check_db(settings)
    if settings.supabase_url and settings.supabase_secret_key:
        await check_storage(settings, client=storage_client)
    else:
        _report("storage.roundtrip", False, "SUPABASE_URL/SECRET_KEY not set")
    if settings.supabase_jwks_url:
        await check_jwks(settings, client=jwks_client)
    else:
        _report("jwks", False, "SUPABASE_JWKS_URL not set")
    if token:
        await check_token(settings, token, client=jwks_client)
    return 0 if all(ok for _, ok, _ in _results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="core.smoke")
    parser.add_argument("--token", default=None)
    args = parser.parse_args()
    import os

    token = args.token or os.environ.get("SMOKE_ACCESS_TOKEN")
    return asyncio.run(run_smoke(token))


if __name__ == "__main__":
    raise SystemExit(main())
