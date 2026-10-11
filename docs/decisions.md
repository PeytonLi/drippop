# Decision log

Coordinator-owned. Each entry: decision, evidence, impact, owner. PRD v1.1 remains authoritative except where superseded here.

## D-001 · Backend platform: Supabase + Render (supersedes PRD §4 Firebase/GCP baseline)
- **Decision (user, 2026-10-11):** Supabase Auth (anonymous sign-in), Supabase Storage (private bucket) and Supabase Postgres replace Firebase Auth, GCS and Firestore. Render hosts the FastAPI web service and a background worker (one container, two start commands, `render.yaml`). Cloud Tasks / Cloud Run / Secret Manager are dropped.
- **Durable dispatch replacement:** a Postgres `job_dispatch` queue drained by the Render worker with `SELECT … FOR UPDATE SKIP LOCKED`, `phase_version`, lease token/expiry and bounded attempts. Job state and its next dispatch row commit in **one transaction**, which removes the PRD §5.4(1) Firestore/Tasks non-atomic crash window. All other §5.4 invariants still apply: one bounded external operation per handler, external calls outside transactions, budget reservation + submission marker before paid submit, `submission_unknown` with no auto-resubmit, eligibility re-check before publishing output, capped timeouts/attempts/lifetime, a maintenance/reconcile command.
- **Auth:** backend verifies Supabase access tokens (JWKS for asymmetric signing keys; legacy HS256 secret only if the project still uses it — lane 1B confirms via Context7). `owner_uid = sub`; anonymous users are allowed but must be authenticated.
- **Data access:** backend connects to Postgres directly (pooler connection string, psycopg 3) for transactions; RLS enabled on every app table with **no** anon/authenticated policies; the bucket is private and only the backend (secret key) reads/writes it. Clients never touch tables or storage.
- **Costs/limits:** Render background workers have no free plan (smallest `0.5c-512mb`, $7/mo per render.com/pricing, checked 2026-10-11); free web services cold-start. No paid resource is created without the user's go-ahead.
- **Impact:** public API (contracts/openapi.yaml) unchanged except the bearer token issuer. PRD §4/§5.3/§5.4 references to Firestore/GCS/Tasks read as the Postgres/Storage equivalents above.

## D-002 · Toolchain pins (initial)
- Backend: Python 3.12, FastAPI, Uvicorn, HTTPX, Pillow, psycopg 3, pydantic v2, pytest; managed with `uv` (`backend/pyproject.toml` + `uv.lock`). Exact versions pinned by lane 1B from current docs.
- Android: Kotlin + Compose, minSdk 34, compileSdk/targetSdk 36 (stable), AGP/Kotlin/BOM pinned by lane 1A from current docs; supabase-kt for anonymous auth; OkHttp for the API.
- Local DB: Supabase CLI (`supabase/` at repo root, migrations in `supabase/migrations/`).

## D-003 · Categories fail closed
`contracts/config/categories.json` `enabled` is empty until Gate 2 evidence passes per category. `fake_mode_enabled` lets fake-provider flows exercise upper_body/full_body. Outside fake mode, a non-enabled category returns 422 `category_unavailable`.

## D-004 · Contract additions beyond PRD §5.1
- Error codes added: `unauthenticated` (401), `not_found` (404), `invalid_request` (400/422), `category_unavailable` (422), `service_unavailable` (503).
- `GET /v1/jobs/{id}/result`: 409 `job_canceled`/not-ready, 410 `result_expired`.
- `job_id` is opaque URL-safe 16–64 chars; `Idempotency-Key` URL-safe 16–128 chars.
- JSON Schema cannot express box ordering/positive area or unique IDs: every consumer must also reject `contracts/fixtures/semantic_invalid/*`.

## D-005 · Tooling deviations from AGENTS.md
- `rtk` is not installed on Devin VMs; commands run unprefixed.
- Context7 MCP was installed for the org on 2026-10-11 and is used for library docs.
