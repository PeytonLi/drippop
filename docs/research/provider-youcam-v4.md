# Provider research: YouCam Clothes V4

Research snapshot: 2026-10-11. Context7 was unavailable because its monthly
quota was exceeded; this review used the supplied primary-source snapshots in
`~/research/` and the linked official provider references. Facts below describe
those sources as accessed on 2026-10-11; they are not live integration evidence.

## API, authentication, and task lifecycle

**Documented facts.** The Clothes V4 OpenAPI bundle identifies
`https://yce-api-01.makeupar.com` and Bearer API-key authentication. The V4
task endpoint is `POST /s2s/v2.0/task/cloth-v4`; its body accepts uploaded
`src_file_id` and `ref_file_id`, `garment_category`, and
`filter_multi_person`. The documented category enum is `full_body`,
`lower_body`, `upper_body`, `shoes`, `auto`, and `outer`. Multi-person filter
values are `off`, `normal`, and `strict`; the adapter defaults to `normal`.

The File API flow is:

1. `POST /s2s/v2.0/file` with `{"files":[{"content_type":"image/jpg"|"image/png","file_name":"…","file_size":N}]}`
   and the API-key Authorization header.
2. Read `data.files[0].file_id` and `requests[0]` from the response.
3. `PUT` the image bytes to the returned presigned URL, sending the exact
   returned request headers and no provider Authorization header.
4. Create one V4 task with the source and reference file IDs.
5. Poll `GET /s2s/v2.0/task/cloth-v4/{task_id}` about every 10 seconds until
   `task_status` is `running`, `success`, or `error`. The success result is
   `data.results.url`.

The File API documents 400 `InvalidParameters` and 401 invalid API-key errors.
Task creation documents 400 `InvalidParameters`, `CreditInsufficiency`,
`InvalidStyleGroup`, `InvalidStyle`, or `BadRequest`; 401 invalid-key and 429
rate-limit responses. Task polling documents 400 `InvalidTaskId`, 401 auth
failure, and 500 `TaskTimeout`. Engine errors include the mapped codes below
and additional/new values; unknown values are not promoted to user-specific
claims.

The file-upload example documents `yce-us.s3-accelerate.amazonaws.com` as a
presigned-upload host. It is used as the initial exact-match upload and output
allowlist; that choice is **an implementation inference from a documented
example**, not proof that all accounts or regions use only that host. Gate 2
must confirm the real upload and result hosts before enabling production use.
Redirect following is disabled. API credentials are sent only to the YCE API
host, never to the presigned upload or result host.

**Coordinator report, not verified by this lane (2026-10-11).** The coordinator
reports that a Bearer API key alone worked, with no secret-key/RSA flow; the
V4 endpoints were confirmed; and `GET /s2s/v2.0/task/template/cloth` returned
200 without spending units. These are account-specific report items, not
evidence independently obtained by this provider lane, and must not be treated
as a general provider guarantee.

## Input requirements, categories, and output

**Documented facts.** The image guidance specifies JPEG/PNG below 10 MB,
recommended 1024×768, minimum 512×384, and maximum side 4096 pixels. The guide
describes a single-person source image, clearly visible face and clothing,
forward-facing/standing pose, and a wearer or front-facing single-garment
reference. Standalone lower-body product photos are called unsupported; pants
should be shown on a person. The V4 API processes one category at a time.
Clothes task IDs and files have a documented 30-day retention period on the
retention page, but the V4 schema says a task ID is queryable for 24 hours
(conflict details below). Result URLs are described as valid for two hours;
the retention guide says to query the task again to obtain a fresh URL.

The adapter enforces the strict `<10 MiB` byte boundary and maximum side of
4096 before any upload. **That exact byte interpretation is an implementation
choice** based on the documented limit. It does not enforce minimum dimensions
or photo composition because those checks require additional validation or
visual judgement. A timeout or uncertain task-create response is treated as
ambiguous and must not be automatically resubmitted by the worker.

Mapped engine failures include pose/face/reference/source/region/multi-person,
shoulder/angle/ratio, size, file-size, and decode errors; the adapter maps these
to `unsupported_reference`. Other or future provider error strings fail closed
to `provider_rejected`. Upload-stage errors happen before paid task creation
and are reported as definite rejection. Task-create 5xx, redirects, and
unparseable success responses are ambiguous because the upstream may have
accepted a paid task.

## Units, pricing, limits, retention, and hooks

**Documented facts.** The Clothes bundle unit table lists V2 and V3 at two
units but omits V4. The September 2026 V4 announcement says two units per
generated image. The August 2026 pricing article lists 500 units at $24/month
or $27.50 pay-as-you-go, and a free account with 40 trial units. These are
published figures, not a current account quote. The developer rate-limit
page says 250 requests per 300 seconds per IP and per access token (about five
requests/second) and documents 429 responses.

**Derived, not quoted pricing.** Those dated 500-unit package prices imply
about $0.096 or $0.11 for a two-unit V4 generation, respectively. This is only
an arithmetic estimate from the published package examples, not a current
checkout quote, failed-attempt policy, or complete per-preview cost.

The webhook documentation uses Standard Webhooks headers (`webhook-id`,
`webhook-timestamp`, and `webhook-signature` with `v1` HMAC-SHA256) and a
payload containing `task_id` and `task_status`. Webhooks are not used here:
they require a publicly reachable endpoint, whereas this adapter runs bounded
polling under worker-owned deadlines. The adapter itself does not retry or
cancel tasks.

**Inference / conservative handling.** Since failed-attempt billing is not
settled by the cited materials, Gate 2 records unit balances before and after
each attempt rather than assuming failed tasks are free. Serial trials below
the published rate cap are a conservative test procedure, not a provider
concurrency guarantee. Re-querying a retained task for a new result link is
documented; whether repeated polling or retries incur units must still be
measured.

## PRD statements now outdated / conflicting

- Firebase/GCP architecture is superseded by D-001: Supabase and Render are
  the selected backend platform.
- The API host in the inspected Clothes bundle is
  `yce-api-01.makeupar.com`.
- Task-ID validity conflicts: the Clothes schema says 24 hours; the retention
  page says 30 days. Preserve task IDs only as backend data and verify the
  actual query window in Gate 2.
- Result URLs are valid for two hours; treat them as short-lived and copy the
  bytes into app-controlled storage promptly.
- The bundle unit table omits V4, while the V4 announcement says two units per
  image. Confirm actual unit consumption from account balances.
- A free account is documented as receiving 40 trial units. Availability and
  terms can change and must be checked in the account.
- `filter_multi_person` was added in v1.15 (2026-08-26); `outer` was added in
  v1.14.1 (2026-08-06).
- Webhooks are available, but are not used by this adapter because a public
  endpoint is not part of this work.
- The published rate limit is 250 requests per 300 seconds per IP and per
  token; account-specific enforcement remains unmeasured.
- Target-image guidance conflicts: the integration guide says high-resolution
  full-body, while another target-image table says chest-up/upper-body only.
  Do not claim either framing is accepted by V4 until Gate 2 evidence exists.
- No idempotency, cancel, or delete operation was found in the inspected
  Clothes and File OpenAPI bundles. This is an absence in those inspected
  interfaces, **not proof that no other product-level support exists**.

## Sources and dependency snapshot

All URLs below were accessed 2026-10-11. Primary-source snapshots are preserved
under `~/research/`.

- [Clothes V4 API guide](https://docs.perfectcorp.com/reference/ai_clothes)
- [Clothes OpenAPI bundle](https://docs.perfectcorp.com/_bundle/reference/ai_clothes.json?download=)
- [File OpenAPI bundle](https://docs.perfectcorp.com/_bundle/reference/file.json?download=)
- [Error codes](https://docs.perfectcorp.com/develop/error_codes)
- [Rate limit](https://docs.perfectcorp.com/develop/rate_limit)
- [Webhook guide](https://docs.perfectcorp.com/develop/webhook)
- [File retention period](https://docs.perfectcorp.com/develop/file_retention_period)
- [V4 announcement](https://www.perfectcorp.com/business/blog/ai-clothes/ai-clothes-try-on-api-v4-outerwear)
- [Published API pricing](https://www.perfectcorp.com/business/blog/ai-clothes/virtual-try-on-api-pricing)
- [Live API pricing](https://yce.perfectcorp.com/ai-api/api-pricing)
- [API terms](https://www.perfectcorp.com/perfectbeauty/youcam/terms-of-service-api)
- [API privacy policy](https://www.perfectcorp.com/perfectbeauty/youcam/privacy-policy-api)

PyPI snapshot (checked 2026-10-11): `httpx==0.28.1`
([PyPI](https://pypi.org/project/httpx/)), `respx==0.23.1`
([PyPI](https://pypi.org/project/respx/)), `pytest==9.1.1`
([PyPI](https://pypi.org/project/pytest/)), `pytest-asyncio==1.4.0`
([PyPI](https://pypi.org/project/pytest-asyncio/)), `jsonschema==4.26.0`
([PyPI](https://pypi.org/project/jsonschema/)), `ruff==0.17.0`
([PyPI](https://pypi.org/project/ruff/)), and `mypy==2.4.0`
([PyPI](https://pypi.org/project/mypy/)). These are verification pins only;
dependency-file changes are outside this task's ownership.
