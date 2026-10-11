package app.drippop.platform.net

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SupabaseAnonAuthTest {
    private val server = MockWebServer()
    private val http = OkHttpClient()
    private val store = MapTokenStore()
    private var nowMs = 1_700_000_000_000L

    private fun auth() = SupabaseAnonAuth(http, server.url("/").toString().trimEnd('/'), "pub-key", store, { nowMs })

    @Before
    fun start() = server.start()

    @After
    fun stop() = server.shutdown()

    private fun tokenResponse(access: String, refresh: String = "r-$access", expiresIn: Long = 3600) =
        MockResponse().setResponseCode(200).setBody(
            JSONObject()
                .put("access_token", access)
                .put("refresh_token", refresh)
                .put("expires_in", expiresIn)
                .toString(),
        )

    @Test
    fun signupWhenStoreEmpty() = runTest {
        server.enqueue(tokenResponse("a1"))
        assertEquals("a1", auth().accessToken())
        val req = server.takeRequest()
        assertEquals("/auth/v1/signup", req.path)
        assertEquals("pub-key", req.getHeader("apikey"))
    }

    @Test
    fun cachedTokenReusedWithoutRequest() = runTest {
        store.put("access_token", "cached")
        store.put("expires_at", ((nowMs / 1000) + 600).toString())
        assertEquals("cached", auth().accessToken())
        assertEquals(0, server.requestCount)
    }

    @Test
    fun refreshWithinSixtySecondsOfExpiry() = runTest {
        store.put("access_token", "stale")
        store.put("expires_at", ((nowMs / 1000) + 30).toString())
        store.put("refresh_token", "r0")
        server.enqueue(tokenResponse("fresh"))
        assertEquals("fresh", auth().accessToken())
        val req = server.takeRequest()
        assertEquals("/auth/v1/token?grant_type=refresh_token", req.path)
        assertEquals("""{"refresh_token":"r0"}""", req.body.readUtf8())
    }

    @Test
    fun refreshRejectionFallsBackToSignup() = runTest {
        store.put("access_token", "stale")
        store.put("expires_at", "0")
        store.put("refresh_token", "r0")
        server.enqueue(MockResponse().setResponseCode(400))
        server.enqueue(tokenResponse("signed-up"))
        assertEquals("signed-up", auth().accessToken())
        assertEquals("/auth/v1/token?grant_type=refresh_token", server.takeRequest().path)
        assertEquals("/auth/v1/signup", server.takeRequest().path)
    }

    @Test
    fun apikeyHeaderIsSent() = runTest {
        server.enqueue(tokenResponse("a1"))
        auth().accessToken()
        assertEquals("pub-key", server.takeRequest().getHeader("apikey"))
    }

    @Test
    fun networkFailureReturnsNull() = runTest {
        server.shutdown()
        assertNull(auth().accessToken())
    }
}

class MapTokenStore : TokenStore {
    private val map = mutableMapOf<String, String>()
    override fun get(key: String): String? = map[key]
    override fun put(key: String, value: String) {
        map[key] = value
    }
    override fun clear() = map.clear()
}
