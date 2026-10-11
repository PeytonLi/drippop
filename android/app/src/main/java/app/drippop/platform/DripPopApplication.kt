package app.drippop.platform

import android.app.Application
import android.content.Context
import app.drippop.contract.CaptureSessionState
import app.drippop.contract.DripPopApi
import app.drippop.platform.fake.AssetFixtureSource
import app.drippop.platform.fake.FakeDripPopApi
import app.drippop.platform.fake.FakeResultRenderer
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

/** Process-wide singletons. Stage 1 wires the fake API only; no network or provider exists yet. */
class AppGraph(context: Context) {
    val sessionState = MutableStateFlow(CaptureSessionState.OFF)
    val photoStore = PersonalPhotoStore(context)
    val api: DripPopApi = FakeDripPopApi(
        fixtures = AssetFixtureSource(context.assets),
        renderResult = FakeResultRenderer::render,
        pollsUntilSuccess = 2,
        latencyMs = 700,
    )
    val isFakeApi: Boolean = true
}

val Context.graph: AppGraph get() = (applicationContext as DripPopApplication).graph
