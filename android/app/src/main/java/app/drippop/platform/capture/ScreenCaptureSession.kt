package app.drippop.platform.capture

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.HandlerThread
import android.view.WindowManager
import app.drippop.contract.CaptureResult
import app.drippop.contract.CaptureSession
import app.drippop.contract.CaptureSessionState
import app.drippop.contract.CapturedFrame
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.android.asCoroutineDispatcher
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.ByteArrayOutputStream
import java.util.UUID
import kotlin.coroutines.resume

/**
 * One MediaProjection session = one VirtualDisplay backed by an ImageReader. The token is used exactly
 * once; a stopped session cannot be restarted (fresh consent is required for the next one).
 *
 * Frames are produced in the captured content's current orientation, so they are already upright.
 */
class ScreenCaptureSession(
    context: Context,
    private val projection: MediaProjection,
    private val sessionState: MutableStateFlow<CaptureSessionState>,
    /** Hides (true) or restores (false) every DripPop window; called on the main thread. */
    private val setWindowsHidden: suspend (Boolean) -> Unit,
    private val onSourceVisibilityChanged: (Boolean) -> Unit,
    private val onStopped: () -> Unit,
) : CaptureSession {

    private val appContext = context.applicationContext
    private val thread = HandlerThread("drippop-capture").apply { start() }
    private val handler = Handler(thread.looper)
    private val captureDispatcher = handler.asCoroutineDispatcher()
    private val captureMutex = Mutex()

    private var reader: ImageReader? = null

    // Capture-thread confined. The newest frame is held open so a static screen still yields a frame
    // composed after our windows were hidden (the compositor sends no further frames until content changes).
    private var latest: Image? = null
    private var waiter: CancellableContinuation<Bitmap?>? = null
    private var waiterThresholdNs = 0L
    private var virtualDisplay: VirtualDisplay? = null
    private val _sourceVisible = MutableStateFlow(true)
    val sourceVisible: StateFlow<Boolean> = _sourceVisible.asStateFlow()

    @Volatile private var stopped = false

    override val state: StateFlow<CaptureSessionState> get() = sessionState

    private val callback = object : MediaProjection.Callback() {
        override fun onStop() {
            handler.post { release() }
        }

        override fun onCapturedContentResize(width: Int, height: Int) {
            handler.post { resize(width, height) }
        }

        override fun onCapturedContentVisibilityChanged(isVisible: Boolean) {
            _sourceVisible.value = isVisible
            onSourceVisibilityChanged(isVisible)
        }
    }

    /** Must be called once, after the foreground service started with type mediaProjection. */
    fun start() {
        val wm = appContext.getSystemService(WindowManager::class.java)
        val bounds = wm.maximumWindowMetrics.bounds
        val dpi = appContext.resources.configuration.densityDpi
        // Android 14+: register the callback before createVirtualDisplay or it throws.
        projection.registerCallback(callback, handler)
        val r = newReader(bounds.width(), bounds.height())
        r.setOnImageAvailableListener(::onImageAvailable, handler)
        reader = r
        virtualDisplay = projection.createVirtualDisplay(
            "DripPopCapture", bounds.width(), bounds.height(), dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, r.surface, null, handler,
        )
        sessionState.value = CaptureSessionState.ACTIVE
    }

    override suspend fun captureLatestFrame(): CaptureResult = captureMutex.withLock {
        if (stopped) return CaptureResult.Unavailable(CaptureResult.Reason.STOPPED)
        if (sessionState.value != CaptureSessionState.ACTIVE || reader == null) {
            return CaptureResult.Unavailable(CaptureResult.Reason.NO_SESSION)
        }
        if (!_sourceVisible.value) return CaptureResult.Unavailable(CaptureResult.Reason.SOURCE_NOT_VISIBLE)

        val hiddenAtNs = System.nanoTime()
        withContext(Dispatchers.Main) { setWindowsHidden(true) }
        try {
            delay(HIDE_SETTLE_MS) // let the compositor drop our windows before accepting a frame
            val bitmap = withContext(captureDispatcher) {
                heldFrameAfter(hiddenAtNs) ?: withTimeoutOrNull(FRESH_FRAME_TIMEOUT_MS) { awaitFreshFrame() }
            } ?: return if (stopped) {
                CaptureResult.Unavailable(CaptureResult.Reason.STOPPED)
            } else {
                CaptureResult.Unavailable(CaptureResult.Reason.STALE_FRAME_TIMEOUT)
            }
            try {
                if (looksProtected(bitmap)) return CaptureResult.Unavailable(CaptureResult.Reason.PROTECTED_CONTENT)
                val out = ByteArrayOutputStream()
                bitmap.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
                CaptureResult.Ok(
                    CapturedFrame(
                        frameId = UUID.randomUUID().toString(),
                        bytes = out.toByteArray(),
                        mime = "image/jpeg",
                        width = bitmap.width,
                        height = bitmap.height,
                        capturedAtEpochMs = System.currentTimeMillis(),
                    ),
                )
            } finally {
                bitmap.recycle()
            }
        } finally {
            withContext(Dispatchers.Main) { setWindowsHidden(false) }
        }
    }

    /** Capture thread: keeps only the newest frame; older buffered frames are closed (discarded). */
    private fun onImageAvailable(ir: ImageReader) {
        if (ir !== reader) return
        val image = try { ir.acquireLatestImage() } catch (_: IllegalStateException) { null } ?: return
        latest?.close()
        latest = image
        val cont = waiter ?: return
        if (!FrameFreshness.awaitedFrameAccepted(image.timestamp, waiterThresholdNs, System.nanoTime())) return
        waiter = null
        if (cont.isActive) cont.resume(toBitmap(image))
    }

    /** Capture thread: the held frame, if it was composed after DripPop windows were hidden. */
    private fun heldFrameAfter(hiddenAtNs: Long): Bitmap? {
        val image = latest ?: return null
        if (!FrameFreshness.heldFrameUsable(image.timestamp, hiddenAtNs, System.nanoTime())) return null
        return toBitmap(image)
    }

    /** Capture thread: waits for the first frame delivered after this call. */
    private suspend fun awaitFreshFrame(): Bitmap? {
        val r = reader ?: return null
        return suspendCancellableCoroutine { cont ->
            waiterThresholdNs = System.nanoTime()
            waiter = cont
            cont.invokeOnCancellation { handler.post { if (waiter === cont) waiter = null } }
            // Re-attaching the surface asks the virtual display to deliver a new frame even if the
            // captured content is static.
            virtualDisplay?.let { vd ->
                vd.surface = null
                vd.surface = r.surface
            }
        }
    }

    private fun resize(width: Int, height: Int) {
        if (stopped || width <= 0 || height <= 0) return
        val vd = virtualDisplay ?: return
        val old = reader
        val r = newReader(width, height)
        r.setOnImageAvailableListener(::onImageAvailable, handler)
        latest?.close()
        latest = null
        vd.resize(width, height, appContext.resources.configuration.densityDpi)
        vd.surface = r.surface
        reader = r
        old?.setOnImageAvailableListener(null, null)
        old?.close()
    }

    @SuppressLint("WrongConstant")
    private fun newReader(width: Int, height: Int): ImageReader =
        ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, MAX_IMAGES)

    private fun toBitmap(image: Image): Bitmap {
        val plane = image.planes[0]
        val pixelStride = plane.pixelStride
        val rowPadding = plane.rowStride - pixelStride * image.width
        val padded = Bitmap.createBitmap(image.width + rowPadding / pixelStride, image.height, Bitmap.Config.ARGB_8888)
        padded.copyPixelsFromBuffer(plane.buffer)
        if (padded.width == image.width) return padded
        return Bitmap.createBitmap(padded, 0, 0, image.width, image.height).also { padded.recycle() }
    }

    /** FLAG_SECURE content is delivered as solid black; never try to bypass it. Heuristic. */
    private fun looksProtected(bitmap: Bitmap): Boolean {
        val steps = 12
        for (yi in 0 until steps) for (xi in 0 until steps) {
            val px = bitmap.getPixel(xi * (bitmap.width - 1) / (steps - 1), yi * (bitmap.height - 1) / (steps - 1))
            if ((px shr 16 and 0xff) > 4 || (px shr 8 and 0xff) > 4 || (px and 0xff) > 4) return false
        }
        return true
    }

    override fun stop() {
        handler.post {
            release()
            try { projection.stop() } catch (_: RuntimeException) { }
        }
    }

    private fun release() {
        if (stopped) return
        stopped = true
        virtualDisplay?.release()
        virtualDisplay = null
        waiter?.let { if (it.isActive) it.resume(null) }
        waiter = null
        latest?.close()
        latest = null
        reader?.setOnImageAvailableListener(null, null)
        reader?.close()
        reader = null
        projection.unregisterCallback(callback)
        sessionState.value = CaptureSessionState.STOPPED
        thread.quitSafely()
        onStopped()
    }

    companion object {
        private const val MAX_IMAGES = 3
        private const val HIDE_SETTLE_MS = 150L
        private const val FRESH_FRAME_TIMEOUT_MS = 1_500L
        private const val JPEG_QUALITY = 92
    }
}
