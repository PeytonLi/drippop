package app.drippop.platform.net

import app.drippop.contract.ApiResult
import app.drippop.contract.CapturedFrame
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class HttpDripPopApiTest {
    private val server = MockWebServer()
    private val http = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .callTimeout(10, TimeUnit.SECONDS)
        .build()
    private val store = MapTokenStore()
    private var nowMs = 1_700_000_000_000L
    private val frame = CapturedFrame("f1", byteArrayOf(1, 2, 3, 4), "image/jpeg", 640, 480, 1L)

    @Before
    fun start() {
        server.start()
        // A cached, far-future token so most tests make no auth call at all.
        store.put("access_token", "test-token")
        store.put("expires_at", ((nowMs / 1000) + 3600).toString())
    }

    @After
    fun stop() = server.shutdown()

    private fun auth() = SupabaseAnonAuth(http, server.url("/").toString().trimEnd('/'), "pub-key", store, { nowMs })
    private fun api() = HttpDripPopApi(server.url("/").toString().trimEnd('/'), auth(), http)

    private fun json(code: Int, body: String) =
        MockResponse().setResponseCode(code).setBody(body)

    @Test
    fun createJobSendsBearerKeyAndMultipartParts() = runTest {
        server.enqueue(json(202, """{"job_id":"job_0123456789abcdef","status":"queued"}"""))
        val result = api().createJob("try-key123", frame, frame, "upper_body")
        assertTrue(result is ApiResult.Ok)

        val req = server.takeRequest()
        assertEquals("Bearer test-token", req.getHeader("Authorization"))
        assertEquals("try-key123", req.getHeader("Idempotency-Key"))
        val body = req.body.readUtf8()
        assertTrue(body.contains("name=\"person_photo\"; filename=\"x.jpg\""))
        assertTrue(body.contains("name=\"reference_photo\"; filename=\"x.jpg\""))
        assertTrue(body.contains("name=\"metadata\""))
        assertTrue(body.contains("""{"garment_category":"upper_body"}"""))
    }

    @Test
    fun unauthorizedRetriesOnceWithSameKeyAndBody() = runTest {
        server.enqueue(json(401, """{"error":{"code":"unauthenticated","retryable":false}}"""))
        server.enqueue(json(200, """{"access_token":"refreshed","refresh_token":"r1","expires_in":3600}"""))
        server.enqueue(json(202, """{"job_id":"job_0123456789abcdef","status":"queued"}"""))
        store.put("refresh_token", "r0")

        val result = api().createJob("try-key123", frame, frame, "upper_body")
        assertTrue(result is ApiResult.Ok)

        val first = server.takeRequest()
        val refresh = server.takeRequest()
        val second = server.takeRequest()
        assertEquals("/v1/jobs", first.path)
        assertEquals("/auth/v1/token?grant_type=refresh_token", refresh.path)
        assertEquals("/v1/jobs", second.path)
        assertEquals(first.getHeader("Idempotency-Key"), second.getHeader("Idempotency-Key"))
        assertEquals(first.body.readByteArray().toList(), second.body.readByteArray().toList())
        assertEquals("Bearer refreshed", second.getHeader("Authorization"))
    }

    @Test
    fun secondUnauthorizedReturnsParsedError() = runTest {
        server.enqueue(json(401, """{"error":{"code":"unauthenticated","retryable":false}}"""))
        server.enqueue(json(200, """{"access_token":"refreshed","expires_in":3600}"""))
        server.enqueue(json(401, """{"error":{"code":"unauthenticated","retryable":false}}"""))
        store.put("refresh_token", "r0")

        val result = api().getJob("job_0123456789abcdef")
        assertEquals(ApiResult.Error(401, "unauthenticated", false), result)
    }

    @Test
    fun conflictResultNotReadyParsesCodeAndRetryable() = runTest {
        server.enqueue(
            json(409, """{"error":{"code":"result_not_ready","message":"x","retryable":true}}"""),
        )
        val result = api().getResult("job_0123456789abcdef")
        assertEquals(ApiResult.Error(409, "result_not_ready", true), result)
    }

    @Test
    fun noResponseIsUncertain() = runTest {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val result = api().getJob("job_0123456789abcdef")
        assertEquals(ApiResult.Uncertain, result)
    }

    @Test
    fun deadServerIsRetryableError() = runTest {
        server.shutdown()
        val result = api().getJob("job_0123456789abcdef")
        assertEquals(ApiResult.Error(0, null, true), result)
    }

    @Test
    fun unparseableErrorBodyGivesNullCode() = runTest {
        server.enqueue(MockResponse().setResponseCode(503).setBody("<html>down</html>"))
        assertEquals(ApiResult.Error(503, null, true), api().getJob("job_x"))
        server.enqueue(MockResponse().setResponseCode(400).setBody("nope"))
        assertEquals(ApiResult.Error(400, null, false), api().getJob("job_x"))
    }

    /** Opt-in smoke against the deployed backend. No paid calls: anonymous auth + one GET. */
    @Test
    fun liveSmokeGetJobNotFound() = runTest {
        Assume.assumeTrue("set DRIPPOP_LIVE_SMOKE=1 to run", "1" == System.getenv("DRIPPOP_LIVE_SMOKE"))
        val liveAuth = SupabaseAnonAuth(
            http,
            System.getenv("SUPABASE_URL")!!,
            System.getenv("SUPABASE_PUBLISHABLE_KEY")!!,
            MapTokenStore(),
        )
        val liveApi = HttpDripPopApi(System.getenv("DRIPPOP_API_BASE_URL")!!, liveAuth, http)
        val result = liveApi.getJob("job_zzzzzzzzzzzzzzzzzzzz")
        assertNotNull(result)
        val error = result as ApiResult.Error
        assertEquals(404, error.httpStatus)
        assertEquals("not_found", error.code)
    }
}
