# DripPop — Product Requirements Document

Version 1.1 · Prepared October 10, 2026 · Public repository edition · Android-first hackathon MVP

**Purpose:** This document is the complete product and engineering brief for a fresh implementation agent. It contains the intended experience, recommended stack, contracts, phased work, research findings, validation gates and references. No previous conversation is required.

**Status:** Specification ready for implementation planning; physical-device feasibility and real-provider validation remain open. The repository contains research and documentation; no app has been implemented or deployed. DripPop is the selected project name.

## 0. Start here

Read this PRD fully, then begin **Stage 1: Setup**. Prove the native Instagram overlay with a placeholder image before investing in the complete AI pipeline. Resolve the provider-input gates using a few consented, suitable fixtures. Freeze the client, backend and provider contracts before feature agents implement against them.

Implement the application in this repository. Its current contents are documentation; create the Android/backend implementation folders during setup. Keep any unrelated projects outside this repository. A Git repository is now established; do not assume application code or cloud resources already exist.

This PRD takes precedence over provisional recommendations in earlier research notes. Preserve those notes as reference material. Record any necessary change to this baseline in a short decision log with the supporting evidence, its impact and the owner. A fresh agent should ask for genuinely missing information while continuing independent work; it should not reopen the settled product concept.

### User decisions and engineering baseline

| Item | Decision and authority |
| --- | --- |
| Core experience | User-selected: a tool over a social app captures the currently visible outfit and shows a personal try-on in an expanded overlay over the same app. |
| Initial host | Native Instagram on Android. Other apps require individual testing before compatibility claims. |
| Activation | Floating Try on button plus a Quick Settings tile. Ordinary third-party triple-power-click activation is excluded from the baseline. |
| Personal model | A suitable user photo chosen once during onboarding, stored privately on the device and temporarily uploaded for generation. |
| MVP rendering | A realistic generated 2D image through YouCam Clothes V4. A still frame represents a reel. |
| Three.js | Explicit user-requested stretch feature: rotatable 3D personal preview inside the expanded overlay. It must remain in the plan, with separate asset/reconstruction feasibility gates. |
| Delivery organization | User-required: setup, features implemented in parallel, then integration and testing. Identify opportunities for sub-agents, dependencies and ownership. |
| Technical baseline | Recommended: Kotlin/Compose, FastAPI, Gemini localization, YouCam V4, Firebase Auth, Firestore, private GCS, Cloud Tasks and Cloud Run. These are design choices, not evidence of an existing integration. |

## 1. Product and user value

A person scrolling Instagram sees clothing they like but cannot quickly judge its appearance on themselves. The current workflow often requires saving or screenshotting the post, leaving the feed, opening another product, uploading an image and finding the clothing again.

The product lets that person tap a floating button, select the intended person and garment, and see a personal appearance preview while Instagram remains underneath. The preview helps decide whether a look is worth pursuing. The consumer/eCommerce value is reducing the effort between social discovery and personal evaluation. Product search, checkout and inventory are not necessary to demonstrate this value.

Primary user: a consenting adult Android user exploring clothing from social posts or reels. The first demo uses the entrant's own or otherwise authorized reference content and consented personal photos.

Suggested positioning: **“Turn the outfit in your feed into a personal preview without breaking your scroll.”** This is an execution and convenience claim. Research found close precedents; do not call the product the first such app or promise worldwide novelty.

### What “inside Instagram” means

The floating button, captured-frame selection, progress and completed preview are application-overlay windows above native Instagram. Instagram remains the underlying app; the product does not modify Instagram's post, own its UI or obtain its original media asset. It cannot guarantee Instagram preserves playback position or other internal state.

First-time onboarding, Android settings and system capture-consent dialogs may open separately. Once a capture session is authorized, individual selection, generation progress and result display must stay in the overlay without opening a result Activity, browser tab or separate try-on screen.

### Core journey

1. Open the app once. Read the capture/photo explanation, select a suitable personal photo with the system Photo Picker, and grant display-over-other-apps permission.
2. Add the Quick Settings tile. Start a session through the app or tile and complete Android's capture-consent flow. Prefer selecting Instagram as the captured app when available.
3. Browse Instagram. On a desired post, or a paused/clear reel frame, tap **Try on**.
4. Capture one fresh still. Expand the overlay and freeze that reference. Analyze that deliberately captured frame, highlight candidate people/garments, and allow manual correction.
5. Confirm one wearer/reference region and one supported category, then tap **Generate preview**. Retain enough of the wearer image for the provider's requirements.
6. Show clear progress stages. The user may collapse the panel and continue scrolling. Cloud generation continues independently.
7. Retrieve the completed image through the authenticated API and display it in the expanded overlay. Offer source/preview comparison, collapse, another capture, and delete/cancel.
8. Stop the session through the tile, panel or capture notification. Remove overlay windows and release capture resources. A retained job can be recovered on a later explicit entry.

## 2. Scope

### Required MVP

| ID | Feature | Required behavior |
| --- | --- | --- |
| M01 | Onboarding and photo management | Explain capture, off-device processing and photo requirements; select, replace and delete a private local personal photo. |
| M02 | Session activation | App entry and user-added Quick Settings tile start the consent flow; tile/panel/notification can stop an active session. |
| M03 | Floating UI | Draggable compact Try on button; bounded expandable panel with selection, progress and final preview; scrolling outside its bounds remains possible. |
| M04 | Fresh-frame capture | Capture the visible post/reel still only on explicit action; exclude the product's own UI and respect capture restrictions. |
| M05 | Clothing selection | Provisional automatic localization plus manually adjustable person/reference selection and supported category. |
| M06 | Personal generation | Submit one selected reference and personal photo to real YouCam Clothes V4; asynchronous durable processing. |
| M07 | Same-feed result | Retrieve and display the completed image over native Instagram; show the selected source alongside it through a simple comparison control. |
| M08 | Recovery and cancellation | Retain job ID/idempotency key across connection/process interruptions; resume status without creating a second attempt; hide canceled content locally immediately and retry pending deletion until the server commits its tombstone. |
| M09 | Privacy and spending controls | Authenticate all requests, enforce ownership, keep image storage private, expire/delete objects, bound requests and paid attempts, redact logs. |
| M10 | Demonstrable delivery | Reproducible Android test build, setup instructions, measured quality/latency evidence and a real intended-device demo. |

First supported categories: **upper_body** and **full_body**, only after each passes Stage 1 provider tests. If only one passes, release that category and clearly document the limitation. The exact V4 category vocabulary is full_body, lower_body, upper_body, shoes, auto and outer; **outer** is the documented value. Do not expose untested categories merely because they exist in the API.

“Extract clothing” in this MVP means identify the intended person/category and build a valid reference image for appearance transfer. It does not require reconstructing a flat garment or identifying the exact retail SKU. A garment highlight is distinct from the wearer-preserving image sent to YouCam.

### Stretch features

| ID | Feature | Trigger and limit |
| --- | --- | --- |
| S01 | Three.js 3D preview | Required in the roadmap; implement the bounded viewer experiment after the core 2D loop passes. Full personal/avatar garment reconstruction is a separate feasibility effort. See section 11. |
| S02 | Additional social apps | Test TikTok/Pinterest or another selected app on real devices; publish an explicit compatibility matrix. |
| S03 | More garment categories | Add only after category-specific input and fidelity tests; pants require a suitable on-model reference. |
| S04 | Permanent account linking | Link the anonymous Firebase identity to a user account if cross-device continuity becomes necessary. |

### Out of scope for this MVP

iOS parity; general triple-power-click activation; AccessibilityService or social-account credentials; scraping Instagram or controlling its playback; continuous video transformation; background feed surveillance; physical fit/size prediction; automatic purchase links; multi-garment layering; wardrobe/social features; model training; arbitrary URL ingestion; a merchant catalog; browser-extension delivery.

An unsupported capture must explain the restriction and offer another image/reference, never bypass protection. An iPhone version would require a separately designed import/share flow rather than inheriting the Android overlay promise. [Android restrictions](https://developer.android.com/security/fraud-prevention/activities), [Apple sandboxing](https://support.apple.com/guide/security/security-of-runtime-process-sec15bfe098e/web).

## 3. Functional and interaction requirements

### 3.1 Onboarding

- Use the system Photo Picker and app-private storage. Copy only the selected image; normalize orientation, validate it, and show a suitability checklist. Avoid broad photo-library access.
- Recommend a clear front-facing standing personal photo with the relevant clothing/body region visible. Do not silently promise every target framing: provider documentation contains conflicting chest-up/full-body guidance.
- Explain plainly that tapping Try on sends the selected frame for cloud analysis and confirming generation sends the personal/reference images to cloud providers. Never continuously transmit the feed.
- Handle permission denial/cancellation without loops. Show a user-initiated route back to settings or consent.
- Keep the local profile until replacement/deletion; exclude sensitive images and job data from unintended device backup. Replacement/deletion must remove prior local files.
- Anonymous sign-in supplies an authenticated UID. Clearing app data can lose that identity; anonymous UID alone does not provide cross-device recovery.

[Photo Picker](https://developer.android.com/training/data-storage/shared/photo-picker), [private files](https://developer.android.com/training/data-storage/app-specific), [anonymous authentication](https://firebase.google.com/docs/auth/android/anonymous-auth).

### 3.2 Session and platform behavior

- Use WindowManager TYPE_APPLICATION_OVERLAY with SYSTEM_ALERT_WINDOW permission and a mediaProjection foreground service with current required permissions/service type.
- Obtain fresh system consent for each new MediaProjection session. Do not reuse an old consent token to create another virtual display.
- Resize the existing capture surface/display correctly on captured-content size/rotation changes; release all surfaces, virtual displays, readers and windows on stop.
- Treat screen lock, system stop, another projection, process death and permission revocation as invalidation. Never show a personal photo over the lock screen or silently restart capture.
- App-only capture remains bound to the chosen source even when the foreground app changes. Handle onCapturedContentVisibilityChanged(false): disable capture and hide private preview content until that source is visible again. Tell the user to return to the chosen app or authorize a new session for another source. Do not add AccessibilityService/Usage Access for foreground tracking. [Source visibility callback](https://developer.android.com/reference/android/media/projection/MediaProjection.Callback#onCapturedContentVisibilityChanged(boolean)).
- Initiate consent from a user-launched Activity. Do not rely on unrestricted background foreground-service starts. On Android 15+, the overlay-related background-start exemption requires an already visible overlay where applicable.
- For the tile on Android 14+, use the documented PendingIntent activity-launch route. If locked, require unlock before exposing private preview/setup.
- Keep capture-session lifetime separate from job lifetime. Do not retain a mediaProjection service merely to wait for a cloud job after capture has stopped.
- Host Compose in the overlay with explicit lifecycle/saved-state ownership and dispose its composition when windows are removed. Repeated attach/remove must not leak resources.

[MediaProjection](https://developer.android.com/media/grow/media-projection), [service type](https://developer.android.com/develop/background-work/services/fgs/service-types#media-projection), [background start limits](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start), [tiles](https://developer.android.com/develop/ui/views/quicksettings-tiles), [tile PendingIntent](https://developer.android.com/reference/android/service/quicksettings/TileService#startActivityAndCollapse(android.app.PendingIntent)), [Compose interoperability](https://developer.android.com/develop/ui/compose/migrate/interoperability-apis/compose-in-views).

### 3.3 Capture and selection

- The reference is an immutable fresh frame with pixel width/height, normalized orientation and capture timestamp. Selection stays attached to that still even if the feed moves.
- Prefer app-only capture on the initial Android 14+ target. Verify our overlay is excluded on the real device. If display capture is used, hide the product's windows and discard stale buffered frames before accepting the next fresh frame.
- With full-display fallback, show the frozen frame for explicit source confirmation before transmitting it for analysis; a floating button alone must not cause an unintended app's content to be uploaded.
- Never assume the overlay can pause a reel. Tell the user to pause/select a clear still when necessary.
- Gemini proposes person and garment boxes/categories. Validate every coordinate, category and object ID; reject malformed/out-of-range output. Empty results allow manual selection.
- Manual correction must work without successful Gemini analysis. The user can select the intended person/reference region and category, inspect the crop and choose another frame.
- Associate captures and asynchronous operations with local frame/attempt identifiers and a selection version. Ignore responses belonging to an older frame, superseded selection or canceled attempt; late boxes must never appear on a newer image.
- Separate image coordinates from overlay display coordinates. Mapping must account for density, scaling, letterboxing and rotation. Crop the upright source bytes, not a screenshot of the selection UI.
- Show the garment highlight, but preserve a single wearer's face and the full intended clothing region in the provider reference. Reject or explain seated, side-facing, obstructed and ambiguous multi-person references.

### 3.4 Generation and result

- Debounce repeated taps. Allow one active try-on per UID initially. Create a new idempotency key once per deliberate attempt and persist it before uploading.
- If the create request times out, retry the same bytes/metadata/key; do not generate a new key automatically.
- Use a real YouCam Clothes V4 job for the release demonstration. Keep fixture/fake-provider results clearly marked in developer/demo modes.
- UI phases are preparing, generating and finalizing; do not invent progress percentages or claim instant output.
- Display the result as a personal appearance preview. Provide source/preview comparison so visible garment differences can be inspected.
- Collapse hides the expanded panel and stops phone polling. Server work continues; reopening retrieves the existing job. No push notification is required for MVP.
- Stop removes all capture/overlay UI. A cloud job may continue; an explicit later session/app entry retrieves its retained job ID without resubmitting.
- Cancel/Delete share one backend operation for MVP. Hide local content immediately and persist pending_delete across disconnect/restart; retry DELETE until the server acknowledges its tombstone. Server access is blocked only after that commit. If create acceptance is unknown, recover the job ID with the retained key/inputs, then delete it. An offline tap cannot stop cloud processing immediately; a provider-accepted generation may still finish and consume units.
- Failed/unknown jobs show a plain explanation and an explicit new-attempt action. Ambiguous provider submission must never be retried automatically as a new charged attempt.

### 3.5 Accessibility and overlay interaction

Provide TalkBack labels, 48 dp minimum touch targets, scalable text, clear contrast and dark/light treatment. Provide visible drag, collapse, dismiss and stop actions rather than gesture-only controls. Keep touch interception within the visible bubble/panel bounds; no invisible full-screen overlay may steal Instagram input. Test platform restrictions on touches passing through untrusted overlays. [Touch restrictions](https://developer.android.com/about/versions/12/behavior-changes-all#untrusted-touch-events).

## 4. Recommended full stack

| Layer | Choice | Purpose and reason |
| --- | --- | --- |
| Native client | Kotlin, Jetpack Compose, Android Studio/Gradle | Native permission, foreground-service and cross-app window control; one client language. |
| Prototype OS | Android 14+; minSdk 34 | Initial simplification around contemporary app capture. Choose and pin a compatible installed stable compile/target SDK and toolchain during setup. |
| Overlay/capture | WindowManager, MediaProjection, ImageReader/surface, TileService | Floating interface, explicit authorized frame capture and quick session activation. |
| HTTP client | OkHttp | Authenticated multipart upload, job polling and result streaming with cancellation/timeouts. |
| Local state | App-private files and small preferences/state store | Personal photo and recovery IDs; no Room database needed for this scope. |
| Localization | Gemini Flash family via Python google-genai | Provisional person/garment boxes and category with structured output. Select an available current model and pin it after fixture tests. |
| Generation | YouCam Clothes V4 REST/File API | Sponsor's asynchronous personal clothing appearance transfer. |
| Backend | Python, FastAPI, Uvicorn, HTTPX AsyncClient, Pillow | Auth/API contracts, bounded provider calls, image validation/reencoding and durable workflow coordination. |
| Client identity | Firebase Authentication, initially anonymous | Authenticated UID without signup friction; Firebase Admin verifies tokens server-side. |
| State database | Firestore, server access only | Durable job/idempotency/lease/budget metadata; no image bytes. |
| Image storage | Private Google Cloud Storage | Temporary input/output bytes; authenticated API mediates uploads/downloads. |
| Durable dispatch | Cloud Tasks | Short submit/check/finalize/cleanup handlers, bounded retries, private authenticated worker invocation. |
| Hosting | Public Cloud Run API + private Cloud Run worker | One backend codebase/container with two modes and separate service access. |
| Secrets/observability | Secret Manager, structured Cloud Run/Tasks logs | Provider keys and job-correlated operational evidence without image/token logging. |
| Verification | Android unit/instrumentation tests, Python pytest, provider fixtures | Focused lifecycle, contract, authorization, coordinate and retry validation. |
| 3D stretch | Three.js + local Android WebView content + glTF/GLB | Render supplied avatar/garment assets in the same overlay after feasibility passes. |

Do not introduce Redis/Celery, WebSockets, a SQL database or another account backend. Polling and Cloud Tasks cover the required interaction. Do not substitute FastAPI BackgroundTasks or an in-memory coroutine for durable generation. FastAPI callbacks remain process-local, and Cloud Run instances can be stopped. [FastAPI background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/), [Cloud Run execution/billing](https://docs.cloud.google.com/run/docs/configuring/billing-settings).

Setup needs a billing-enabled Firebase/GCP project, anonymous Auth, Firestore, a private bucket, queue, runtime/task service accounts, IAM, secrets and required APIs. Select compatible nearby resource locations deliberately. Cloud Storage for Firebase now requires Blaze; using a server-managed GCS bucket does not eliminate billed-project requirements. No account, billing configuration, quota or deployment was inspected. [Cloud Run FastAPI setup](https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-fastapi-service), [Tasks setup](https://docs.cloud.google.com/run/docs/triggering/using-tasks), [Storage billing changes](https://firebase.google.com/docs/storage/faqs-storage-changes-announced-sept-2024).

### Architecture

~~~mermaid
flowchart LR
    I[Native Instagram] -->|User-selected still| A[Android capture and overlay]
    A -->|Firebase ID token and image| P[FastAPI on Cloud Run]
    P --> G[Gemini localization]
    P --> F[Firestore job state]
    P --> S[Private image storage]
    P --> Q[Cloud Tasks]
    Q --> W[Private Cloud Run worker]
    W --> Y[YouCam Clothes V4]
    W --> F
    W --> S
    A -->|Poll job and retrieve private result| P
    P -->|Generated image| A
~~~

The Firebase user identity authorizes public API requests. The Google task service identity authorizes worker invocation. They serve different trust boundaries.

## 5. Shared contracts — freeze in Stage 1

The names below are the initial contract. Publish OpenAPI/JSON Schema and matching valid/error fixtures under contracts/ before agents work independently. Changing an endpoint or schema requires the integration owner's approval and a coordinated consumer update.

### 5.1 Public API

All endpoints require **Authorization: Bearer <Firebase ID token>**. Derive owner_uid from verified claims; never accept it from request data. Return 404 for another user's job to avoid exposing its existence.

| Endpoint | Input | Output |
| --- | --- | --- |
| POST /v1/garments:detect | Multipart frame image | 200 validated DetectionResponse. Synchronous bounded analysis; no durable analysis session. |
| POST /v1/jobs | Multipart person_photo, reference_photo, JSON metadata; Idempotency-Key header | 202 JobResponse only after the initial named task exists. Repeated accepted requests return the same job. |
| GET /v1/jobs/{job_id} | Job ID | 200 owner's JobResponse. |
| GET /v1/jobs/{job_id}/result | Job ID | Owner-authorized generated image stream; Cache-Control: no-store. Only succeeded, unexpired, undeleted jobs. |
| DELETE /v1/jobs/{job_id} | Job ID | 202 cancellation/deletion acknowledgment; repeated calls remain safe. |

Detection receives only the explicitly captured frame. Process bytes in memory and do not create an analysis-history collection. The later job uploads the personal photo plus user-confirmed reference; repeating that small upload is acceptable for the prototype.

**DetectionResponse**

~~~json
{
  "image_width": 1080,
  "image_height": 1920,
  "coordinate_space": "normalized_upright_xyxy",
  "persons": [{
    "id": "p1",
    "box": [0.15, 0.12, 0.84, 0.95],
    "garments": [{
      "id": "g1",
      "category": "upper_body",
      "box": [0.22, 0.31, 0.73, 0.60]
    }]
  }],
  "manual_selection_required": false
}
~~~

Boxes are finite floats between 0 and 1, ordered **left, top, right, bottom**, with positive area, against the upright source image. Convert Gemini's documented native box ordering/scale inside the provider adapter. Do not expose model-generated confidence percentages as calibrated probabilities. An empty persons array with manual_selection_required true is valid.

**Generation metadata**

~~~json
{"garment_category": "upper_body"}
~~~

Android creates the wearer-preserving reference crop after confirmation. The backend validates/reencodes every image independently. Metadata cannot contain a UID, arbitrary storage path, provider task ID or remote URL.

**JobResponse**

~~~json
{
  "job_id": "opaque-id",
  "status": "processing",
  "phase": "generating",
  "created_at": "2026-10-10T18:00:00Z",
  "expires_at": "2026-10-11T18:00:00Z",
  "poll_after_ms": 3000,
  "result_available": false,
  "error": null
}
~~~

Public statuses: queued, processing, succeeded, failed, canceled. Public phases: queued, preparing, generating, finalizing; terminal states may retain their last phase. expires_at is the image-access expiry, not a provider retention promise. The server supplies a polling interval; 3 seconds is an initial tuning default, not an API latency guarantee.

Use structured safe errors, for example:

~~~json
{
  "error": {
    "code": "generation_status_unknown",
    "message": "We couldn't confirm this preview. Start a new try-on to try again.",
    "retryable": false
  },
  "job_id": "opaque-id"
}
~~~

Minimum error cases: invalid_image, unsupported_reference, analysis_unavailable, active_job_exists, quota_exceeded, idempotency_conflict, provider_rejected, generation_status_unknown, generation_timeout, result_expired and job_canceled. Map client validation to 400/413/422 as appropriate, invalid auth to 401, key/active-job conflict to 409, quota to 429 and transient service failure to 503. Use 404 for unknown or non-owned jobs. Handle a token refresh with the same request key.

### 5.2 Client states and interfaces

Keep three concepts separate:

| State owner | States/data | Key invariant |
| --- | --- | --- |
| Capture session | off, requesting_consent, active, stopped | A completed job cannot reactivate screen capture. |
| Try-on UI | idle, capturing, analyzing, selecting, uploading, generating, ready, error; frame_id, attempt_id and selection_version | Only responses for the current immutable frame/selection/attempt may update the visible panel. |
| Backend job | queued, processing, succeeded, failed, canceled | Server job persists independently of overlay/process lifetime. |

Agree small interfaces for: captureLatestFrame() returning upright bytes/dimensions/timestamp; session start/stop callbacks; overlay show/collapse/remove; the API client's detect/create/status/result/delete methods. Native agent owns capture-to-display coordinate mapping; UI agent consumes tested mapping helpers rather than implementing a competing crop transform.

Persist the job ID, idempotency key, pending_delete flag and the exact prepared input files until acceptance is known. Keep the current reference private until job expiry or explicit deletion so source comparison can recover; delete it with the result cache. If acceptance is unknown, do not clean the retry bytes before the same-key retry/reconciliation decision. Enforce image-access expiry on every open/resume and remove expired local caches then; a killed app cannot promise physical file deletion at the exact expiry instant.

### 5.3 Backend persistence and provider adapters

Firestore job metadata includes owner_uid, hashed idempotency key, request fingerprint, status/internal_phase, monotonic phase_version, private input/output object paths, provider_task_id, submission-attempt marker, lease token/expiry, pending_dispatch, created/updated/deadline/image-expiry timestamps, safe error code and cancel/delete timestamp.

Hash canonical validated image bytes plus metadata for the request fingerprint. Scope idempotency to UID plus key. Same key/same fingerprint retrieves the same job; changed inputs return 409. Look up an existing same-key request before rejecting for active-job/quota limits so retries recover their own job. New-key creation transactionally claims the UID's active-job slot. Replaying a canceled/deleted attempt during the retained idempotency window cannot generate again. New deliberate attempts receive new keys.

The foundation agent owns job state and retries. The provider agent implements only these agreed adapters:

~~~text
detect(frame) -> DetectionResponse
submit(person, reference, category) -> ProviderTicket
check(ticket) -> pending | succeeded(output_location) | failed(safe_code)
~~~

Submission errors must distinguish definite rejection from an ambiguous upstream acceptance. Provider output locations remain backend-only and must be validated against the provider's expected transport/hosts before downloading. The public API does not accept arbitrary remote URLs.

### 5.4 Durable processing invariants

1. Store the pending initial dispatch and ensure its deterministic named Cloud Task exists before returning 202. Firestore and task creation are not atomic; a same-key retry heals a crash between them.
2. Invoke POST /internal/jobs:advance with job_id, phase and version using the Cloud Tasks Google service account's OIDC token. Restrict worker invocation to that identity. No images, provider keys or user tokens in task bodies.
3. Each handler performs one bounded operation: submit, one status check, finalize, or cleanup. Persist the pending next dispatch, ensure its named task exists, then acknowledge with 2xx.
4. Duplicate/out-of-order delivery checks terminal status, version and lease before acting. An occupied live lease returns a retryable response unless persisted state proves the phase completed and its follow-up dispatch exists; merely failing to claim a lease is not grounds for 2xx. Terminal generation state does not suppress required cleanup work. Cloud Tasks is at least once; named tasks do not establish exactly-once execution.
5. Firestore transactions coordinate state only. External calls run outside transaction callbacks, which may rerun.
6. Before a paid submit, transactionally reserve the project allowance together with the submission marker. If the provider may have accepted but no ticket was durably saved, move to internal **submission_unknown** and a safe public failure. Never automatically resubmit without verified provider-supported idempotency/reconciliation.
7. Save output privately using deterministic naming/preconditions, then commit success only if the job is still eligible. Cancellation must be rechecked; an output arriving after cancellation is deleted rather than published.
8. Cap HTTP timeouts, handler deadlines, retry counts and total job lifetime. Preserve the budget reservation for unknown attempts. Include a bounded private maintenance/reconcile command for stale leases, exhausted retries, abandoned dispatches/files and expiry.

No scheduler is necessary solely for accepted-job delivery if these dispatch invariants hold. A scheduled maintenance run is required before promising unattended public-service cleanup. Storage lifecycle is a secondary orphan-cleanup safeguard, not an exact deletion timer. [Tasks semantics](https://docs.cloud.google.com/tasks/docs/common-pitfalls), [authenticated invocation](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks), [Firestore transactions](https://firebase.google.com/docs/firestore/manage-data/transactions), [object lifecycle](https://docs.cloud.google.com/storage/docs/lifecycle).

## 6. Privacy, validation and operating limits

### Required controls

- Validate Firebase ID tokens and ownership on create/read/download/delete. Deny direct client Firestore access. Server SDKs bypass client Security Rules, so IAM/rules do not replace API ownership checks.
- Keep GCS private. API-mediated streams authorize every download; no public bucket or long-lived bearer result URL. Provider File API upload is preferred; verify the exact V4 source transport during setup.
- Accept JPEG/PNG only for MVP, detect actual format, bound bytes and decoded pixels, normalize orientation and reencode to remove unnecessary metadata. Reject truncated/decompression-bomb inputs. Document stricter internal limits alongside provider limits.
- Apply per-UID and project-wide analysis limits, one transactionally claimed active generation per UID, project-wide paid-attempt limits and bounded queue concurrency. Reserve detection allowance before calling Gemini and retain uncertain charges conservatively. Anonymous identities can be recreated, so UID quotas alone cannot cap spending.
- Only explicitly selected frames/photos may leave the phone. No feed history, contacts, social login, unrelated screenshot archive or raw image logs.
- Logs contain opaque job IDs, safe phase/error codes, durations and unit/budget observations. Never log auth/provider tokens, personal images, raw model responses containing private data or signed URLs.
- Server deletion first tombstones the job and blocks image access, then removes objects with retry. Local deletion hides content immediately but must persist/retry pending_delete until acknowledged. Recheck cancellation around asynchronous writes. Do not resurrect a deleted result after a late provider response.

[Token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens), [Firestore server authorization caveat](https://firebase.google.com/docs/firestore/security/rules-conditions), [Cloud Run secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets).

### Initial policy defaults — implement, then measure

These are proposed product defaults, not vendor guarantees: temporary cloud inputs/results expire after **24 hours**; minimal non-image job/idempotency/budget records persist **30 days**; local personal photo remains until replacement/deletion; locally cached result/reference expires with the job or on deletion. Preserve idempotency/tombstones for that documented 30-day window; never reuse keys. Cleanup retries are monitored and lifecycle catches orphan objects. Confirm these policies against provider/account terms before release.

Default queue concurrency: one paid submission at a time during controlled development, adjustable after measured limits. Start with a deliberately small project-wide daily allowance from redeemed units. Select exact detection/paid-attempt caps, network timeouts and generation deadline in Stage 1 using provider behavior and available budget; until configured, fail closed for public generation. A cloud billing alert is not a hard spending cap.

Performance evidence must report real capture/analysis/generation/total durations, acceptance rate and p50/p95 where the sample supports them. A visible response within 250 ms of tapping the bubble is an initial local-UI target. There is no asserted provider latency SLA; show an honest waiting/retry state when observed deadlines are exceeded.

### Provider privacy findings

Perfect's API terms and privacy policy describe client/generated data as generally retained for **30 days**, with stated exceptions. Improvement use requires explicit agreement; the app owner is described as controller and Perfect as processor for API data. App-side 24-hour deletion cannot promise deletion of provider-held copies. Obtain appropriate input consent and explain this difference in the privacy notice. Confirm Gemini's applicable account/data terms separately before using real personal or third-party frames. [YouCam API terms](https://www.perfectcorp.com/perfectbeauty/youcam/terms-of-service-api), [API privacy policy](https://www.perfectcorp.com/perfectbeauty/youcam/privacy-policy-api).

## 7. Delivery model and parallel-agent rules

Use one integration/coordinator agent and independent feature owners. The user expressly authorizes sub-agents and wants every practical opportunity identified. The current environment has four total concurrency slots: coordinator plus up to three workers. Use waves; do not assume all proposed lanes can run simultaneously.

Recommended project layout, created during setup:

~~~text
drippop/
  android/                 native application
  backend/
    api/                   public routes and auth
    providers/             Gemini and YouCam adapters
    worker.py              durable job advancement
    tests/                 backend/adapter tests
  contracts/               OpenAPI, schemas, shared fixtures
  docs/                    decisions, runbooks, evidence, demo
  viewer3d/                stretch-only viewer/assets
~~~

Ownership is more important than exact folder names. Freeze actual paths before delegation. The coordinator owns shared contracts and integration changes; agents request contract changes rather than concurrently editing the same interface, manifest, Gradle file or deployment configuration. If using Git worktrees, establish a repository and use suitable isolated worktrees after checking local instructions. Do not create user-visible separate chats as a substitute for sub-agents.

Every delegated task must specify owned paths, fixed inputs/contracts, expected artifact, acceptance tests, prerequisites and unresolved questions. Each agent returns a concise handoff listing changes, checks and limitations. Independent searches/tests may run concurrently; physical interaction with the same phone must be scheduled serially.

## 8. Stage 1 — Setup

**Outcome:** a verified native proof, confirmed provider input contract, reproducible skeleton and frozen shared interfaces. This stage is the gate for substantial parallel feature implementation.

### Setup tasks and parallel opportunities

| Lane | Owner / sub-agent opportunity | Tasks | Deliverable |
| --- | --- | --- | --- |
| 1A — Native feasibility | Android platform sub-agent | Inspect current Android docs/toolchain; create isolated minimal Android project; prove permission, foreground capture, tile and bounded overlay over real native Instagram using a placeholder. | Device/build matrix, test notes/video, working native shell and lifecycle findings. |
| 1B — Backend foundation | Backend sub-agent | Inspect credentials/project availability without logging secrets; choose versions/locations; build local FastAPI skeleton and fake-provider path; design auth/storage/tasks IAM and budget configuration. Provision only within separately established implementation authorization. | Reproducible local backend, cloud setup/runbook, failure-mode notes. |
| 1C — Provider and research | Provider/research sub-agent | Fetch current docs with Context7; inspect Clothes V4 OpenAPI, categories, upload/status/output contract and Gemini model/schema support; prepare consented fixtures; perform a bounded live trial only with available authorized credentials/budget. | Exact validated input/response fixtures, measured acceptance/units/latency, open-question log. |
| Shared contract freeze | Coordinator, after findings | Adopt section 5 schemas and platform interfaces, pin compatible versions, decide active categories/limits, record frame transformations, assign file ownership. | contracts/ schemas/fixtures and docs/decisions.md. |

With three workers, lanes 1A/1B/1C can run in parallel after the coordinator establishes safe isolated paths and task boundaries. If a phone, credentials or billing are unavailable, continue useful skeleton/fake-provider work and mark the affected gate pending; do not call it passed.

### Gate 1 — Physical native proof

On a real Android 14+ phone with native Instagram, record phone model, OS/build, Instagram version and tested surfaces:

- Overlay permission grant/deny and capture consent accept/cancel are handled.
- Bubble captures the current post and a chosen reel still; it excludes the product's own UI.
- Placeholder selection/progress/result expand over Instagram; touches outside the visible panel still scroll the feed.
- Rotation/capture resize preserve image geometry and prevent a stale frame.
- Switching away from the selected app disables capture/hides private preview; no hidden or stale Instagram frame is submitted. Returning restores the eligible session UI without bypassing consent.
- Tile, panel and notification stop release resources and remove windows.
- Lock/system stop invalidates capture and requires new consent; no private photo remains visible over the lock screen.
- Protected content fails safely; no bypass is attempted.

An emulator helps development but does not replace this gate. An app-only capture test must establish actual Instagram behavior; do not infer it solely from Android documentation.

### Gate 2 — Provider proof

Test at least one valid upper-body reference and, if offered, one full-body reference using suitable consenting personal photos. Confirm:

- V4 route/model/version, exact category values and source/reference File API or URL transport.
- Accepted target framing despite the documentation inconsistency.
- A wearer reference preserves one front-facing standing person, visible face and entire intended clothing region.
- Real asynchronous status/output handling, output expiry and safe download hosts.
- Visible identity/garment detail, observed time and consumed units.
- Model availability, normalized Gemini boxes and manual selection fallback.
- Failed-attempt billing, concurrency/rate limits, upstream idempotency/reconciliation/cancel/delete support, and applicable provider retention terms.

Some provider questions may remain undocumented. Record the scoped absence and use conservative workflow behavior rather than inventing support. No paid live trials have been made as part of writing this PRD.

### Gate 3 — Development ready

Pin toolchain/dependencies; establish a secret-free example configuration; confirm billing/credits and a concrete trial cap; publish schema fixtures; run the local fake-provider happy path; define test images' permissions and locations; assign owners. If a critical platform/provider gate fails, narrow supported inputs/platform claims and update the PRD before Stage 2.

## 9. Stage 2 — Implementing features in parallel

**Outcome:** independently verified client, backend and provider modules that conform to frozen contracts. Core 2D features remain the critical path.

### Feature lanes and ownership

| Lane | Owner and owned areas | Features | Depends on | Completion evidence |
| --- | --- | --- | --- | --- |
| 2A — Native platform | Android native agent: service/window host/tile/capture, manifest and Gradle | M02/M03 platform host/M04; lifecycle, secure stop, fresh frames, rotation and coordinate mapping. | Gate 1 and client interfaces. | Phone proof plus targeted lifecycle/transform tests; no leaked windows or stale frames. |
| 2B — User interaction | Android UI agent: onboarding/photo selection, pure Compose panels/state, API client integration | M01/M03 UI/M05 selection/M07/M08; accessible selection, comparison, progress, errors and job recovery. | Frozen native/API interfaces; fake services first. | Fake-server flow and UI tests; manual selection and result remain in overlay host. |
| 2C — Backend foundation | Backend agent: API/auth/image validation/state/storage/dispatch/worker/IAM/config | M06 durable workflow/M08/M09; idempotency, ownership, budget, cancellation, cleanup and recovery. | Frozen API and provider interfaces. | Fake-provider happy path and focused authorization/crash/retry tests. |
| 2D — Provider adapters | Provider agent: backend/providers/ plus provider fixtures/tests | Gemini detection and YouCam File/V4 submit/check adapters; schema validation and definite-vs-ambiguous errors. | Gate 2; frozen adapter interface. | Adapter fixture tests and bounded real-provider evidence. No route/worker/IAM edits. |
| 2E — Verification assets | QA agent: dedicated test fixtures, docs/evidence/, contract consumers | Consented difficult frames, acceptance scripts, coordinate/auth/retry scenarios, quality rubric and demo draft. | Frozen schemas; can start fixtures during setup. | Reusable test matrix and expected outcomes, no private photos in public repository. |
| 2F — Three.js stretch | 3D agent: viewer3d/ and isolated documented native viewer interface | S01 known-asset rotatable viewer and reconstruction feasibility report. | Core 2D gate plus section 11 prerequisites. | Real overlay/WebGL2 proof, licensing/asset provenance and graceful 2D fallback. |

### Scheduling with the available slots

**Wave A:** coordinator + 2A native + 2B UI + 2C backend. UI and backend use fakes implementing frozen contracts; no lane waits for completed provider generation to build its module.

**Wave B:** as a lane finishes, replace it with 2D provider and/or 2E QA. The provider adapter can run alongside the backend once the adapter boundary is frozen; if spare capacity exists, start it earlier. The coordinator owns integration of shared files and fixes interface mismatches.

**Wave C:** after the real 2D loop works, optional 2F 3D research/viewer work can run alongside quality refinement and submission documentation. It must not destabilize the release path.

More slots permit more independent lanes, not more editors on the same files. Agents must not independently change common dependencies, endpoint names, job states or crop coordinates. Avoid building two native shells, competing auth systems or an unnecessary generic agent framework.

### Feature acceptance before integration

- Native lane supplies clean frame bytes and reliable start/stop callbacks with repeated attach/remove tested.
- UI lane completes capture-selection-progress-result against fixtures, manually corrects detection and recovers a retained job without resubmit.
- Backend lane authorizes every operation, prevents ordinary duplicate submits, persists pending dispatch and protects cancel/finalize races.
- Provider lane supplies documented good/bad fixtures and reports ambiguous submission explicitly.
- QA lane supplies reproducible cases with clear expected behavior. Fixture-only generation is not evidence of a functioning sponsor integration.

## 10. Stage 3 — Integration and testing phase

**Outcome:** one real capture-to-YouCam-to-overlay loop, verified operational boundaries and a reproducible hackathon submission.

### Integration sequence — one coordinator

1. Wire native capture/session events to the overlay UI with the immutable upright frame and tested transform.
2. Connect Firebase token handling and OkHttp to the frozen API. Run the fake-provider path end to end first.
3. Connect real Gemini localization, preserving manual correction when analysis is empty, invalid or unavailable.
4. Connect the YouCam adapters to the durable worker; execute a small authorized real-image batch.
5. Prove the completed result appears in the panel over the same native Instagram session. Capture a real-device recording.
6. Exercise collapse, reconnect, process restart, stop and resume. Resume by known job/key rather than creating another paid job.
7. Validate cancellation/deletion, object expiry, project budget and the operational runbook; prepare submission artifacts.

### Parallel verification lanes

| Lane | Sub-agent opportunity | Work |
| --- | --- | --- |
| 3A — Native/device | Android QA agent | Real Instagram posts/reels; permission changes; tile, rotation, lock, capture stop, process kill, panel touch bounds and accessibility. Schedule shared-phone use. |
| 3B — Backend/privacy | Backend QA agent | Cross-UID authorization, malformed uploads, idempotency, duplicate/out-of-order tasks, dispatch crashes, ambiguous submit, cancel/finalize races, expiry and quotas. |
| 3C — Fidelity and delivery | Quality/docs agent | Consented image set, acceptance/detail/identity review, latency/unit measurements, compatibility claims, repository setup, judge instructions and demo. |
| Coordinator | Integration owner | Merge findings, repair root causes, update contracts/evidence and decide release gates. |

These lanes can run concurrently after the integrated build is available. Coordinate exclusive phone access; backend/fidelity fixture checks do not need to wait for the physical phone.

### Required test matrix

| Area | Minimum scenarios | Pass condition |
| --- | --- | --- |
| Capture | Post, clear moving/paused reel frame, rotation, app switch, self-overlay contamination, protected surface | Correct fresh still and mapping; no hidden-source upload; safe explicit failure where prohibited. |
| Selection | Multiple people, garments, clutter, blurry/obstructed reference, invalid/empty AI boxes, frame A response after frame B capture | Select intended valid wearer; manual correction remains usable; stale responses are ignored; unsupported reference is explained. |
| Overlay | Expand/collapse/drag, scroll outside bounds, dark/light, large text, TalkBack | Result stays above native Instagram; no invisible touch interception; controls remain usable. |
| Lifecycle | Consent denial, overlay revocation, projection stop, lock, process death, repeated sessions | Release resources, hide private UI and require fresh capture consent; job recovery is independent. |
| Network | Detection timeout, upload response lost, polling offline/reconnect, token refresh | Reuse request key/input on uncertain acceptance; resume known job; no silent new paid attempt. |
| Ownership | Wrong UID reads/downloads/deletes, fabricated job/object path, unauthenticated worker | Access denied without existence leak; private worker accepts only approved service identity. |
| Idempotency | Same UID/key/body repeated at quota; changed body; deleted key; double tap; concurrent different-key creation | Recover the existing attempt before quota rejection; atomically allow one active job; conflict rejected; canceled attempt not regenerated during retained window. |
| Dispatch | Duplicate/out-of-order task, concurrent duplicate plus first-worker crash, state-write/enqueue crash, stale lease | Occupied work is not prematurely acknowledged; retry repairs pending dispatch without a second known submission; cleanup still runs for terminal jobs. |
| Paid uncertainty | Provider accepted then response/ticket save lost | submission_unknown; no automatic resubmit; budget remains reserved. |
| Deletion | Cancel before submit, during generation/output write, while offline or after unknown create acceptance | Hide locally immediately; persist/retry deletion and recover unknown job ID; server blocks access after tombstone; late output deleted; no false upstream-cancel/refund promise. |
| Limits | Oversized/truncated/incorrect-format image, pixel bomb, analysis/job/budget limit | Bounded safe rejection; generation fails closed when budget configuration is absent/exhausted. |
| Generation quality | At least a small varied consented set including each exposed category | Record acceptance, visible garment-detail/identity defects and latency; narrow claims to supported observations. |

Tests should focus on meaningful logic/security/lifecycle boundaries, rather than snapshotting every implementation detail. Use fake providers for crash/duplicate/race tests; reserve real API units for input/fidelity/latency validation.

### Quality evidence

Create docs/evidence/ with a small initial set of approximately ten consented cases if budget allows. Record category/reference framing, acceptance/rejection reason, analysis/queue/generation/total durations, units consumed, visible garment details changed and major identity/body artifacts. Summarize sample size and observed p50/p95 without implying a population-wide SLA.

Judge fidelity against the visible source: color, pattern, silhouette and salient details. Hidden/back-side garment details cannot be verified from one social frame. A result is an appearance preview, not physical fit or exact product identity. Severe defects trigger retry guidance or a narrower supported-input claim, not an “accurate” badge.

### Release definition of done

- All M01–M10 acceptance criteria pass on the documented phone/Instagram version.
- A real YouCam V4 result is generated and displayed in-overlay; the demo identifies the API and does not silently substitute a fixture.
- Required auth, validation, duplicate-task, submission-uncertainty and cancellation checks pass.
- Resource stop/lock behavior and outside-panel touch behavior pass physical-device testing.
- Retention/cleanup defaults, provider retention notice, quotas and project spending configuration are explicit.
- Source/assets/licenses, secret-free configuration, setup/build/runbook and judge testing instructions are complete.
- Known limitations, unsupported categories/apps and measured evidence are documented. Three.js completion is not required for the 2D MVP release.

If phone tests or real provider calls remain unavailable, the result is a prototype awaiting validation, not a completed hackathon build.

## 11. Three.js / 3D stretch specification

The user specifically requested this feature in the PRD. Its intended result is **a rotatable personal avatar wearing the selected look inside the existing expandable overlay**, with the 2D image always available.

### Bounded first experiment

1. Use one licensed, known compatible avatar and garment GLB/glTF asset. Load them into a local Three.js viewer embedded with Android WebViewAssetLoader.
2. Provide drag-to-rotate, a reset view and a 2D/3D control in the panel. Keep overlay collapse/stop reliable and do not intercept feed touches outside the panel.
3. Test current WebGL2 support, real-device startup/interaction/memory and repeated open/close. Pause rendering while hidden; dispose meshes/materials/textures/WebView resources correctly.
4. Fall back to the 2D result if loading/GPU support fails. Package trusted local scripts/assets; restrict navigation and any JavaScript bridge to the smallest necessary interface.
5. Label the asset demo truthfully. A generic avatar demonstrates the viewer, not a personalized reconstruction of this user's body or captured outfit.

Current Three.js WebGLRenderer requires WebGL2; GLTFLoader loads supplied assets. These establish rendering tools, not photo-to-body or photo-to-garment generation. A YouCam 2D result has no documented garment mesh. Mapping a flat result onto a plane is not a rotatable clothing preview. [GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html), [WebGLRenderer](https://threejs.org/docs/pages/WebGLRenderer.html), [local WebView content](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content).

### Personal 3D feasibility gates

Research separately: consented avatar acquisition, body-shape representation, garment geometry/material recovery, hidden-side reconstruction, fitting/rigging/collision, asset licensing, runtime size and mobile performance. One frame cannot measure unseen geometry. Do not select a reconstruction provider or promise arbitrary-outfit 3D until a bounded pipeline demonstrates these steps.

**Stretch acceptance:** viewer remains in-overlay, rotates actual 3D supplied assets, preserves core stop/collapse controls and falls back cleanly. Claim a “personal 3D try-on” only when the avatar and garment are genuinely derived through a validated pipeline. The 3D agent returns working known-asset evidence plus a specific feasibility report for the personalized version.

## 12. Research findings, uncertainties and positioning

### Closest precedents

| Source | Published workflow | Implication |
| --- | --- | --- |
| [OnMe](https://devpost.com/software/onme-h6jmzf) | Android floating bubble, screen capture/drag crop, YouCam Clothes V4; description routes to a verdict page. | Near-exact capture/render precedent. Completed result over native Instagram was not independently established. |
| [Trial Room](https://play.google.com/store/apps/details?hl=en&id=apps.ijp.trial.room) | Screenshots from social/shopping apps plus floating try-on button. | Direct consumer competitor. Listing does not settle exact completed-overlay placement; app was not installed. |
| [OnMee Android](https://www.onmee.org/products/android) | Advertises capture/generation/preview without leaving other apps. | Broader overlay claim already published; download link was not configured when researched. |
| [Anywear](https://devpost.com/software/anywear-ic7ep3) | Social screenshot, Gemini garments, YouCam V4 and draggable personal mirror. | Extraction plus personal transfer is established adjacent work; native cross-app overlay not shown by this description. |
| [Google Circle to Search + Try On](https://blog.google/products-and-platforms/products/search/circle-to-search-february-2026/) | Social-outfit identification, shoppable alternatives and personal preview on supported devices/regions. | Incumbent collision on discovery-to-preview. Direct selected-reference transfer avoids catalog substitution but cannot promise exact hidden details. |
| [Hanger](https://devpost.com/software/hanger-08gvhz) | Browser panel try-on and mobile share/import. | Browser overlays and share flows are adjacent, not proof of arbitrary native-app overlays. |

These are author/vendor claims and primary published descriptions, not hands-on validation or patent clearance. The potential distinction is a demonstrably reliable **complete in-overlay interaction** over native social feeds, with source/result transparency and personal photo reuse. This remains a hypothesis; avoid a “never seen before” claim.

The earlier research also covers Kloset, TryOn, Vanity, TryThisFit and Slidez, plus inconclusive leads. Preserve it for later competitive follow-up. Optional comparator testing can be delegated after feasibility; it does not block the basic build.

### Clothes V4 verified input facts

Official categories are full_body, lower_body, upper_body, shoes, auto and outer. Source/reference support file IDs or accessible URLs. Published input guidance specifies JPG/PNG below 10 MB, longest side at most 4096 px; recommended 1024×768 and minimum 512×384.

A human reference should contain one front-facing standing person, visible unobstructed face and the entire intended clothing region. A product reference should contain a single front-facing garment, not a top/bottom composite. Standalone lower-body product photos are explicitly unsupported; pants need an on-model reference. V4 renders one category at a time; layered outfit/outerwear requires successive renders and is deferred.

No idempotency/cancel/delete operation was found in the inspected Clothes OpenAPI. This means support is undocumented in that inspected source, not proven nonexistent across all provider systems. The target framing table conflicts with full/lower-body examples; live category tests remain necessary. [Clothes guide](https://docs.perfectcorp.com/reference/ai_clothes), [official OpenAPI](https://docs.perfectcorp.com/_bundle/reference/ai_clothes.json?download=).

### Units and dated pricing

The official V4 announcement states **2 units per generated image**. An August 2026 pricing article publishes $24/month or $27.50 pay-as-you-go for 500 units, implying roughly $0.096/$0.11 per successful two-unit render under those packages. These are dated published figures, not verified checkout quotes or a complete per-preview operating cost. Confirm current packages, failed-attempt charges and developer account balance before paid trials. [V4 announcement](https://www.perfectcorp.com/business/blog/ai-clothes/ai-clothes-try-on-api-v4-outerwear), [published pricing](https://www.perfectcorp.com/business/blog/ai-clothes/virtual-try-on-api-pricing), [live pricing](https://yce.perfectcorp.com/ai-api/api-pricing).

Other costs include Gemini, compute, tasks, storage and network. Cloud costs were not estimated. Redeemed free units reduce development cost but do not eliminate abuse controls.

### Open questions and gate owners

| Priority | Uncertainty | Owner / next action | Conservative behavior until resolved |
| --- | --- | --- | --- |
| P0 | Native Instagram capture/overlay/touch/lifecycle on intended device | Native agent, Gate 1 physical proof | Claim only tested device/surfaces; mark gate pending without phone. |
| P0 | Accepted personal/reference framing by category | Provider agent, small real V4 fixture test | Expose only passing categories; preserve wearer rather than tiny garment crop. |
| P0 | Upstream accepted-but-unrecorded submission | Backend + provider agents, investigate idempotency/reconciliation | submission_unknown; no auto-resubmit; retain budget reservation. |
| P0 | Credentials, credits, billing and public generation allowance | Coordinator/account owner, setup | Local fake mode; fail closed for paid requests until configured. |
| P1 | Rate limits, failed-attempt billing, signed-result expiry | Provider agent, docs/account measurements | Bounded serial trial, configurable deadlines, copy output promptly. |
| P1 | Gemini account/model/data-use terms and box reliability | Provider agent, current docs and fixtures | Manual correction, limited selected images, no assumed calibrated confidence. |
| P1 | Deletion/retention beyond app-controlled storage | Coordinator/provider research | Explain provider retention; no instant all-copy deletion promise. |
| P1 | Difficulty of social poses, occlusion and identity fidelity | Quality agent, varied consented cases | Narrow supported inputs and show source comparison. |
| P2 | Novelty at completed-native-overlay level | Research agent, optional competitor testing | Convenience/reliability positioning; no first-ever claim. |
| P2 | Personal avatar and arbitrary garment 3D | 3D agent, bounded known-asset viewer then reconstruction research | Clearly labeled viewer demo and 2D fallback. |

## 13. Hackathon requirements and delivery checklist

The current event is **YouCam API Skin AI & eCommerce VTO Hackathon**. Submission closes **November 2, 2026 at 11:45 AM Eastern / 8:45 AM Pacific / 16:45 UTC**. Judging ends **November 20 at 11:45 AM Eastern**. An existing project requires significant updates after September 29, 2026 noon Eastern, explained in the entry. Confirm entrant/team eligibility directly against the official location, age and conflict restrictions; eligibility has not been checked for this user. [Official rules](https://youcam-api-skin-ai-ecommerce.devpost.com/rules).

Deliver a working application using at least one YouCam API with clear consumer/eCommerce value; source/assets/setup repository; text description and screenshots; a public **1–3 minute YouTube/Vimeo intended-device demo** identifying the API; and free judge testing access through the end of judging. Materials must be in English or include English translations, including demo and testing instructions. Public source requires appropriate licensing; private source must be shared per the rules. Recheck rules before submission. [Rules](https://youcam-api-skin-ai-ecommerce.devpost.com/rules), [overview](https://youcam-api-skin-ai-ecommerce.devpost.com/).

Judging weights implementation, design, potential impact and idea equally. Demonstrate the full native overlay interaction and observed usefulness rather than adding unrelated sponsor endpoints. A winner must participate in an exit interview; the overview also specifies a feature article. [Criteria/overview](https://youcam-api-skin-ai-ecommerce.devpost.com/).

Participants may redeem **1,000 free API units** through registration/email code/account redemption; allocations are nontransferable and valid 90 days after redemption. Optional social-sharing bonus is reviewed after the submission deadline, so do not budget it as development credit. [Resources](https://youcam-api-skin-ai-ecommerce.devpost.com/resources), [bonus rules](https://youcam-api-skin-ai-ecommerce.devpost.com/rules).

The older **Skin AI & Apparel VTO** event ended August 17, 2026. Its gallery is prior-art research, not the current event gallery. [Prior event](https://youcam-api.devpost.com/).

### Suggested demo sequence

Show a real Android phone in Instagram; activate the authorized session; select a clear post/reel outfit; correct/confirm a choice; show real YouCam generation and final personal image over the same feed; collapse and continue scrolling; stop capture. Briefly identify YouCam V4, appearance-preview limitations and the consumer value. Show Three.js only if genuinely implemented, labeled with its actual asset/reconstruction status.

Prepare judge instructions for Android version/device, installation, permissions, personal-photo requirements, tested category, backend availability, known limits and spending allowance. A quota must not silently make required judge testing impossible; reserve sufficient authorized units/service availability for that period. Public footage must have permission for included third-party trademarks, music and copyrighted material.

## 14. References and preserved artifacts

Research used Context7 where available, then official documentation/primary product sources. Android Context7 availability was unreliable, so official Android pages were used as fallback. URLs and accounts can change; implementation must recheck current documentation and pin tested versions.

### Existing research — preserve

- [Overlay novelty/platform research](research/overlay-research.md): detailed comparator evidence, distinctions among native overlays/browser extensions/share flows, platform limitations and the 3D scope.
- [Stack and durable-workflow research](research/tech-stack.md): stack reasoning, Cloud Tasks/Firestore invariants, IAM/billing and retry details. Its earlier unconfirmed V4 pricing/privacy notes are superseded by sections 6 and 12 here.
- [Original hackathon idea research](research/idea-research.md): archived concepts including Encore, novelty scans and sponsor references. Those alternate concepts are not active features; this user chose the overlay product.

### Implementation documentation index

| Area | Primary references |
| --- | --- |
| Compose/overlay | [Compose](https://developer.android.com/compose), [application overlay window](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#TYPE_APPLICATION_OVERLAY), [Compose in Android views](https://developer.android.com/develop/ui/compose/migrate/interoperability-apis/compose-in-views) |
| Capture/services/tiles | [MediaProjection](https://developer.android.com/media/grow/media-projection), [foreground service type](https://developer.android.com/develop/background-work/services/fgs/service-types#media-projection), [background starts](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start), [Quick Settings](https://developer.android.com/develop/ui/views/quicksettings-tiles) |
| Restrictions/activation | [capture and overlay restrictions](https://developer.android.com/security/fraud-prevention/activities), [secure window flag](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#FLAG_SECURE), [Android power-key handling](https://android.googlesource.com/platform/frameworks/base/+/android16-release/services/core/java/com/android/server/policy/PhoneWindowManager.java#5463) |
| Gemini | [image understanding/boxes](https://ai.google.dev/gemini-api/docs/image-understanding), [structured output](https://ai.google.dev/gemini-api/docs/structured-output), [current models](https://ai.google.dev/gemini-api/docs/models), [Python SDK](https://github.com/googleapis/python-genai) |
| YouCam | [Clothes V4 reference](https://docs.perfectcorp.com/reference/ai_clothes), [OpenAPI bundle](https://docs.perfectcorp.com/_bundle/reference/ai_clothes.json?download=), [API terms](https://www.perfectcorp.com/perfectbeauty/youcam/terms-of-service-api), [privacy](https://www.perfectcorp.com/perfectbeauty/youcam/privacy-policy-api) |
| HTTP/images | [OkHttp recipes](https://square.github.io/okhttp/recipes/), [HTTPX async](https://www.python-httpx.org/async/), [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/), [Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html) |
| Firebase/GCP | [verify user tokens](https://firebase.google.com/docs/auth/admin/verify-id-tokens), [transactions](https://firebase.google.com/docs/firestore/manage-data/transactions), [Cloud Run FastAPI](https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-fastapi-service), [Cloud Run Tasks](https://docs.cloud.google.com/run/docs/triggering/using-tasks), [Tasks pitfalls](https://docs.cloud.google.com/tasks/docs/common-pitfalls), [secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets), [storage lifecycle](https://docs.cloud.google.com/storage/docs/lifecycle) |
| Three.js | [GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html), [WebGLRenderer](https://threejs.org/docs/pages/WebGLRenderer.html), [WebView local content](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content) |
| Challenge | [current overview](https://youcam-api-skin-ai-ecommerce.devpost.com/), [rules](https://youcam-api-skin-ai-ecommerce.devpost.com/rules), [resources](https://youcam-api-skin-ai-ecommerce.devpost.com/resources), [older gallery](https://youcam-api.devpost.com/project-gallery) |

## 15. Fresh-agent operating instructions and suggested skills

Follow the user's supplied AGENTS.md conventions:

1. **Use Context7 for current library/framework/SDK/API/CLI/cloud documentation**, even when familiar. Start with resolve-library-id unless the user supplies the exact ID, select a relevant authoritative match, then query-docs. If unavailable or incomplete, document that and use official primary sources.
2. **Prefix shell commands with rtk.** Use rtk proxy for an unsupported command where needed. Prefer rg for file/text searches. Do not expose secrets in command output.
3. Use sub-agents for the independent lanes identified above; one coordinator owns shared contracts/integration. Do not coedit shared files or manipulate the same phone concurrently.
4. Preserve unrelated workspace files and archived research. Do not claim a gate passed based on mocks, documentation alone or unavailable hardware.
5. Keep meaningful progress updates concise. Ask for truly necessary missing device/account information while progressing independent local work.

Suggested skills for the next agent:

- **context7-mcp** — current dependency/API docs, required by the user's instructions.
- **mobile-design** — native touch/accessibility/permission interaction decisions.
- **research** — resolve scoped provider/competitor/3D questions against primary sources and preserve evidence.
- **tdd** — focused tests for substantive coordinate, authorization, idempotency, state and cancellation logic.
- **diagnose** — reproduce and isolate device/provider integration failures.
- **handoff** — write a short next-session entry point referencing this PRD and implemented artifacts. Read its installed SKILL.md when available; the repository handoff is [HANDOFF.md](../HANDOFF.md).

The next implementation agent's first deliverable is **Stage 1 evidence and frozen contracts**, followed by the parallel feature lanes. The original research/specification session created no application code or cloud resources and made no paid API calls or hackathon submission. A public documentation repository was subsequently created; implementation and the validation gates remain pending.
