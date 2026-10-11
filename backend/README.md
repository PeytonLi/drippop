# DripPop backend

FastAPI API + Postgres durable worker implementing `contracts/openapi.yaml`.
Public schema is Supabase (Postgres, private storage bucket, Supabase Auth JWTs).

**All results here are fake-provider / local-dev evidence only. No real
Supabase project, YouCam, or Gemini was contacted.**

## Local runbook

```bash
# 1. install uv (0.13.0) and Python 3.12
curl -LsSf https://astral.sh/uv/0.13.0/install.sh | sh
uv python install 3.12

# 2. start Postgres (docker) — or `supabase db start` for the full local stack
docker run -d --name drippop-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:17

# 3. install deps and apply migrations (local/CI/test path only)
cd backend
uv sync
uv run python -m core.db migrate

# 4. run the API and the worker
uv run uvicorn api.main:create_app --factory --reload
uv run python -m worker run        # or: drain [--max-steps N] / reconcile
```

Tests need a reachable Postgres: `TEST_DATABASE_URL` (default
`postgresql://127.0.0.1:5432/postgres`). For a password-protected local
instance like the container above, `export PGUSER=postgres PGPASSWORD=postgres`
so psycopg/libpq supplies the credentials — never put them in the URL.

## Coordinator: live setup and smoke check

Credentials are never committed. With `DATABASE_URL` (pooler URI),
`SUPABASE_URL`, `SUPABASE_SECRET_KEY` exported:

```bash
# Apply migrations to the real project (Supabase CLI runs supabase/migrations)
npx supabase@2.120.0 db push --db-url "$DATABASE_URL"

# Read-only smoke check (writes + deletes one smoke/<rand>.png object)
cd backend
uv run python -m core.smoke --token "$ANON_ACCESS_TOKEN"   # token optional
```

`python -m core.db migrate` is for local/CI/test only — Supabase projects are
migrated with the CLI (`db push` / `supabase db start` locally).

## Modes

- `PROVIDER_MODE=fake` (default): in-process fake providers; results are
  JPEGs watermarked "FAKE PREVIEW". Categories from
  `categories.json.fake_mode_enabled` (upper_body, full_body) are accepted.
- `PROVIDER_MODE=live`: real adapters. Detect works with `GEMINI_API_KEY`
  set (without it → 503 `analysis_unavailable`). Job creation still needs
  a category enabled in `categories.json` — `enabled` stays empty until
  Gate 2, so generation fails closed — plus `DAILY_PAID_ATTEMPT_CAP > 0`
  and `YOUCAM_API_KEY` (missing key → 503 `service_unavailable`).

## Env vars

| Var | Default | Notes |
| --- | --- | --- |
| PROVIDER_MODE | fake | fake \| live |
| DATABASE_URL | local postgres | psycopg pooler URI |
| SUPABASE_URL | "" | needed for JWKS + supabase storage |
| SUPABASE_JWKS_URL | `${SUPABASE_URL}/auth/v1/.well-known/jwks.json` | |
| SUPABASE_JWT_ISSUER | `${SUPABASE_URL}/auth/v1` | |
| SUPABASE_JWT_AUDIENCE | authenticated | |
| SUPABASE_SECRET_KEY | "" | `sb_secret_…`; sent on `apikey` header only |
| GEMINI_API_KEY | "" | live detect; empty → detect returns 503 |
| GEMINI_MODEL | adapter default | optional override of the Gemini model ID |
| YOUCAM_API_KEY | "" | live generation; empty → jobs return 503 |
| STORAGE_BACKEND | derived | local when fake mode & no secret key |
| LOCAL_STORAGE_DIR | backend/.local-storage | |
| STORAGE_BUCKET | drippop-private | |
| CONTRACTS_DIR | repo/contracts | `/app/contracts` in Docker |
| DAILY_PAID_ATTEMPT_CAP | 0 | project-wide paid attempts/day |
| DETECT_DAILY_CAP_PER_UID / _PROJECT | 200 / 2000 | |
| MAX_IMAGE_BYTES / _SIDE / _PIXELS | 8388608 / 4096 / 16777216 | |
| MIN_GEN_SHORT_SIDE / LONG_SIDE | 384 / 512 | person+reference minimums |
| POLL_AFTER_MS | 3000 | |
| IMAGE_TTL_S / RECORD_TTL_S | 86400 / 2592000 | 24h / 30d |
| JOB_DEADLINE_S | 900 | |
| LEASE_S / HANDLER_TIMEOUT_S | 120 / 60 | timeout must be < lease |
| DISPATCH_MAX_ATTEMPTS | 5 | |
| MAX_CHECKS / CHECK_INTERVAL_S | 120 / 3 | |
| DETECT_TIMEOUT_S | 20 | |
| MAX_RESULT_BYTES | 15000000 | |
| RECONCILE_INTERVAL_S / WORKER_IDLE_SLEEP_S | 300 / 1.0 | |

## Auth notes (Supabase docs, fetched 2026-10-11)

Supabase signing keys are asymmetric (ES256 P-256 or RS256); public keys at
`GET <project>/auth/v1/.well-known/jwks.json`. The coordinator confirmed on
2026-10-11 that the real DripPop project's JWKS serves a single ES256 key.
We therefore accept only ES256/RS256 via JWKS — HS256/legacy-JWT-secret
fallback was removed and HS256 tokens are always rejected. Claims:
`iss=https://<ref>.supabase.co/auth/v1`, `aud=authenticated`, `sub`=owner_uid.
New `sb_secret_` keys are not JWTs and go on the `apikey` header (never
`Authorization: Bearer`). Sources:
supabase.com/docs/guides/auth/signing-keys, /auth/jwts (jwt-fields),
/guides/api/api-keys (getting-started + migrating-to-new-api-keys).

## Failure modes

- `submission_unknown`: any ambiguous submit outcome (SubmitAmbiguous,
  timeout, crash after the submission marker) → public failed
  `generation_status_unknown`, reservation kept, never auto-resubmitted.
- Lease/fencing: every commit after an external call re-locks the dispatch
  row by lease token and requires `jobs.phase_version` to match; a lost
  lease discards the result (late provider output is deleted, not published).
- Cleanup dispatches delete `stored_objects` rows from the store; exhausted
  cleanup dispatches are reset (attempts=0, +1h) — they keep retrying.
- `python -m worker reconcile` (also every RECONCILE_INTERVAL_S in `run`):
  deadline timeouts, exhausted dispatches, expired jobs → cleanup enqueue,
  record purge at 30d, orphan objects >1h under `jobs/`.

## Pinned versions

Sources: PyPI JSON API + GitHub releases, checked 2026-10-11. Context7 monthly
quota was exhausted on 2026-10-11, so official primary docs were used
(PyPI, Pillow docs reference/Image.rst, psycopg docs advanced/prepare.rst,
Starlette docs requests.md, FastAPI docs, httpx docs, Supabase docs listed
above, astral.sh uv releases, supabase CLI releases).

uv 0.13.0 · Python 3.12 · fastapi 0.143.0 · uvicorn[standard] 0.54.0 ·
httpx 0.28.1 · pillow 12.3.0 · psycopg[binary] 3.3.6 · psycopg-pool 3.3.3 ·
pydantic 2.14.0 · pydantic-settings 2.15.0 · pyjwt[crypto] 2.15.1 ·
cryptography 50.0.2 · python-multipart 0.0.32 · jsonschema 4.26.0 ·
referencing 0.37.0 · dev: pytest 9.1.1, pytest-asyncio 1.4.0, ruff 0.17.0,
mypy 2.4.0, pyyaml 6.0.3 · Supabase CLI 2.120.0 · postgres 17 (docker).
