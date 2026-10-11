package app.drippop.platform.capture

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import app.drippop.contract.CaptureSessionState
import app.drippop.platform.graph
import app.drippop.platform.onboarding.MainActivity

/**
 * User-launched (app button or Quick Settings tile) entry that asks for a *fresh* MediaProjection
 * consent for every session, then hands the one-time result to [CaptureService]. Cancel never loops.
 */
class ProjectionConsentActivity : ComponentActivity() {

    private val consent = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val data = result.data
        if (result.resultCode == Activity.RESULT_OK && data != null) {
            startForegroundService(CaptureService.startIntent(this, result.resultCode, data))
        } else {
            graph.sessionState.value = CaptureSessionState.OFF
            Toast.makeText(this, "Capture not started. Start again from DripPop or the tile.", Toast.LENGTH_LONG).show()
        }
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState?.getBoolean(KEY_LAUNCHED) == true) return
        if (!Settings.canDrawOverlays(this)) {
            startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            finish()
            return
        }
        // A new session always needs new consent: end any running one first.
        if (graph.sessionState.value == CaptureSessionState.ACTIVE) {
            startService(CaptureService.stopIntent(this))
        }
        graph.sessionState.value = CaptureSessionState.REQUESTING_CONSENT
        val mpm = getSystemService(MediaProjectionManager::class.java)
        consent.launch(mpm.createScreenCaptureIntent())
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean(KEY_LAUNCHED, true)
    }

    private companion object {
        const val KEY_LAUNCHED = "launched"
    }
}
