package app.drippop.platform.onboarding

import android.Manifest
import android.app.StatusBarManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import app.drippop.R
import app.drippop.contract.CaptureSessionState
import app.drippop.platform.capture.CaptureService
import app.drippop.platform.capture.ProjectionConsentActivity
import app.drippop.platform.graph
import app.drippop.platform.tile.DripPopTileService
import kotlinx.coroutines.launch

/** Onboarding: privacy explanation, personal photo (Photo Picker), overlay + notification permission, start. */
class MainActivity : ComponentActivity() {
    private var resumeTick by mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val accent = Color(0xFFFF5FA2)
            MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme(primary = accent) else lightColorScheme(primary = accent)) {
                Surface(Modifier.fillMaxSize()) { Onboarding(resumeTick) }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        resumeTick++
    }

    @Composable
    private fun Onboarding(tick: Int) {
        val store = graph.photoStore
        val scope = rememberCoroutineScope()
        val session by graph.sessionState.collectAsState()
        var photoVersion by remember { mutableIntStateOf(0) }
        var photoNote by remember { mutableStateOf<String?>(null) }
        val overlayGranted = remember(tick) { Settings.canDrawOverlays(this) }
        var notificationsGranted by remember(tick) {
            mutableStateOf(ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)
        }
        val thumbnail = remember(photoVersion) { store.file()?.let { f -> BitmapFactory.decodeFile(f.path, BitmapFactory.Options().apply { inSampleSize = 4 }) } }

        val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri: Uri? ->
            if (uri != null) scope.launch {
                photoNote = runCatching { store.importFrom(uri) }.fold(
                    onSuccess = { s -> if (s.suitable) "Saved privately (${s.width}x${s.height})." else s.issues.joinToString(" ") },
                    onFailure = { "Couldn't read that image. Pick another photo." },
                )
                photoVersion++
            }
        }
        val notifLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            notificationsGranted = granted
        }

        Column(
            Modifier.safeDrawingPadding().verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("DripPop", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("See the drip. Tap the pop. Try it on.", style = MaterialTheme.typography.titleSmall)
            if (graph.isFakeApi) Text("Stage 1 build: all analysis and previews are FAKE fixtures; nothing is uploaded.", color = MaterialTheme.colorScheme.primary)
            Text(
                "Tapping Try on captures one still of the screen you chose to share and (in real builds) sends it for cloud analysis. " +
                    "Confirming generation sends your personal photo and the selected reference to cloud providers. The feed is never streamed.",
            )

            Step("1. Personal photo") {
                Text("Pick a clear, front-facing standing photo with the clothing region visible. It stays in app-private storage and is excluded from backup.")
                thumbnail?.let { Image(it.asImageBitmap(), "Your personal photo", Modifier.size(120.dp), contentScale = ContentScale.Crop) }
                photoNote?.let { Text(it) }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { picker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, modifier = Modifier.heightIn(min = 48.dp)) {
                        Text(if (store.exists) "Replace photo" else "Choose photo")
                    }
                    if (store.exists) OutlinedButton(onClick = { store.delete(); photoNote = "Deleted."; photoVersion++ }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Delete") }
                }
            }

            Step("2. Display over other apps") {
                Text(if (overlayGranted) "Granted." else "Needed for the floating Try on button and the result panel.")
                if (!overlayGranted) Button(
                    onClick = { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))) },
                    modifier = Modifier.heightIn(min = 48.dp),
                ) { Text("Open overlay settings") }
            }

            Step("3. Notifications") {
                Text(if (notificationsGranted) "Granted." else "Lets the capture-session notification (with Stop) be visible.")
                if (!notificationsGranted) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS) }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Allow") }
                    OutlinedButton(
                        onClick = { startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName)) },
                        modifier = Modifier.heightIn(min = 48.dp),
                    ) { Text("Settings") }
                }
            }

            Step("4. Session") {
                Text("Session: ${session.name.lowercase().replace('_', ' ')}. Android asks for capture consent every session; choose Instagram when offered.")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        enabled = overlayGranted,
                        onClick = { startActivity(Intent(this@MainActivity, ProjectionConsentActivity::class.java)) },
                        modifier = Modifier.heightIn(min = 48.dp),
                    ) { Text("Start try-on session") }
                    if (session == CaptureSessionState.ACTIVE) OutlinedButton(
                        onClick = { startService(CaptureService.stopIntent(this@MainActivity)) },
                        modifier = Modifier.heightIn(min = 48.dp),
                    ) { Text("Stop") }
                }
                OutlinedButton(onClick = ::requestTile, modifier = Modifier.heightIn(min = 48.dp)) { Text("Add Quick Settings tile") }
            }
        }
    }

    @Composable
    private fun Step(title: String, content: @Composable () -> Unit) {
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                content()
            }
        }
    }

    private fun requestTile() {
        getSystemService(StatusBarManager::class.java).requestAddTileService(
            ComponentName(this, DripPopTileService::class.java),
            getString(R.string.tile_label),
            Icon.createWithResource(this, R.drawable.ic_tile),
            mainExecutor,
        ) { }
    }
}
