package app.drippop.platform.tile

import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import app.drippop.contract.CaptureSessionState
import app.drippop.platform.capture.CaptureService
import app.drippop.platform.capture.ProjectionConsentActivity
import app.drippop.platform.graph

/** Quick Settings tile: starts the consent flow (Android 14+ PendingIntent route) or stops the session. */
class DripPopTileService : TileService() {

    override fun onStartListening() {
        super.onStartListening()
        val tile = qsTile ?: return
        val active = graph.sessionState.value == CaptureSessionState.ACTIVE
        tile.state = if (active) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        tile.subtitle = if (active) "Session on" else "Off"
        tile.updateTile()
    }

    override fun onClick() {
        super.onClick()
        if (graph.sessionState.value == CaptureSessionState.ACTIVE) {
            startService(CaptureService.stopIntent(this))
            return
        }
        val pending = PendingIntent.getActivity(
            this, 0,
            Intent(this, ProjectionConsentActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        // Never expose setup/preview over the lock screen: unlock first.
        if (isLocked) unlockAndRun { startActivityAndCollapse(pending) } else startActivityAndCollapse(pending)
    }

    companion object {
        fun requestUpdate(context: Context) {
            requestListeningState(context, ComponentName(context, DripPopTileService::class.java))
        }
    }
}
