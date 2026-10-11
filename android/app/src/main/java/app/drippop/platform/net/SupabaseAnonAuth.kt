package app.drippop.platform.net

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/** Persists the anonymous Supabase session. Never log token values. */
interface TokenStore {
    fun get(key: String): String?
    fun put(key: String, value: String)
    fun clear()
}

/** SharedPreferences-backed TokenStore. Backups are disabled app-wide (allowBackup=false). */
class PrefsTokenStore(context: Context) : TokenStore {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("drippop_auth", Context.MODE_PRIVATE)

    override fun get(key: String): String? = prefs.getString(key, null)

    override fun put(key: String, value: String) {
        prefs.edit { putString(key, value) }
    }

    override fun clear() {
        prefs.edit { clear() }
    }
}

/**
 * Anonymous Supabase auth: reuses a cached access token, refreshes it near expiry,
 * and signs up a fresh anonymous user when no usable refresh token remains.
 * Returns null on network failure; the caller maps that to a retryable error.
 */
class SupabaseAnonAuth(
    private val http: OkHttpClient,
    private val supabaseUrl: String,
    private val publishableKey: String,
    private val store: TokenStore,
    private val nowMs: () -> Long = System::currentTimeMillis,
) {
    private val mutex = Mutex()

    private sealed class AuthOutcome {
        data class Ok(val accessToken: String) : AuthOutcome()
        /** Server answered 400/401 or an unusable body. */
        data object Rejected : AuthOutcome()
        /** Transport failure: nothing was learned about the token's validity. */
        data object NetworkError : AuthOutcome()
    }

    suspend fun accessToken(forceRefresh: Boolean = false): String? = mutex.withLock {
        val nowS = nowMs() / 1000
        val cached = store.get(KEY_ACCESS)
        val expiresAt = store.get(KEY_EXPIRES_AT)?.toLongOrNull() ?: 0L
        if (!forceRefresh && cached != null && expiresAt - nowS > REFRESH_MARGIN_S) {
            return@withLock cached
        }
        val refresh = store.get(KEY_REFRESH)
        if (refresh != null) {
            when (val outcome = requestToken("token?grant_type=refresh_token", """{"refresh_token":"$refresh"}""")) {
                is AuthOutcome.Ok -> return@withLock outcome.accessToken
                AuthOutcome.NetworkError -> return@withLock null
                AuthOutcome.Rejected -> Unit // fall through to signup
            }
        }
        return@withLock when (val outcome = requestToken("signup", "{}")) {
            is AuthOutcome.Ok -> outcome.accessToken
            else -> null
        }
    }

    private suspend fun requestToken(path: String, bodyJson: String): AuthOutcome =
        withContext(Dispatchers.IO) {
            runCatching {
                val request = Request.Builder()
                    .url("$supabaseUrl/auth/v1/$path")
                    .header("apikey", publishableKey)
                    .post(bodyJson.toRequestBody(JSON))
                    .build()
                http.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) {
                        // Only a definitive auth rejection falls through to signup;
                        // 429/5xx/anything else is transient and must keep the session.
                        if (response.code == 400 || response.code == 401 || response.code == 403) {
                            AuthOutcome.Rejected
                        } else {
                            AuthOutcome.NetworkError
                        }
                    } else {
                        val body = response.body?.string().orEmpty()
                        val json = runCatching { JSONObject(body) }.getOrNull()
                        val access = json?.optString("access_token")?.takeIf { it.isNotEmpty() }
                        if (access == null) {
                            AuthOutcome.Rejected
                        } else {
                            store.put(KEY_ACCESS, access)
                            json.optString("refresh_token").takeIf { it.isNotEmpty() }
                                ?.let { store.put(KEY_REFRESH, it) }
                            val expiresAt = json.optLong("expires_at", 0L)
                            val expiry = if (expiresAt > 0) {
                                expiresAt
                            } else {
                                nowMs() / 1000 + json.optLong("expires_in", 3600)
                            }
                            store.put(KEY_EXPIRES_AT, expiry.toString())
                            AuthOutcome.Ok(access)
                        }
                    }
                }
            }.getOrDefault(AuthOutcome.NetworkError)
        }

    companion object {
        private const val REFRESH_MARGIN_S = 60L
        private const val KEY_ACCESS = "access_token"
        private const val KEY_REFRESH = "refresh_token"
        private const val KEY_EXPIRES_AT = "expires_at"
        private val JSON = "application/json".toMediaType()
    }
}
