# Provider research: Gemini image detection

Research snapshot: 2026-10-11. Context7 was unavailable because its monthly
quota was exceeded; this review used the supplied official Google AI
documentation snapshots in `~/research/`. Citations and model/pricing statements
reflect the sources accessed on 2026-10-11, not an account-specific trial.

## Model and API choice

**Documented facts.** Google lists `gemini-3.8-flash` as stable (September
2026) with structured-output support. Gemini 2.5 model access is restricted to
users who previously used those models. The current endpoint shape is
`POST /v1beta/models/{model}:generateContent` on
`https://generativelanguage.googleapis.com`, authenticated by the
`x-goog-api-key` header. The body uses `contents` with inline image data and
text, plus `generationConfig.responseMimeType`,
`generationConfig.responseJsonSchema`, and
`generationConfig.thinkingConfig.thinkingLevel`.

Google now recommends the Interactions API for new projects, but the same
documentation labels it Beta and subject to breaking changes; its API guide
also says production workloads should continue using `generateContent`.
Interactions store interactions by default (the notes record 55 days for paid
and one day for free). This adapter uses raw HTTP with `generateContent` to
avoid SDK auto-retries and avoid the stateful Interactions API default. This is
an implementation choice based on those documented tradeoffs.

## Request and output handling

The provider sends the image as base64 `inlineData` (`mimeType` plus `data`)
and a prompt asking for each clearly visible person and visible garment.
`box_2d` is requested in `[ymin, xmin, ymax, xmax]` order, integer coordinates
normalized from 0 to 1000 over the whole image. Categories are restricted to
`upper_body`, `full_body`, `lower_body`, `shoes`, and `outer`. Names, identities,
ages, and other personal attributes are explicitly excluded.

The structured response schema constrains persons and each person's garments
to at most eight entries. Structured output guarantees syntax shape only; the
implementation validates every model-provided value. Any malformed or
out-of-range box, zero/inverted area, duplicate person box, duplicate
`(category, box)` within a person, missing garments array, unknown category,
empty result, refusal/block, or non-`STOP` finish returns the contract's empty
manual-selection response. There is no partial salvage, clamping, confidence,
model ID, or model label in adapter output.

Valid boxes convert to the contract's normalized upright `[left, top, right,
bottom]` coordinates by `[xmin/1000, ymin/1000, xmax/1000, ymax/1000]`.
Contract IDs are assigned locally (`p1…pN` and `g1…gM`, with garment IDs
sequential across all persons). Coordinates remain floating-point values in
the inclusive normalized range `[0,1]`; positive box area is enforced
separately from JSON Schema.

The Google image guide documents a 20 MB total inline request limit. The
adapter rejects raw frames larger than 15 MiB before making a request. That
lower raw-byte limit is a conservative implementation bound intended to leave
room for base64 and JSON overhead; Gate 2 must validate model/account behavior
with representative files. No image is written to logs.

## Errors, privacy, cost, and rate limits

**Documented facts.** The REST API can return 400-class input/auth/model
errors, 429 rate/quota errors, and 5xx/availability errors. The official
documentation says the Google GenAI SDK retries by default; using raw HTTPX
keeps this adapter to one bounded upstream request. The adapter maps 429 and
5xx plus transport failures to retryable `DetectionUnavailable`; other
non-2xx responses are nonretryable. A successful but unusable envelope is
retryable, while a valid refusal or malformed model output falls back to
manual selection.

Pricing for Gemini 3.8 Flash is listed as $0.75 per million input tokens and
$3.75 per million output tokens (including thinking tokens) through
2026-12-31, doubling to $1.50 / $7.50 from 2027-01-01. The free tier is listed
as no-cost but says content is used to improve Google's products; paid tier
content is not used that way. **Policy:** use a paid tier before submitting any
real personal frames. The exact account tier, retention, limits, and current
invoice are not established by this code. Rate limits are tier/account specific
and are shown in AI Studio; no fixed model-wide number was found.

## PRD statements now outdated / conflicting

- Firebase/GCP is superseded by decision D-001 (Supabase + Render).
- The current stable model snapshot is `gemini-3.8-flash` (September 2026);
  access to Gemini 2.5 is restricted for new users.
- Google recommends Interactions for new projects, but it is Beta and stores
  interactions by default; Google also advises continuing with `generateContent`
  for production workloads. This adapter uses stateless `generateContent`.
- Gemini's image coordinate convention is normalized integer
  `[ymin,xmin,ymax,xmax]` in `[0,1000]`; DripPop's contract is floating
  `[left,top,right,bottom]` in `[0,1]`. Conversion and semantic checks are
  mandatory.
- Free-tier content-use terms conflict with processing personal photos;
  configure a paid account before any real personal frames are sent.

## Sources and dependency snapshot

All URLs below were accessed 2026-10-11; the source text snapshots are in
`~/research/`.

- [Image understanding and object boxes](https://ai.google.dev/gemini-api/docs/image-understanding)
- [Structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Current models](https://ai.google.dev/gemini-api/docs/models)
- [Gemini 3.8 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [GenerateContent API](https://ai.google.dev/api/generate-content)
- [Interactions API](https://ai.google.dev/gemini-api/docs/interactions)
- [API versions](https://ai.google.dev/gemini-api/docs/api-versions)
- [Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Error codes](https://ai.google.dev/gemini-api/docs/troubleshooting)
- [Google GenAI Python SDK](https://github.com/googleapis/python-genai) (not used)

PyPI snapshot (checked 2026-10-11): `httpx==0.28.1`
([PyPI](https://pypi.org/project/httpx/)), `respx==0.23.1`
([PyPI](https://pypi.org/project/respx/)), `pytest==9.1.1`
([PyPI](https://pypi.org/project/pytest/)), `pytest-asyncio==1.4.0`
([PyPI](https://pypi.org/project/pytest-asyncio/)), `jsonschema==4.26.0`
([PyPI](https://pypi.org/project/jsonschema/)), `ruff==0.17.0`
([PyPI](https://pypi.org/project/ruff/)), and `mypy==2.4.0`
([PyPI](https://pypi.org/project/mypy/)). `google-genai==2.29.0` was researched
but is deliberately not used. No dependency files were changed.
