# Android client interfaces (frozen)

Package root: `app.drippop`. Lane 2A (native) owns `app.drippop.platform.*`; lane 2B (UI) owns
`app.drippop.ui.*`, `app.drippop.data.*`; `app.drippop.contract.*` is coordinator-owned and holds only these types.

```kotlin
package app.drippop.contract

/** Immutable, upright frame. Bytes are JPEG or PNG; width/height are of the upright image. */
data class CapturedFrame(
    val frameId: String,          // UUID, new per capture
    val bytes: ByteArray,
    val mime: String,             // "image/jpeg" | "image/png"
    val width: Int,
    val height: Int,
    val capturedAtEpochMs: Long,
)

sealed interface CaptureResult {
    data class Ok(val frame: CapturedFrame) : CaptureResult
    data class Unavailable(val reason: Reason) : CaptureResult
    enum class Reason { NO_SESSION, SOURCE_NOT_VISIBLE, PROTECTED_CONTENT, STALE_FRAME_TIMEOUT, STOPPED }
}

enum class CaptureSessionState { OFF, REQUESTING_CONSENT, ACTIVE, STOPPED }

interface CaptureSession {
    val state: kotlinx.coroutines.flow.StateFlow<CaptureSessionState>
    /** Hides DripPop windows if needed, discards buffered frames, returns one fresh frame. */
    suspend fun captureLatestFrame(): CaptureResult
    fun stop()
}

interface OverlayHost {
    fun showBubble()
    fun expand()
    fun collapse()
    fun removeAll()           // disposes compositions, removes every window
}

/** Normalized [l,t,r,b] in upright image space <-> overlay px. Owned by lane 2A, consumed by 2B. */
interface CoordinateMapper {
    fun imageToView(box: FloatArray, viewWidthPx: Int, viewHeightPx: Int): android.graphics.RectF
    fun viewToImage(rect: android.graphics.RectF, viewWidthPx: Int, viewHeightPx: Int): FloatArray
    /** Crops upright source bytes (not a UI screenshot) to a normalized box. */
    fun cropUpright(frame: CapturedFrame, box: FloatArray): CapturedFrame
}

interface DripPopApi {   // OkHttp; bearer = Supabase access token (refresh + retry once with same key)
    suspend fun detect(frame: CapturedFrame): ApiResult<String /* DetectionResponse JSON */>
    suspend fun createJob(idempotencyKey: String, person: CapturedFrame, reference: CapturedFrame, category: String): ApiResult<String /* JobResponse JSON */>
    suspend fun getJob(jobId: String): ApiResult<String>
    suspend fun getResult(jobId: String): ApiResult<ByteArray>
    suspend fun deleteJob(jobId: String): ApiResult<String>
}

sealed interface ApiResult<out T> {
    data class Ok<T>(val value: T) : ApiResult<T>
    data class Error(val httpStatus: Int, val code: String?, val retryable: Boolean) : ApiResult<Nothing>
    /** Request may or may not have reached the server: retry the SAME key/bytes, never a new key. */
    data object Uncertain : ApiResult<Nothing>
}
```

Try-on UI state: `idle, capturing, analyzing, selecting, uploading, generating, ready, error` carrying
`frameId`, `attemptId`, `selectionVersion`. A response is applied only if all three still match.
Recovery store (app-private, excluded from backup): `{attemptId, idempotencyKey, jobId?, pendingDelete, category, inputPaths}`.
