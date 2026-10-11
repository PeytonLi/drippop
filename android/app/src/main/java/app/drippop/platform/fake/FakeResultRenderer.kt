package app.drippop.platform.fake

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import app.drippop.contract.CapturedFrame
import java.io.ByteArrayOutputStream
import kotlin.math.max

/** Produces an obviously fake "result": the reference crop tinted and stamped FAKE PREVIEW. */
object FakeResultRenderer {
    private const val MAX_SIDE = 768

    fun render(person: CapturedFrame, reference: CapturedFrame): ByteArray {
        val src = BitmapFactory.decodeByteArray(reference.bytes, 0, reference.bytes.size)
            ?: BitmapFactory.decodeByteArray(person.bytes, 0, person.bytes.size)
        val scale = if (src == null) 1f else minOf(1f, MAX_SIDE.toFloat() / max(src.width, src.height))
        val w = src?.let { (it.width * scale).toInt().coerceAtLeast(1) } ?: 512
        val h = src?.let { (it.height * scale).toInt().coerceAtLeast(1) } ?: 768
        val out = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(out)
        canvas.drawColor(Color.DKGRAY)
        if (src != null) {
            canvas.drawBitmap(Bitmap.createScaledBitmap(src, w, h, true), 0f, 0f, null)
            src.recycle()
        }
        canvas.drawColor(Color.argb(90, 255, 0, 160))
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            typeface = Typeface.DEFAULT_BOLD
            textAlign = Paint.Align.CENTER
            textSize = w / 7f
            setShadowLayer(8f, 0f, 0f, Color.BLACK)
        }
        canvas.save()
        canvas.rotate(-30f, w / 2f, h / 2f)
        canvas.drawText("FAKE PREVIEW", w / 2f, h / 2f, paint)
        canvas.restore()
        val bytes = ByteArrayOutputStream()
        out.compress(Bitmap.CompressFormat.JPEG, 90, bytes)
        out.recycle()
        return bytes.toByteArray()
    }
}
