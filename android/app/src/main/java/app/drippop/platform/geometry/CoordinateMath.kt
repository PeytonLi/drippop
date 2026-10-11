package app.drippop.platform.geometry

import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

/** Overlay/view pixel rectangle (platform-free so it is unit-testable on the JVM). */
data class ViewRect(val left: Float, val top: Float, val right: Float, val bottom: Float)

/** Integer pixel rectangle in upright source image space; right/bottom exclusive. */
data class PixelRect(val left: Int, val top: Int, val right: Int, val bottom: Int) {
    val width: Int get() = right - left
    val height: Int get() = bottom - top
}

/**
 * Pure math behind [app.drippop.contract.CoordinateMapper].
 *
 * Boxes are normalized `[l, t, r, b]` in the upright source image (contract `normalized_upright_xyxy`).
 * The image is displayed rotated clockwise by `rotationDegrees` and aspect-fit (centered,
 * letterboxed or pillarboxed) inside a `viewWidthPx` x `viewHeightPx` view.
 */
object CoordinateMath {
    private val ROTATIONS = setOf(0, 90, 180, 270)

    fun isValidBox(box: FloatArray): Boolean {
        if (box.size != 4 || box.any { !it.isFinite() }) return false
        val (l, t, r, b) = box.toList()
        return l >= 0f && t >= 0f && r <= 1f && b <= 1f && l < r && t < b
    }

    fun imageToView(
        box: FloatArray,
        imageWidth: Int,
        imageHeight: Int,
        rotationDegrees: Int,
        viewWidthPx: Int,
        viewHeightPx: Int,
    ): ViewRect {
        require(isValidBox(box)) { "invalid normalized box: ${box.contentToString()}" }
        val fit = fit(imageWidth, imageHeight, rotationDegrees, viewWidthPx, viewHeightPx)
        val (l, t, r, b) = rotate(box, rotationDegrees).toList()
        return ViewRect(
            left = fit.offsetX + l * fit.contentWidth,
            top = fit.offsetY + t * fit.contentHeight,
            right = fit.offsetX + r * fit.contentWidth,
            bottom = fit.offsetY + b * fit.contentHeight,
        )
    }

    /** Inverse of [imageToView]; normalizes inverted drags and clamps letterbox regions into [0, 1]. */
    fun viewToImage(
        rect: ViewRect,
        imageWidth: Int,
        imageHeight: Int,
        rotationDegrees: Int,
        viewWidthPx: Int,
        viewHeightPx: Int,
    ): FloatArray {
        val fit = fit(imageWidth, imageHeight, rotationDegrees, viewWidthPx, viewHeightPx)
        fun nx(x: Float) = ((x - fit.offsetX) / fit.contentWidth).coerceIn(0f, 1f)
        fun ny(y: Float) = ((y - fit.offsetY) / fit.contentHeight).coerceIn(0f, 1f)
        val rotated = floatArrayOf(
            nx(min(rect.left, rect.right)),
            ny(min(rect.top, rect.bottom)),
            nx(max(rect.left, rect.right)),
            ny(max(rect.top, rect.bottom)),
        )
        return rotate(rotated, (360 - rotationDegrees) % 360)
    }

    /** Pixel crop of an upright image, rounded outward so the full box is kept, at least 1x1. */
    fun pixelCrop(box: FloatArray, imageWidth: Int, imageHeight: Int): PixelRect {
        require(isValidBox(box)) { "invalid normalized box: ${box.contentToString()}" }
        require(imageWidth > 0 && imageHeight > 0) { "empty image" }
        val left = floor(box[0] * imageWidth).toInt().coerceIn(0, imageWidth - 1)
        val top = floor(box[1] * imageHeight).toInt().coerceIn(0, imageHeight - 1)
        val right = ceil(box[2] * imageWidth).toInt().coerceIn(left + 1, imageWidth)
        val bottom = ceil(box[3] * imageHeight).toInt().coerceIn(top + 1, imageHeight)
        return PixelRect(left, top, right, bottom)
    }

    /** Rotates a normalized box clockwise by [degrees] (0/90/180/270). */
    internal fun rotate(box: FloatArray, degrees: Int): FloatArray {
        require(degrees in ROTATIONS) { "unsupported rotation: $degrees" }
        val (l, t, r, b) = box.toList()
        return when (degrees) {
            0 -> floatArrayOf(l, t, r, b)
            90 -> floatArrayOf(1f - b, l, 1f - t, r)
            180 -> floatArrayOf(1f - r, 1f - b, 1f - l, 1f - t)
            else -> floatArrayOf(t, 1f - r, b, 1f - l)
        }
    }

    private class Fit(val offsetX: Float, val offsetY: Float, val contentWidth: Float, val contentHeight: Float)

    private fun fit(imageWidth: Int, imageHeight: Int, rotationDegrees: Int, viewWidth: Int, viewHeight: Int): Fit {
        require(rotationDegrees in ROTATIONS) { "unsupported rotation: $rotationDegrees" }
        require(imageWidth > 0 && imageHeight > 0) { "empty image" }
        require(viewWidth > 0 && viewHeight > 0) { "empty view" }
        val swap = rotationDegrees == 90 || rotationDegrees == 270
        val w = (if (swap) imageHeight else imageWidth).toFloat()
        val h = (if (swap) imageWidth else imageHeight).toFloat()
        val scale = min(viewWidth / w, viewHeight / h)
        val cw = w * scale
        val ch = h * scale
        return Fit((viewWidth - cw) / 2f, (viewHeight - ch) / 2f, cw, ch)
    }
}
