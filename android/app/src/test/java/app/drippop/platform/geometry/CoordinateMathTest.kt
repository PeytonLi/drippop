package app.drippop.platform.geometry

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class CoordinateMathTest {
    private val eps = 1e-3f

    private fun assertRect(expected: ViewRect, actual: ViewRect) {
        assertEquals("left", expected.left, actual.left, eps)
        assertEquals("top", expected.top, actual.top, eps)
        assertEquals("right", expected.right, actual.right, eps)
        assertEquals("bottom", expected.bottom, actual.bottom, eps)
    }

    @Test
    fun sameAspectFillsViewExactly() {
        val r = CoordinateMath.imageToView(floatArrayOf(0.1f, 0.2f, 0.5f, 0.6f), 1080, 1920, 0, 540, 960)
        assertRect(ViewRect(54f, 192f, 270f, 576f), r)
    }

    @Test
    fun tallImageInSquareViewIsPillarboxed() {
        // scale = 1000/1920, content width = 562.5, x offset = 218.75
        val r = CoordinateMath.imageToView(floatArrayOf(0f, 0f, 1f, 1f), 1080, 1920, 0, 1000, 1000)
        assertRect(ViewRect(218.75f, 0f, 781.25f, 1000f), r)
    }

    @Test
    fun wideImageInSquareViewIsLetterboxed() {
        val r = CoordinateMath.imageToView(floatArrayOf(0f, 0.5f, 0.5f, 1f), 1920, 1080, 0, 1000, 1000)
        // content height = 562.5, y offset = 218.75
        assertRect(ViewRect(0f, 500f, 500f, 781.25f), r)
    }

    @Test
    fun rotation90ClockwiseMovesTopLeftToTopRight() {
        // 1080x1920 portrait image displayed rotated 90° CW is 1920x1080.
        val r = CoordinateMath.imageToView(floatArrayOf(0f, 0f, 0.5f, 0.25f), 1080, 1920, 90, 1920, 1080)
        assertRect(ViewRect(1440f, 0f, 1920f, 540f), r)
    }

    @Test
    fun rotation180FlipsBothAxes() {
        val r = CoordinateMath.imageToView(floatArrayOf(0f, 0f, 0.5f, 0.25f), 1000, 1000, 180, 1000, 1000)
        assertRect(ViewRect(500f, 750f, 1000f, 1000f), r)
    }

    @Test
    fun rotation270ClockwiseMovesTopLeftToBottomLeft() {
        val r = CoordinateMath.imageToView(floatArrayOf(0f, 0f, 0.5f, 0.25f), 1080, 1920, 270, 1920, 1080)
        assertRect(ViewRect(0f, 540f, 480f, 1080f), r)
    }

    @Test
    fun roundTripForEveryRotationWithLetterbox() {
        val rnd = Random(7)
        for (rotation in listOf(0, 90, 180, 270)) {
            repeat(200) {
                val l = rnd.nextFloat() * 0.8f
                val t = rnd.nextFloat() * 0.8f
                val box = floatArrayOf(l, t, l + 0.01f + rnd.nextFloat() * (0.99f - l), t + 0.01f + rnd.nextFloat() * (0.99f - t))
                val view = CoordinateMath.imageToView(box, 1080, 2340, rotation, 900, 1300)
                val back = CoordinateMath.viewToImage(view, 1080, 2340, rotation, 900, 1300)
                assertArrayEquals("rotation=$rotation", box, back, 1e-4f)
            }
        }
    }

    @Test
    fun viewToImageClampsLetterboxAreaIntoImage() {
        // Pillarbox spans x 218.75..781.25; a rect covering the whole view clamps to the full image.
        val back = CoordinateMath.viewToImage(ViewRect(0f, -10f, 1000f, 1010f), 1080, 1920, 0, 1000, 1000)
        assertArrayEquals(floatArrayOf(0f, 0f, 1f, 1f), back, 1e-6f)
    }

    @Test
    fun viewToImageNormalizesInvertedDrag() {
        val back = CoordinateMath.viewToImage(ViewRect(500f, 500f, 0f, 0f), 1000, 1000, 0, 1000, 1000)
        assertArrayEquals(floatArrayOf(0f, 0f, 0.5f, 0.5f), back, 1e-6f)
    }

    @Test
    fun isValidBoxRejectsMalformedOrOutOfRangeBoxes() {
        assertTrue(CoordinateMath.isValidBox(floatArrayOf(0f, 0f, 1f, 1f)))
        assertFalse(CoordinateMath.isValidBox(floatArrayOf(0f, 0f, 1f)))
        assertFalse(CoordinateMath.isValidBox(floatArrayOf(-0.1f, 0f, 0.5f, 0.5f)))
        assertFalse(CoordinateMath.isValidBox(floatArrayOf(0f, 0f, 1.01f, 0.5f)))
        assertFalse(CoordinateMath.isValidBox(floatArrayOf(0.5f, 0f, 0.5f, 0.5f)))
        assertFalse(CoordinateMath.isValidBox(floatArrayOf(0.6f, 0f, 0.5f, 0.5f)))
        assertFalse(CoordinateMath.isValidBox(floatArrayOf(0f, Float.NaN, 0.5f, 0.5f)))
    }

    @Test(expected = IllegalArgumentException::class)
    fun imageToViewRejectsInvalidBox() {
        CoordinateMath.imageToView(floatArrayOf(0.2f, 0.2f, 0.1f, 0.5f), 100, 100, 0, 100, 100)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsUnsupportedRotation() {
        CoordinateMath.imageToView(floatArrayOf(0f, 0f, 1f, 1f), 100, 100, 45, 100, 100)
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsEmptyView() {
        CoordinateMath.imageToView(floatArrayOf(0f, 0f, 1f, 1f), 100, 100, 0, 0, 100)
    }

    @Test
    fun pixelCropRoundsOutwardAndClamps() {
        val crop = CoordinateMath.pixelCrop(floatArrayOf(0.101f, 0.249f, 0.5f, 1f), 1080, 1920)
        assertEquals(PixelRect(109, 478, 540, 1920), crop)
    }

    @Test
    fun pixelCropIsAtLeastOnePixel() {
        val crop = CoordinateMath.pixelCrop(floatArrayOf(0.5f, 0.5f, 0.5001f, 0.5001f), 10, 10)
        assertEquals(1, crop.width)
        assertEquals(1, crop.height)
    }
}
