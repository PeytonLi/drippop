# Gate 2 — Provider proof plan

**Status: PENDING — no credentials yet.** No live calls, personal photos,
provider spend, or real-provider acceptance evidence are included in this
change. Constructed fixtures and emulators are development evidence only; they
do not pass Gate 2. The Gate 2 requirements follow the provider-proof section
of `docs/PRD.md` and are split into per-category test rows below.

## Test inputs and handling

Prepare a small, repeatable reference set for each category offered:

| Category | Planned reference set | Gate status |
| --- | --- | --- |
| `upper_body` | One public or synthetic front-facing upper-body garment reference; one public or synthetic suitable source frame | **PENDING — no credentials yet** |
| `full_body` | One public or synthetic front-facing full outfit reference; one public or synthetic suitable source frame | **PENDING — no credentials yet** |

Use only public or synthetic images in this evidence plan. Do not add personal
photos to the repository. If separately authorized, consented personal images
must remain under `.local/`, must not be committed, and must not appear in
fixtures, logs, or screenshots. Record source/license and a non-sensitive case
label rather than copying private image data into the report. Emulator/fake
results are useful for development but are not provider evidence.

## Acceptance criteria and measurements

For each category, run the same bounded, serial trial and record one row per
attempt. Do not expand enabled categories based solely on docs or mocks.

| Evidence item | Acceptance / measurement to record | Status |
| --- | --- | --- |
| Route/model/version | Confirm Clothes V4 endpoint, exact category value, File API upload IDs and task-create payload | **PENDING — no credentials yet** |
| Target framing | Record exact source framing and whether V4 accepts it despite the conflicting chest-up/full-body guidance | **PENDING — no credentials yet** |
| Reference suitability | Confirm one front-facing standing wearer, visible face, and full intended clothing region; record garment-detail and identity changes | **PENDING — no credentials yet** |
| Reference acceptance | For each `upper_body` and `full_body` set, record accepted/rejected, provider safe outcome, and any rejection reason | **PENDING — no credentials yet** |
| Units and failed billing | Capture account balance before/after each accepted and rejected attempt; record consumed units and whether failures are billed | **PENDING — no credentials yet** |
| Latency | Capture submit, each poll, completion, download, and end-to-end durations; calculate sample p50/p95 without claiming an SLA | **PENDING — no credentials yet** |
| Status and output expiry | Verify running/success/error lifecycle, output URL expiry, and whether re-querying the task yields a fresh link | **PENDING — no credentials yet** |
| Download hosts | Record exact upload and result hosts and verify HTTPS, host, redirects, and result-download behavior | **PENDING — no credentials yet** |
| Limits and concurrency | Verify account/IP rate-limit response, safe serial cadence, and any account-specific concurrency guidance | **PENDING — no credentials yet** |
| Idempotency/cancel/delete | Record that no such operation was found in the inspected Clothes/File OpenAPI; ask provider/account support before claiming global absence | **PENDING — no credentials yet** |
| Gemini model/output | Confirm available model, paid account tier, normalized box ordering/range, semantic validity, and manual-selection fallback rate | **PENDING — no credentials yet** |
| Gemini model availability | Confirm the configured Gemini model appears in `GET /v1beta/models` for the project key and supports `generateContent`; if `gemini-3.8-flash` is absent, set `GEMINI_MODEL=gemini-3.1-flash-lite` and record it | **PENDING — no credentials yet** |
| Retention/data-use | Record applicable provider retention and account tier/data-use terms; do not send personal frames on Gemini free tier | **PENDING — no credentials yet** |

For visual fidelity, compare only visible source details (color, pattern,
silhouette, and salient features); a single image cannot validate hidden-side
details, exact product identity, or physical fit. Preserve the source reference
and expected outcomes locally under the permissions governing that data. Keep
the repository evidence summary free of personal image bytes.

## Smoke command

Install the optional image reader in the one-off environment, set the required
provider key in the shell, and invoke a single bounded case only after
confirming authorization and available budget. The CLI requires
`--i-accept-cost`, refuses output outside repository `.local/`, caps deadlines
at 600 seconds, polls V4 every 10 seconds, and downloads at most 20 MiB. Do not
run these example commands without valid local input paths and an approved
trial:

```sh
uv run --python 3.12 --with pillow python -m backend.providers.smoke \
  --provider youcam --i-accept-cost \
  --person .local/youcam-source.jpg \
  --reference .local/upper-body-reference.jpg \
  --category upper_body --deadline-s 180 \
  --out .local/youcam-upper-body-result.jpg

uv run --python 3.12 --with pillow python -m backend.providers.smoke \
  --provider gemini --i-accept-cost \
  --frame .local/gemini-frame.jpg --deadline-s 180 \
  --out .local/gemini-detection.json
```

The smoke tool prints only outcomes, safe codes, durations, and downloaded
byte count. Never put keys, task IDs, presigned URLs, or private image data in
the evidence report.

## References

- [PRD Gate 2 — Provider proof](../PRD.md#gate-2--provider-proof), accessed
  2026-10-11.
- [YouCam V4 research snapshot](../research/provider-youcam-v4.md), sources
  accessed 2026-10-11.
- [Gemini detection research snapshot](../research/provider-gemini-detection.md),
  sources accessed 2026-10-11.
