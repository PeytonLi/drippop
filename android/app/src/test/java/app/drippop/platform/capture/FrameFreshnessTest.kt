package app.drippop.platform.capture

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FrameFreshnessTest {
    private val now = 50_000_000_000L
    private val hidden = now - 150_000_000L

    @Test fun heldFrameComposedAfterHideIsUsable() {
        assertTrue(FrameFreshness.heldFrameUsable(hidden + 16_000_000L, hidden, now))
    }

    @Test fun heldFrameComposedAtHideInstantIsUsable() {
        assertTrue(FrameFreshness.heldFrameUsable(hidden, hidden, now))
    }

    @Test fun heldFrameComposedBeforeHideIsRejected() {
        assertFalse(FrameFreshness.heldFrameUsable(hidden - 1, hidden, now))
    }

    @Test fun heldFrameWithImplausibleClockIsRejected() {
        assertFalse(FrameFreshness.heldFrameUsable(0L, hidden, now))
        assertFalse(FrameFreshness.heldFrameUsable(now + 20_000_000_000L, hidden, now))
    }

    @Test fun awaitedFrameAfterThresholdIsAccepted() {
        assertTrue(FrameFreshness.awaitedFrameAccepted(now, now - 1, now))
    }

    @Test fun awaitedFrameBeforeThresholdIsRejected() {
        assertFalse(FrameFreshness.awaitedFrameAccepted(now - 10, now - 1, now))
    }

    @Test fun awaitedFrameWithImplausibleClockIsAcceptedInsteadOfHanging() {
        assertTrue(FrameFreshness.awaitedFrameAccepted(0L, now - 1, now))
    }
}
