package app.drippop.platform

import android.app.Application
import android.content.Context
import app.drippop.contract.CaptureSessionState
import app.drippop.contract.DripPopApi
import app.drippop.platform.fake.AssetFixtureSource
import app.drippop.platform.fake.FakeDripPopApi
import app.drippop.platform.fake.FakeResultRenderer
import app.drippop.BuildConfig
import app.drippop.platform.net.HttpDripPopApi
import app.drippop.platform.net.PrefsTokenStore
import app.drippop.platform.net.SupabaseAnonAuth
import app.drippop.platform.onboarding.PersonalPhotoStore
import kotlinx.coroutines.flow.MutableStateFlow

class DripPopApplication : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
    }
}

/** Process-wide singletons. The real backend is wired only for a LIVE_API build; fake stays the default. */
class AppGraph(context: Context) {
    val sessionState = MutableStateFlow(CaptureSessionState.OFF)
    val photoStore = PersonalPhotoStore(context)
    val api: DripPopApi
    val isFakeApi: Boolean

    init {
        if (BuildConfig.LIVE_API) {
            val http = HttpDripPopApi.defaultClient()
            val auth = SupabaseAnonAuth(
                http = http,
                supabaseUrl = BuildConfig.SUPABASE_URL,
                publishableKey = BuildConfig.SUPABASE_PUBLISHABLE_KEY,
                store = PrefsTokenStore(context),
            )
            api = HttpDripPopApi(BuildConfig.API_BASE_URL, auth, http)
            isFakeApi = false
        } else {
            api = FakeDripPopApi(
                fixtures = AssetFixtureSource(context.assets),
                renderResult = FakeResultRenderer::render,
                pollsUntilSuccess = 2,
                latencyMs = 700,
            )
            isFakeApi = true
        }
    }
}

val Context.graph: AppGraph get() = (applicationContext as DripPopApplication).graph
