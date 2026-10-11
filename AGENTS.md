# Agent instructions

Read [HANDOFF.md](HANDOFF.md) and the complete [PRD](docs/PRD.md) before implementing.

## Scope and ownership

- Begin with the PRD's setup gates. Report actual device/provider evidence; mocks do not establish physical feasibility or real YouCam integration.
- Use independent sub-agents for the parallel opportunities specified in the PRD. One coordinator owns shared contracts and integration.
- Freeze interfaces and file ownership before delegation. Do not coedit shared files or manipulate one phone concurrently.
- Preserve the PRD, research and Three.js stretch requirement. Record evidence-backed changes and known limitations.
- Keep secrets, credentials, personal photos and private test data out of this public repository.

## Current documentation — Context7

Use Context7 MCP whenever work involves a library, framework, SDK, API, CLI tool or cloud service, including familiar tools. Prefer it over web search for library documentation.

1. Start with resolve-library-id using the library name and the full question, unless the user provides an exact library ID.
2. Choose the best match by exact name, relevance, snippet coverage, source reputation and benchmark score. Use version-specific IDs when appropriate.
3. Query the selected documentation with the full scoped question.
4. Base implementation on the retrieved docs. If unavailable/incomplete, record the limitation and use official primary sources.

This requirement does not apply to pure refactoring, scripts written from scratch, business-logic debugging, code review or general programming concepts.

## Shell commands — RTK

Prefix shell commands with **rtk**. Examples: rtk git status, rtk rg --files, rtk gh repo view.

Use rtk proxy for unsupported commands that need unfiltered execution. In a command chain, prefix each segment. Prefer rg for file/text searches.

## Verification

Run meaningful checks for changed logic and security/lifecycle boundaries. Use fake providers for repeat/crash/race cases and bounded authorized live trials for actual input/fidelity/latency validation.

End handoffs with completed checks, skipped checks and material unresolved risks.
