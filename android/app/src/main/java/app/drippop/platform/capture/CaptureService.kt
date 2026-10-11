package app.drippop.platform.capture

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjectionManager
import android.os.IBinder
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import app.drippop.R
import app.drippop.contract.CaptureSessionState
import app.drippop.platform.graph
import app.drippop.platform.onboarding.MainActivity
import app.drippop.platform.overlay.DevTryOnHarness
import app.drippop.platform.overlay.OverlayController
import app.drippop.platform.tile.DripPopTileService

/**
 * Foreground service (type mediaProjection) that owns exactly one capture session plus the overlay.
 * Stop (notification, tile, panel), projection stop, screen off and process death all end the session;
 * nothing restarts it silently (START_NOT_STICKY). A cloud job does not keep this service alive.
 */
class CaptureService : LifecycleService() {

    private var session: ScreenCaptureSession? = null
    private var overlay: OverlayController? = null
    private var harness: DevTryOnHarness? = null
    private var screenOffRegistered = false

    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == Intent.ACTION_SCREEN_OFF) stopSession()
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        when (intent?.action) {
            ACTION_START -> start(intent)
            ACTION_STOP -> stopSession()
            else -> stopSession()
        }
        return START_NOT_STICKY
    }

    private fun start(intent: Intent) {
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
        val data = intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        if (resultCode != Activity.RESULT_OK || data == null) {
            stopSession()
            return
        }
        teardown()
        // Android 14+: startForeground with the mediaProjection type before getMediaProjection().
        startForeground(NOTIFICATION_ID, buildNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        val mpm = getSystemService(MediaProjectionManager::class.java)
        val projection = mpm.getMediaProjection(resultCode, data)
        if (projection == null) {
            stopSession()
            return
        }
        val overlay = OverlayController(this)
        val state = graph.sessionState
        val session = ScreenCaptureSession(
            context = this,
            projection = projection,
            sessionState = state,
            setWindowsHidden = { hidden -> overlay.setHiddenForCapture(hidden) },
            onSourceVisibilityChanged = { visible -> ContextCompat.getMainExecutor(this).execute { harness?.onSourceVisible(visible) } },
            onStopped = { ContextCompat.getMainExecutor(this).execute { stopSession() } },
        )
        this.overlay = overlay
        this.session = session
        harness = DevTryOnHarness(this, lifecycleScope, session, overlay, graph.api, graph.photoStore, graph.isFakeApi) { stopSession() }
            .also { overlay.attachHarness(it) }
        session.start()
        ContextCompat.registerReceiver(this, screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
        screenOffRegistered = true
        overlay.showBubble()
        DripPopTileService.requestUpdate(this)
    }

    private fun teardown() {
        harness?.dispose()
        harness = null
        overlay?.removeAll()
        overlay = null
        session?.stop()
        session = null
        if (screenOffRegistered) {
            unregisterReceiver(screenOff)
            screenOffRegistered = false
        }
    }

    private fun stopSession() {
        val wasRunning = session != null
        teardown()
        if (wasRunning || graph.sessionState.value == CaptureSessionState.ACTIVE) {
            graph.sessionState.value = CaptureSessionState.STOPPED
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
        DripPopTileService.requestUpdate(this)
    }

    override fun onDestroy() {
        teardown()
        if (graph.sessionState.value == CaptureSessionState.ACTIVE) graph.sessionState.value = CaptureSessionState.STOPPED
        super.onDestroy()
    }

    override fun onBind(intent: Intent): IBinder? {
        super.onBind(intent)
        return null
    }

    private fun buildNotification(): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, getString(R.string.notification_channel_name), NotificationManager.IMPORTANCE_LOW),
        )
        val stop = PendingIntent.getService(this, 1, stopIntent(this), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val open = PendingIntent.getActivity(
            this, 2, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_tile)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(getString(R.string.notification_text))
            .setOngoing(true)
            .setContentIntent(open)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .addAction(Notification.Action.Builder(null, getString(R.string.notification_stop), stop).build())
            .build()
    }

    companion object {
        private const val ACTION_START = "app.drippop.capture.START"
        private const val ACTION_STOP = "app.drippop.capture.STOP"
        private const val EXTRA_RESULT_CODE = "resultCode"
        private const val EXTRA_RESULT_DATA = "resultData"
        private const val CHANNEL_ID = "capture_session"
        private const val NOTIFICATION_ID = 41

        fun startIntent(context: Context, resultCode: Int, data: Intent): Intent =
            Intent(context, CaptureService::class.java).setAction(ACTION_START)
                .putExtra(EXTRA_RESULT_CODE, resultCode)
                .putExtra(EXTRA_RESULT_DATA, data)

        fun stopIntent(context: Context): Intent = Intent(context, CaptureService::class.java).setAction(ACTION_STOP)
    }
}
