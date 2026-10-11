package app.drippop.platform.net

import app.drippop.contract.ApiResult
import app.drippop.contract.CapturedFrame
import app.drippop.contract.DripPopApi
import java.io.IOException
import java.net.ConnectException
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLHandshakeException
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject

/**
 * Live DripPopApi over OkHttp. Bearer = Supabase anonymous access token; a 401 is
 * retried exactly once after a forced refresh with the identical request (same
 * Idempotency-Key, same body bytes).
 */
class HttpDripPopApi(
    private val baseUrl: String,
    private val auth: SupabaseAnonAuth,
    private val http: OkHttpClient,
) : DripPopApi {

    override suspend fun detect(frame: CapturedFrame): ApiResult<String> {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("frame", imageFilename(frame.mime), frameBody(frame))
            .build()
        return call(buildRequest("POST", "/v1/garments:detect", body)) { it.bodyString() }
    }

    override suspend fun createJob(
        idempotencyKey: String,
        person: CapturedFrame,
        reference: CapturedFrame,
        category: String,
    ): ApiResult<String> {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("person_photo", imageFilename(person.mime), frameBody(person))
            .addFormDataPart("reference_photo", imageFilename(reference.mime), frameBody(reference))
            .addFormDataPart(
                "metadata",
                null,
                """{"garment_category":"$category"}""".toRequestBody("application/json".toMediaType()),
            )
            .build()
        val request = buildRequest("POST", "/v1/jobs", body)
            .header("Idempotency-Key", idempotencyKey)
        return call(request) { it.bodyString() }
    }

    override suspend fun getJob(jobId: String): ApiResult<String> =
        call(buildRequest("GET", "/v1/jobs/$jobId", null)) { it.bodyString() }

    override suspend fun getResult(jobId: String): ApiResult<ByteArray> =
        call(buildRequest("GET", "/v1/jobs/$jobId/result", null)) { response ->
            val data = response.body?.bytes() ?: byteArrayOf()
            if (data.size > MAX_RESULT_BYTES) {
                throw OversizeResult()
            }
            data
        }

    override suspend fun deleteJob(jobId: String): ApiResult<String> =
        call(buildRequest("DELETE", "/v1/jobs/$jobId", null)) { it.bodyString() }

    private class OversizeResult : IOException()

    private fun frameBody(frame: CapturedFrame): RequestBody =
        frame.bytes.toRequestBody(frame.mime.toMediaType())

    private fun imageFilename(mime: String): String =
        if (mime == "image/png") "x.png" else "x.jpg"

    private fun buildRequest(method: String, path: String, body: RequestBody?): Request.Builder =
        Request.Builder()
            .url("$baseUrl$path")
            .method(method, body)

    private fun Response.bodyString(): String = body?.string().orEmpty()

    private suspend fun <T> call(
        request: Request.Builder,
        onSuccess: (Response) -> T,
    ): ApiResult<T> {
        var token = auth.accessToken()
            ?: return ApiResult.Error(0, null, true)
        var authed = request.header("Authorization", "Bearer $token").build()
        return try {
            var response = execute(authed)
            if (response.code == 401) {
                response.close()
                token = auth.accessToken(forceRefresh = true)
                    ?: return ApiResult.Error(0, null, true)
                authed = request.header("Authorization", "Bearer $token").build()
                response = execute(authed)
            }
            mapResponse(response, onSuccess)
        } catch (e: OversizeResult) {
            ApiResult.Error(0, null, false)
        } catch (e: IOException) {
            mapIOException(e)
        }
    }

    private suspend fun execute(request: Request): Response =
        suspendCancellableCoroutine { cont ->
            val call = http.newCall(request)
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(
                object : Callback {
                    override fun onFailure(call: Call, e: IOException) {
                        cont.resumeWith(Result.failure(e))
                    }

                    override fun onResponse(call: Call, response: Response) {
                        cont.resumeWith(Result.success(response))
                    }
                },
            )
        }

    private fun <T> mapResponse(response: Response, onSuccess: (Response) -> T): ApiResult<T> {
        response.use { r ->
            if (r.isSuccessful) {
                return try {
                    ApiResult.Ok(onSuccess(r))
                } catch (e: OversizeResult) {
                    throw e
                } catch (e: IOException) {
                    ApiResult.Error(0, null, true)
                }
            }
            val body = r.body?.string().orEmpty()
            val error = runCatching { JSONObject(body).optJSONObject("error") }.getOrNull()
            val code = error?.optString("code")?.takeIf { it.isNotEmpty() }
            val retryable = error?.optBoolean("retryable")
            return when {
                error != null && code != null && retryable != null ->
                    ApiResult.Error(r.code, code, retryable)
                error != null && code != null ->
                    ApiResult.Error(r.code, code, r.code >= 500 || r.code == 429)
                else ->
                    ApiResult.Error(r.code, null, r.code >= 500 || r.code == 429)
            }
        }
    }

    private fun <T> mapIOException(e: IOException): ApiResult<T> = when {
        e is ConnectException || e is UnknownHostException || e is SSLHandshakeException ->
            ApiResult.Error(0, null, true)
        else -> ApiResult.Uncertain
    }

    companion object {
        private const val MAX_RESULT_BYTES = 15 * 1024 * 1024

        /** Shared client: generous read/call timeouts for Render free-tier cold starts (~60 s). */
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .readTimeout(90, TimeUnit.SECONDS)
            .callTimeout(120, TimeUnit.SECONDS)
            .build()
    }
}
