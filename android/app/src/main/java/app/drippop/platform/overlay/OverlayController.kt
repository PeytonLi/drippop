package app.drippop.platform.overlay

import android.content.Context
import android.graphics.PixelFormat
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.ViewCompositionStrategy
import androidx.lifecycle.setViewTreeLifecycleOwner
import androidx.lifecycle.setViewTreeViewModelStoreOwner
import androidx.savedstate.setViewTreeSavedStateRegistryOwner
import app.drippop.contract.OverlayHost
import kotlin.math.roundToInt

/**
 * TYPE_APPLICATION_OVERLAY windows: a small draggable bubble and an expandable bottom panel. Each window
 * is sized to its visible content and is FLAG_NOT_FOCUSABLE, so touches outside reach the app beneath.
 * Main thread only.
 */
class OverlayController(private val context: Context) : OverlayHost {
    private val wm = context.getSystemService(WindowManager::class.java)
    private var harness: DevTryOnHarness? = null
    private var bubble: OverlayWindow? = null
    private var panel: OverlayWindow? = null

    val isExpanded: Boolean get() = panel != null
    val windowCount: Int get() = listOfNotNull(bubble, panel).size

    fun attachHarness(h: DevTryOnHarness) {
        harness = h
    }

    override fun showBubble() {
        if (bubble != null) return
        val density = context.resources.displayMetrics.density
        val params = baseParams(WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT).apply {
            gravity = Gravity.TOP or Gravity.START
            x = (16 * density).roundToInt()
            y = (220 * density).roundToInt()
        }
        bubble = OverlayWindow(context, wm, params) {
            harness?.let { h -> Bubble(h, onDrag = { dx, dy -> moveBubble(dx, dy) }) }
        }.also { it.attach() }
    }

    private fun moveBubble(dx: Float, dy: Float) {
        val w = bubble ?: return
        val bounds = wm.currentWindowMetrics.bounds
        w.params.x = (w.params.x + dx.roundToInt()).coerceIn(0, bounds.width() - w.view.width.coerceAtLeast(1))
        w.params.y = (w.params.y + dy.roundToInt()).coerceIn(0, bounds.height() - w.view.height.coerceAtLeast(1))
        wm.updateViewLayout(w.view, w.params)
    }

    override fun expand() {
        if (panel != null) return
        val bounds = wm.currentWindowMetrics.bounds
        val params = baseParams(WindowManager.LayoutParams.MATCH_PARENT, (bounds.height() * PANEL_HEIGHT_FRACTION).roundToInt()).apply {
            gravity = Gravity.BOTTOM
        }
        panel = OverlayWindow(context, wm, params) { harness?.let { Panel(it) } }.also { it.attach() }
    }

    override fun collapse() {
        panel?.detach()
        panel = null
    }

    override fun removeAll() {
        collapse()
        bubble?.detach()
        bubble = null
    }

    /** Invisible windows are not composited, so they cannot appear in a full-display capture. */
    fun setHiddenForCapture(hidden: Boolean) {
        val v = if (hidden) View.INVISIBLE else View.VISIBLE
        bubble?.view?.visibility = v
        panel?.view?.visibility = v
    }

    private fun baseParams(width: Int, height: Int) = WindowManager.LayoutParams(
        width, height,
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
        PixelFormat.TRANSLUCENT,
    ).apply { title = "DripPopOverlay" }

    private class OverlayWindow(
        context: Context,
        private val wm: WindowManager,
        val params: WindowManager.LayoutParams,
        content: @Composable () -> Unit,
    ) {
        private val owner = OverlayLifecycleOwner()
        val view = ComposeView(context).apply {
            setViewCompositionStrategy(ViewCompositionStrategy.DisposeOnDetachedFromWindowOrReleasedFromPool)
            setContent { content() }
        }

        fun attach() {
            owner.onCreate()
            view.setViewTreeLifecycleOwner(owner)
            view.setViewTreeViewModelStoreOwner(owner)
            view.setViewTreeSavedStateRegistryOwner(owner)
            wm.addView(view, params)
            owner.onResume()
        }

        fun detach() {
            view.disposeComposition()
            if (view.isAttachedToWindow) wm.removeViewImmediate(view)
            owner.onDestroy()
        }
    }

    private companion object {
        const val PANEL_HEIGHT_FRACTION = 0.62f
    }
}
