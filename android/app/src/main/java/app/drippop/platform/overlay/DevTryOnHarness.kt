package app.drippop.platform.overlay

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import app.drippop.contract.ApiResult
import app.drippop.contract.CaptureResult
import app.drippop.contract.CaptureSession
import app.drippop.contract.CapturedFrame
import app.drippop.contract.DripPopApi
import app.drippop.platform.geometry.CoordinateMath
import app.drippop.platform.geometry.DefaultCoordinateMapper
import app.drippop.platform.onboarding.PersonalPhotoStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.UUID

/** One selectable garment from a validated DetectionResponse. */
data class Candidate(val personId: String, val personBox: FloatArray, val garmentId: String, val category: String, val box: FloatArray)

sealed interface HarnessState {
    data object Idle : HarnessState
    data object Capturing : HarnessState
    data class Analyzing(val frame: CapturedFrame, val bitmap: Bitmap) : HarnessState
    data class Selecting(val frame: CapturedFrame, val bitmap: Bitmap, val candidates: List<Candidate>, val selected: Candidate?) : HarnessState
    data class Generating(val frame: CapturedFrame, val bitmap: Bitmap, val phase: String) : HarnessState
    data class Ready(val reference: Bitmap, val result: Bitmap) : HarnessState
    data class Error(val message: String) : HarnessState
    data object SourceHidden : HarnessState
}

/**
 * Dev harness flow (platform-owned, replaced by lane 2B's UI): capture → detect →
 * select → job → preview. Late responses for an older frame or attempt are dropped.
 */
class DevTryOnHarness(
    private val context: Context,
    private val scope: CoroutineScope,
    private val session: CaptureSession,
    private val overlay: OverlayController,
    private val api: DripPopApi,
    private val photoStore: PersonalPhotoStore,
    val isFakeApi: Boolean,
    val onStopRequested: () -> Unit,
) {
    private val _state = MutableStateFlow<HarnessState>(HarnessState.Idle)
    val state: StateFlow<HarnessState> = _state.asStateFlow()
    private var currentFrameId: String? = null
    private var currentJobId: String? = null
    private var attemptId: String? = null
    private var work: Job? = null
    private var hiddenFrom: HarnessState? = null

    fun onBubbleTap() {
        when {
            overlay.isExpanded -> overlay.collapse()
            _state.value is HarnessState.Idle || _state.value is HarnessState.Error -> captureNew()
            else -> overlay.expand()
        }
    }

    fun captureNew() {
        work?.cancel()
        attemptId = null
        // The server allows one active job and inputs are private: abandon the old job server-side.
        currentJobId?.let { id -> scope.launch(NonCancellable) { api.deleteJob(id) } }
        currentJobId = null
        _state.value = HarnessState.Capturing
        work = scope.launch {
            when (val r = session.captureLatestFrame()) {
                is CaptureResult.Unavailable -> {
                    _state.value = HarnessState.Error(explain(r.reason))
                    overlay.expand()
                }
                is CaptureResult.Ok -> {
                    val frame = r.frame
                    currentFrameId = frame.frameId
                    val bmp = BitmapFactory.decodeByteArray(frame.bytes, 0, frame.bytes.size)
                    _state.value = HarnessState.Analyzing(frame, bmp)
                    overlay.expand()
                    val detection = api.detect(frame)
                    if (currentFrameId != frame.frameId) return@launch
                    _state.value = when (detection) {
                        is ApiResult.Ok -> HarnessState.Selecting(frame, bmp, parseCandidates(detection.value), null)
                        else -> HarnessState.Selecting(frame, bmp, emptyList(), null)
                    }
                }
            }
        }
    }

    fun select(c: Candidate?) {
        val s = _state.value as? HarnessState.Selecting ?: return
        _state.value = s.copy(selected = c)
    }

    fun generate() {
        val s = _state.value as? HarnessState.Selecting ?: return
        val choice = s.selected ?: return
        val attempt = UUID.randomUUID().toString()
        attemptId = attempt
        val key = "try-" + UUID.randomUUID().toString().replace("-", "")
        _state.value = HarnessState.Generating(s.frame, s.bitmap, "preparing")
        work = scope.launch {
            val mapper = DefaultCoordinateMapper(s.frame.width, s.frame.height)
            val reference = mapper.cropUpright(s.frame, choice.personBox)
            val person = photoStore.loadFrame() ?: reference
            fun stillCurrent() = attemptId == attempt && currentFrameId == s.frame.frameId
            // An Uncertain create may or may not have arrived: retry the SAME key/bytes, never a new key.
            var created = api.createJob(key, person, reference, choice.category)
            for (backoffMs in CREATE_RETRY_BACKOFFS_MS) {
                if (created !is ApiResult.Uncertain) break
                delay(backoffMs)
                if (!stillCurrent()) return@launch
                created = api.createJob(key, person, reference, choice.category)
            }
            if (!stillCurrent()) return@launch
            val jobId = when (created) {
                is ApiResult.Ok -> runCatching { JSONObject(created.value).getString("job_id") }.getOrNull()
                    ?: return@launch fail("Couldn't start the preview: unexpected response.")
                is ApiResult.Error -> return@launch fail("Couldn't start the preview", created)
                ApiResult.Uncertain -> return@launch fail("Couldn't reach the service. Check the connection and try again.")
            }
            currentJobId = jobId

            val deadlineMs = System.currentTimeMillis() + GENERATE_DEADLINE_MS
            while (System.currentTimeMillis() < deadlineMs) {
                var pollMs = POLL_MS
                var done = false
                when (val job = api.getJob(jobId)) {
                    is ApiResult.Ok -> {
                        val json = runCatching { JSONObject(job.value) }.getOrNull()
                            ?: return@launch fail("Couldn't read the job status: unexpected response.")
                        pollMs = json.optLong("poll_after_ms", POLL_MS).takeIf { it > 0 } ?: POLL_MS
                        when (val status = json.optString("status")) {
                            "succeeded" -> done = true
                            "failed", "canceled" -> {
                                val errorCode = json.optJSONObject("error")?.optString("code")?.takeIf { it.isNotEmpty() } ?: "unknown"
                                return@launch fail("The preview $status ($errorCode).")
                            }
                            else -> _state.value = HarnessState.Generating(s.frame, s.bitmap, json.optString("phase", "working"))
                        }
                    }
                    is ApiResult.Error -> if (!job.retryable) return@launch fail("Couldn't read the job status", job)
                    ApiResult.Uncertain -> Unit
                }
                if (done) break
                delay(pollMs)
                if (!stillCurrent()) return@launch
            }
            if (System.currentTimeMillis() >= deadlineMs) {
                return@launch fail("The preview took too long. Try again.")
            }
            _state.value = HarnessState.Generating(s.frame, s.bitmap, "finalizing")
            val bytes = awaitResult(jobId, deadlineMs) { stillCurrent() }
                ?: return@launch
            if (!stillCurrent()) return@launch
            _state.value = HarnessState.Ready(
                reference = BitmapFactory.decodeByteArray(reference.bytes, 0, reference.bytes.size),
                result = BitmapFactory.decodeByteArray(bytes, 0, bytes.size),
            )
        }
    }

    /** getResult with retry: 409 result_not_ready, retryable errors and Uncertain keep polling until the deadline. */
    private suspend fun awaitResult(jobId: String, deadlineMs: Long, stillCurrent: () -> Boolean): ByteArray? {
        while (System.currentTimeMillis() < deadlineMs) {
            when (val result = api.getResult(jobId)) {
                is ApiResult.Ok -> return result.value
                is ApiResult.Error -> {
                    val notReady = result.httpStatus == 409 && result.code == "result_not_ready"
                    if (!notReady && !result.retryable) {
                        fail("The preview isn't available", result)
                        return null
                    }
                }
                ApiResult.Uncertain -> Unit
            }
            if (!stillCurrent()) return null
            delay(POLL_MS)
        }
        fail("The preview took too long. Try again.")
        return null
    }

    fun reset() {
        work?.cancel()
        currentFrameId = null
        attemptId = null
        currentJobId?.let { id -> scope.launch(NonCancellable) { api.deleteJob(id) } }
        currentJobId = null
        _state.value = HarnessState.Idle
    }

    /** onCapturedContentVisibilityChanged: hide private preview content while the source is hidden. */
    fun onSourceVisible(visible: Boolean) {
        if (!visible) {
            if (_state.value !is HarnessState.SourceHidden) hiddenFrom = _state.value
            _state.value = HarnessState.SourceHidden
            overlay.collapse()
        } else if (_state.value is HarnessState.SourceHidden) {
            _state.value = hiddenFrom ?: HarnessState.Idle
            hiddenFrom = null
        }
    }

    fun collapse() = overlay.collapse()

    fun dispose() {
        work?.cancel()
    }

    private fun fail(message: String, error: ApiResult.Error? = null) {
        val suffix = when {
            error?.code != null -> " (${error.code})"
            error != null && error.httpStatus > 0 -> " (HTTP ${error.httpStatus})"
            else -> ""
        }
        _state.value = HarnessState.Error(message + suffix)
    }

    private fun explain(reason: CaptureResult.Reason): String = when (reason) {
        CaptureResult.Reason.NO_SESSION -> "No capture session. Start one from DripPop or the tile."
        CaptureResult.Reason.SOURCE_NOT_VISIBLE -> "The shared app is not visible. Return to it, or start a new session for another app."
        CaptureResult.Reason.PROTECTED_CONTENT -> "This screen is protected and can't be captured. Choose another post or image."
        CaptureResult.Reason.STALE_FRAME_TIMEOUT -> "No fresh frame arrived. Try again."
        CaptureResult.Reason.STOPPED -> "Capture session stopped. Start a new one to continue."
    }

    companion object {
        private const val POLL_MS = 900L
        private const val GENERATE_DEADLINE_MS = 180_000L
        private val CREATE_RETRY_BACKOFFS_MS = longArrayOf(2_000L, 5_000L)
        private val CATEGORIES = setOf("upper_body", "full_body")

        /** Validates boxes/ids/categories; anything malformed is dropped (manual selection stays available). */
        fun parseCandidates(json: String): List<Candidate> = runCatching {
            val root = JSONObject(json)
            val persons = root.getJSONArray("persons")
            val seen = mutableSetOf<String>()
            buildList {
                for (i in 0 until persons.length()) {
                    val p = persons.getJSONObject(i)
                    val pBox = p.getJSONArray("box").let { a -> FloatArray(a.length()) { a.getDouble(it).toFloat() } }
                    if (!CoordinateMath.isValidBox(pBox) || !seen.add(p.getString("id"))) continue
                    val garments = p.getJSONArray("garments")
                    for (j in 0 until garments.length()) {
                        val g = garments.getJSONObject(j)
                        val box = g.getJSONArray("box").let { a -> FloatArray(a.length()) { a.getDouble(it).toFloat() } }
                        val cat = g.getString("category")
                        if (!CoordinateMath.isValidBox(box) || cat !in CATEGORIES || !seen.add(g.getString("id"))) continue
                        add(Candidate(p.getString("id"), pBox, g.getString("id"), cat, box))
                    }
                }
            }
        }.getOrDefault(emptyList())

        val WHOLE_FRAME = Candidate("manual", floatArrayOf(0f, 0f, 1f, 1f), "manual", "upper_body", floatArrayOf(0f, 0f, 1f, 1f))
    }
}
