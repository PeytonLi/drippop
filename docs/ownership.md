# File ownership (frozen for Stage 1/2)

| Path | Owner | Notes |
| --- | --- | --- |
| `contracts/**`, `docs/decisions.md`, `docs/ownership.md`, `README.md`, `render.yaml`, root `.gitignore` | Coordinator | Lanes request changes in their PR description; never edit directly. |
| `android/**` (Gradle, manifest, `app.drippop.platform.*`) | Lane 1A/2A native | Creates `app.drippop.contract.*` verbatim from contracts/interfaces/android.md. |
| `android/app/src/main/java/app/drippop/ui/**`, `.../data/**` | Lane 2B UI (Stage 2) | Not touched in Stage 1. |
| `backend/api/**`, `backend/worker.py`, `backend/core/**`, `backend/pyproject.toml`, `backend/Dockerfile`, `supabase/**`, `backend/tests/**` (except providers) | Lane 1B/2C backend | Creates `backend/providers/base.py` verbatim from contracts/interfaces/providers.md and `backend/providers/fake.py`. |
| `backend/providers/**` (except base.py, fake.py), `backend/tests/providers/**`, `docs/evidence/gate2-*` | Lane 1C/2D provider | No route/worker/DB edits. Adds deps by requesting them in the PR description. |
| `docs/evidence/gate1-*`, `docs/runbooks/android-*` | Lane 1A native | |
| `viewer3d/**` | Lane 2F (Stage 2, after core 2D gate) | |
