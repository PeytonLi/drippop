package app.drippop.platform.geometry

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.RectF
import app.drippop.contract.CapturedFrame
import app.drippop.contract.CoordinateMapper
import java.io.ByteArrayOutputStream

/**
 * [CoordinateMapper] for one immutable upright frame displayed aspect-fit and rotated clockwise by
 * [rotationDegrees] in an overlay view. Create a new mapper per frame / display rotation.
 */
class DefaultCoordinateMapper(
    private val imageWidth: Int,
    private val imageHeight: Int,
    private val rotationDegrees: Int = 0,
    private val jpegQuality: Int = 92,
) : CoordinateMapper {

    override fun imageToView(box: FloatArray, viewWidthPx: Int, viewHeightPx: Int): RectF {
        val r = CoordinateMath.imageToView(box, imageWidth, imageHeight, rotationDegrees, viewWidthPx, viewHeightPx)
        return RectF(r.left, r.top, r.right, r.bottom)
    }

    override fun viewToImage(rect: RectF, viewWidthPx: Int, viewHeightPx: Int): FloatArray =
        CoordinateMath.viewToImage(
            ViewRect(rect.left, rect.top, rect.right, rect.bottom),
            imageWidth, imageHeight, rotationDegrees, viewWidthPx, viewHeightPx,
        )

    /**
     * Decodes the frame's own upright bytes and crops [box] (rounded outward). Keeps frameId and
     * capture time so a crop stays attributable to its source frame; PNG stays PNG, else JPEG.
     */
    override fun cropUpright(frame: CapturedFrame, box: FloatArray): CapturedFrame {
        require(CoordinateMath.isValidBox(box)) { "invalid normalized box: ${box.contentToString()}" }
        val source = BitmapFactory.decodeByteArray(frame.bytes, 0, frame.bytes.size)
            ?: throw IllegalArgumentException("undecodable frame ${frame.frameId}")
        try {
            require(source.width == frame.width && source.height == frame.height) {
                "frame ${frame.frameId} declares ${frame.width}x${frame.height} but decodes to ${source.width}x${source.height}"
            }
            val px = CoordinateMath.pixelCrop(box, frame.width, frame.height)
            val cropped = Bitmap.createBitmap(source, px.left, px.top, px.width, px.height)
            val png = frame.mime == "image/png"
            val out = ByteArrayOutputStream()
            cropped.compress(if (png) Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG, jpegQuality, out)
            if (cropped !== source) cropped.recycle()
            return frame.copy(
                bytes = out.toByteArray(),
                mime = if (png) "image/png" else "image/jpeg",
                width = px.width,
                height = px.height,
            )
        } finally {
            source.recycle()
        }
    }
}
