package app.drippop.platform.onboarding

import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.net.Uri
import app.drippop.contract.CapturedFrame
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID
import kotlin.math.max

/**
 * Keeps exactly one personal photo in app-private storage (filesDir/profile; excluded from backup and
 * device transfer by data_extraction_rules.xml). Only the picked image is copied, re-encoded upright
 * (ImageDecoder applies EXIF orientation) and downscaled; replacing or deleting removes the old file.
 */
class PersonalPhotoStore(context: Context) {
    private val appContext = context.applicationContext
    private val dir = File(appContext.filesDir, "profile")
    private val file = File(dir, "personal.jpg")

    data class Summary(val width: Int, val height: Int, val suitable: Boolean, val issues: List<String>)

    val exists: Boolean get() = file.isFile

    fun file(): File? = file.takeIf { it.isFile }

    suspend fun importFrom(uri: Uri): Summary = withContext(Dispatchers.IO) {
        val source = ImageDecoder.createSource(appContext.contentResolver, uri)
        val bitmap = ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            val longSide = max(info.size.width, info.size.height)
            if (longSide > MAX_SIDE) {
                val s = MAX_SIDE.toFloat() / longSide
                decoder.setTargetSize((info.size.width * s).toInt(), (info.size.height * s).toInt())
            }
        }
        dir.mkdirs()
        val tmp = File(dir, "personal.tmp")
        tmp.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 92, it) }
        if (!tmp.renameTo(file)) {
            tmp.copyTo(file, overwrite = true)
            tmp.delete()
        }
        summarize(bitmap.width, bitmap.height).also { bitmap.recycle() }
    }

    fun delete() {
        dir.listFiles()?.forEach { it.delete() }
    }

    suspend fun loadFrame(): CapturedFrame? = withContext(Dispatchers.IO) {
        val f = file() ?: return@withContext null
        val opts = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        android.graphics.BitmapFactory.decodeFile(f.path, opts)
        CapturedFrame(UUID.randomUUID().toString(), f.readBytes(), "image/jpeg", opts.outWidth, opts.outHeight, f.lastModified())
    }

    private fun summarize(width: Int, height: Int): Summary {
        val issues = buildList {
            if (minOf(width, height) < MIN_SIDE) add("Image is small (${width}x$height); use a sharper photo.")
            if (width > height) add("Landscape photo; a front-facing standing portrait works best.")
        }
        return Summary(width, height, issues.isEmpty(), issues)
    }

    companion object {
        const val MAX_SIDE = 2048
        const val MIN_SIDE = 512
    }
}
