package app.drippop.platform.capture

import kotlin.math.abs

/** Decides whether a VirtualDisplay frame (CLOCK_MONOTONIC timestamps) is fresh enough to return. */
internal object FrameFreshness {
    private const val MAX_CLOCK_SKEW_NS = 10_000_000_000L

    fun isPlausible(timestampNs: Long, nowNs: Long): Boolean =
        timestampNs > 0 && abs(nowNs - timestampNs) < MAX_CLOCK_SKEW_NS

    /** The most recent frame already received may be used only if it was composed after our windows were hidden. */
    fun heldFrameUsable(timestampNs: Long, hiddenAtNs: Long, nowNs: Long): Boolean =
        isPlausible(timestampNs, nowNs) && timestampNs >= hiddenAtNs

    /** A newly delivered frame is accepted after the threshold; implausible clocks are accepted rather than hanging. */
    fun awaitedFrameAccepted(timestampNs: Long, thresholdNs: Long, nowNs: Long): Boolean =
        !isPlausible(timestampNs, nowNs) || timestampNs >= thresholdNs
}
