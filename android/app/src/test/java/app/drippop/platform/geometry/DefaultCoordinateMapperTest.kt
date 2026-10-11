package app.drippop.platform.geometry

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.RectF
import app.drippop.contract.CapturedFrame
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.ByteArrayOutputStream

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class DefaultCoordinateMapperTest {

    /** 100x200 upright PNG: TL red, TR green, BL blue, BR white. */
    private fun quadrantFrame(): CapturedFrame {
        val bmp = Bitmap.createBitmap(100, 200, Bitmap.Config.ARGB_8888)
        for (y in 0 until 200) for (x in 0 until 100) {
            val c = when {
                x < 50 && y < 100 -> Color.RED
                y < 100 -> Color.GREEN
                x < 50 -> Color.BLUE
                else -> Color.WHITE
            }
            bmp.setPixel(x, y, c)
        }
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.PNG, 100, out)
        return CapturedFrame("frame-1", out.toByteArray(), "image/png", 100, 200, 1234L)
    }

    @Test
    fun imageToViewUsesLetterboxAndReturnsRectF() {
        val mapper = DefaultCoordinateMapper(imageWidth = 100, imageHeight = 200)
        val r = mapper.imageToView(floatArrayOf(0f, 0f, 1f, 1f), 400, 400)
        assertEquals(RectF(100f, 0f, 300f, 400f), r)
    }

    @Test
    fun viewToImageRoundTripsWithRotation() {
        val mapper = DefaultCoordinateMapper(imageWidth = 1080, imageHeight = 2400, rotationDegrees = 90)
        val box = floatArrayOf(0.2f, 0.3f, 0.7f, 0.9f)
        val back = mapper.viewToImage(mapper.imageToView(box, 1200, 700), 1200, 700)
        assertArrayEquals(box, back, 1e-4f)
    }

    @Test
    fun cropUprightCropsSourceBytesNotTheView() {
        val mapper = DefaultCoordinateMapper(imageWidth = 100, imageHeight = 200, rotationDegrees = 90)
        val frame = quadrantFrame()
        val crop = mapper.cropUpright(frame, floatArrayOf(0.5f, 0f, 1f, 0.5f))
        assertEquals(50, crop.width)
        assertEquals(100, crop.height)
        assertEquals("image/png", crop.mime)
        assertEquals(frame.frameId, crop.frameId)
        assertEquals(frame.capturedAtEpochMs, crop.capturedAtEpochMs)
        val decoded = BitmapFactory.decodeByteArray(crop.bytes, 0, crop.bytes.size)
        assertEquals(50, decoded.width)
        assertEquals(100, decoded.height)
        assertEquals(Color.GREEN, decoded.getPixel(0, 0))
        assertEquals(Color.GREEN, decoded.getPixel(49, 99))
    }

    @Test
    fun cropUprightUsesFrameDimensionsAndKeepsJpegMime() {
        val png = quadrantFrame()
        val bmp = BitmapFactory.decodeByteArray(png.bytes, 0, png.bytes.size)
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 95, out)
        val jpeg = png.copy(bytes = out.toByteArray(), mime = "image/jpeg")
        val crop = DefaultCoordinateMapper(1, 1).cropUpright(jpeg, floatArrayOf(0f, 0.5f, 0.5f, 1f))
        assertEquals("image/jpeg", crop.mime)
        assertEquals(50, crop.width)
        assertEquals(100, crop.height)
        val px = BitmapFactory.decodeByteArray(crop.bytes, 0, crop.bytes.size).getPixel(25, 50)
        assert(Color.blue(px) > 200 && Color.red(px) < 60) { "expected blue quadrant, got ${Integer.toHexString(px)}" }
    }

    @Test(expected = IllegalArgumentException::class)
    fun cropUprightRejectsInvalidBox() {
        DefaultCoordinateMapper(100, 200).cropUpright(quadrantFrame(), floatArrayOf(0.5f, 0.5f, 0.4f, 0.9f))
    }

    @Test(expected = IllegalArgumentException::class)
    fun cropUprightRejectsDimensionMismatch() {
        DefaultCoordinateMapper(100, 200).cropUpright(quadrantFrame().copy(width = 99), floatArrayOf(0f, 0f, 1f, 1f))
    }
}
