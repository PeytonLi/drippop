# Handoff: implement DripPop

Prepared October 10, 2026. This is the fresh-agent entry point; no prior conversation is required.

## Read first

**Full authoritative PRD:** [docs/PRD.md](docs/PRD.md)

Read the entire PRD before implementing. It contains the chosen product, complete recommended stack, shared API/state contracts, provider/platform limitations, research sources, acceptance criteria and the user's required three-stage delivery structure. Both this handoff and the PRD are versioned in the public repository.

## Next-session focus

Begin PRD **Stage 1 — Setup** and produce its feasibility evidence and frozen contracts. Then follow its parallel feature lanes and integration/testing gates. The PRD already identifies which tasks can use independent sub-agents, owned paths, dependencies and an execution order for four total concurrency slots.

This session completed research and specification only. A documentation repository has been created; no app, deployment or paid provider trial exists yet. Physical-phone behavior, live provider inputs/fidelity, credentials/billing and runtime limits remain validation gates, not completed checks.

The user's product intent is settled. Preserve the complete same-feed overlay journey and the explicitly requested Three.js stretch requirement. Use the PRD's distinction between approved product intent, recommended implementation choices and unverified feasibility; do not silently drop the stretch or describe it as already solved.

## Repository boundaries

- Work in this repository; create application folders according to the PRD during setup.
- Read [AGENTS.md](AGENTS.md) for the user's working conventions.
- Preserve the research files indexed in PRD section 14. The PRD supersedes provisional findings where stated.
- Keep unrelated projects outside this repository.
- No API keys, credentials or personal photos are included.

## Working instructions

The user's AGENTS.md instructions are reproduced in PRD section 15: use Context7 for current library/API/cloud docs, starting with resolve-library-id, and prefix shell commands with rtk. Use official primary sources when Context7 is unavailable.

The user explicitly requests parallel agents whenever useful. Follow the PRD's ownership boundaries; one coordinator owns shared contracts and integration. Do not concurrently manipulate one phone or coedit shared native/build/API interfaces.

An instruction to read this handoff alone does not establish authorization to spend money, publish or submit the entry. Continue reversible local setup within the new session's authorized task, and resolve missing account/device access while progressing independent work. Never expose credentials or claim unperformed tests passed.

## Suggested skills

- **context7-mcp** — current library, SDK, API and cloud documentation; required by the user.
- **mobile-design** — native overlay, touch, accessibility and permission experience.
- **research** — targeted unresolved provider/3D/competitive questions, with primary-source evidence.
- **tdd** — substantive coordinate/state/auth/idempotency/cancellation logic tests.
- **diagnose** — reproduce and isolate integration failures.
- **handoff** — future session continuity; read its installed SKILL.md when available.

Read relevant skill instructions when applying them. Do not invoke unrelated approval/release workflows merely because they are installed.

## Completion standard

Use the PRD's stage gates and release definition of done. A placeholder overlay or fake-provider flow is progress, not a finished YouCam integration. Record actual hardware/API evidence and preserve remaining limitations.
