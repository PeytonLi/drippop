package app.drippop.platform.overlay

import android.graphics.RectF
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.res.stringResource
import app.drippop.R
import app.drippop.platform.geometry.DefaultCoordinateMapper

private val Accent = Color(0xFFFF5FA2)

@Composable
private fun OverlayTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme(primary = Accent) else lightColorScheme(primary = Accent)) {
        content()
    }
}

@Composable
internal fun Bubble(harness: DevTryOnHarness, onDrag: (Float, Float) -> Unit) {
    val state by harness.state.collectAsState()
    val label = when (state) {
        HarnessState.Capturing -> "…"
        HarnessState.SourceHidden -> "Paused"
        else -> stringResource(R.string.bubble_label)
    }
    val description = stringResource(R.string.bubble_description)
    OverlayTheme {
        Box(
            modifier = Modifier
                .sizeIn(minWidth = 64.dp, minHeight = 64.dp)
                .background(Accent, CircleShape)
                .pointerInput(Unit) { detectDragGestures { change, drag -> change.consume(); onDrag(drag.x, drag.y) } }
                .clickable(role = Role.Button) { harness.onBubbleTap() }
                .semantics { contentDescription = description }
                .padding(12.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(label, color = Color.White, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
internal fun Panel(harness: DevTryOnHarness) {
    val state by harness.state.collectAsState()
    OverlayTheme {
        Surface(
            modifier = Modifier.fillMaxSize(),
            shape = RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp),
            tonalElevation = 6.dp,
            shadowElevation = 12.dp,
        ) {
            Column(Modifier.padding(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("DripPop", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        Text("Dev harness · FAKE API", style = MaterialTheme.typography.labelSmall, color = Accent)
                    }
                    OutlinedButton(onClick = harness::collapse, modifier = Modifier.heightIn(min = 48.dp)) { Text("Collapse") }
                    Button(onClick = harness.onStopRequested, modifier = Modifier.padding(start = 8.dp).heightIn(min = 48.dp)) { Text("Stop") }
                }
                Box(Modifier.weight(1f).fillMaxWidth().padding(top = 8.dp)) { PanelBody(state, harness) }
            }
        }
    }
}

@Composable
private fun PanelBody(state: HarnessState, harness: DevTryOnHarness) {
    when (state) {
        HarnessState.Idle -> Centered("Tap Try on over a post or a paused reel to capture one still.")
        HarnessState.Capturing -> Progress("Capturing a fresh still…", Modifier.fillMaxSize())
        HarnessState.SourceHidden -> Centered("Return to the shared app to continue, or stop and start a new session.")
        is HarnessState.Error -> Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxSize()) {
            Text(state.message, modifier = Modifier.padding(16.dp))
            Button(onClick = harness::captureNew, modifier = Modifier.heightIn(min = 48.dp)) { Text("Try again") }
        }
        is HarnessState.Analyzing -> Column(Modifier.fillMaxSize()) {
            FrameWithBoxes(state.bitmap, state.frame.width, state.frame.height, emptyList(), null, {}, Modifier.weight(1f))
            Progress("Analyzing (fake detection)…", Modifier.height(56.dp))
        }
        is HarnessState.Selecting -> Column(Modifier.fillMaxSize()) {
            FrameWithBoxes(state.bitmap, state.frame.width, state.frame.height, state.candidates, state.selected, harness::select, Modifier.weight(1f))
            Row(Modifier.horizontalScroll(rememberScrollState()).padding(vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                state.candidates.forEach { c ->
                    FilterChip(selected = state.selected == c, onClick = { harness.select(c) }, label = { Text("${c.garmentId} · ${c.category}") }, modifier = Modifier.heightIn(min = 48.dp))
                }
                FilterChip(
                    selected = state.selected == DevTryOnHarness.WHOLE_FRAME,
                    onClick = { harness.select(DevTryOnHarness.WHOLE_FRAME) },
                    label = { Text("Manual: whole frame") },
                    modifier = Modifier.heightIn(min = 48.dp),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = harness::captureNew, modifier = Modifier.heightIn(min = 48.dp)) { Text("New capture") }
                Button(onClick = harness::generate, enabled = state.selected != null, modifier = Modifier.heightIn(min = 48.dp)) { Text("Generate preview") }
            }
        }
        is HarnessState.Generating -> Column(Modifier.fillMaxSize()) {
            FrameWithBoxes(state.bitmap, state.frame.width, state.frame.height, emptyList(), null, {}, Modifier.weight(1f))
            Progress("Fake job: ${state.phase}", Modifier.height(56.dp))
        }
        is HarnessState.Ready -> Column(Modifier.fillMaxSize()) {
            Text("FAKE PREVIEW — fixture flow, not a real try-on", color = Accent, fontWeight = FontWeight.Bold)
            Row(Modifier.weight(1f).fillMaxWidth().padding(vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Labeled("Source", Modifier.weight(1f)) { Image(state.reference.asImageBitmap(), "Source reference crop", Modifier.fillMaxSize(), contentScale = ContentScale.Fit) }
                Labeled("Preview", Modifier.weight(1f)) { Image(state.result.asImageBitmap(), "Fake preview result", Modifier.fillMaxSize(), contentScale = ContentScale.Fit) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = harness::reset, modifier = Modifier.heightIn(min = 48.dp)) { Text("Discard") }
                Button(onClick = harness::captureNew, modifier = Modifier.heightIn(min = 48.dp)) { Text("New capture") }
            }
        }
    }
}

@Composable
private fun FrameWithBoxes(
    bitmap: android.graphics.Bitmap,
    width: Int,
    height: Int,
    candidates: List<Candidate>,
    selected: Candidate?,
    onSelect: (Candidate) -> Unit,
    modifier: Modifier,
) {
    BoxWithConstraints(modifier.fillMaxWidth()) {
        val wPx = constraints.maxWidth
        val hPx = constraints.maxHeight
        val mapper = DefaultCoordinateMapper(width, height)
        val rects: List<Pair<Candidate, RectF>> = if (wPx > 0 && hPx > 0) candidates.map { it to mapper.imageToView(it.box, wPx, hPx) } else emptyList()
        Image(bitmap.asImageBitmap(), "Captured still", Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
        Canvas(
            Modifier.fillMaxSize().pointerInput(rects) {
                detectTapGestures { p -> rects.lastOrNull { it.second.contains(p.x, p.y) }?.let { onSelect(it.first) } }
            },
        ) {
            rects.forEach { (c, r) ->
                drawRect(
                    color = if (c == selected) Accent else Color.White,
                    topLeft = Offset(r.left, r.top),
                    size = Size(r.width(), r.height()),
                    style = Stroke(width = if (c == selected) 6f else 3f),
                )
            }
        }
    }
}

@Composable
private fun Labeled(label: String, modifier: Modifier, content: @Composable () -> Unit) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Box(Modifier.weight(1f).fillMaxWidth()) { content() }
    }
}

@Composable
private fun Centered(text: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text(text, modifier = Modifier.padding(16.dp)) }
}

@Composable
private fun Progress(text: String, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
        CircularProgressIndicator(Modifier.size(24.dp))
        Text(text, modifier = Modifier.padding(start = 12.dp))
    }
}
