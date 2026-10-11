package app.drippop.platform.fake

import app.drippop.contract.ApiResult
import app.drippop.contract.CapturedFrame
import app.drippop.contract.DripPopApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.security.MessageDigest
import java.util.UUID

/** Reads a contracts/fixtures/valid JSON fixture by file name. */
fun interface FixtureSource {
    fun read(name: String): String
}

/**
 * Dev/demo-only [DripPopApi] that answers with the frozen contract fixtures. Never talks to a network
 * or provider. Results come from [renderResult], which must visibly mark output as FAKE PREVIEW.
 *
 * Mimics the documented server rules that matter to the client: per-key idempotency with a request
 * fingerprint, one active job, fake-mode categories, cancel tombstones and result readiness.
 */
class FakeDripPopApi(
    private val fixtures: FixtureSource,
    private val renderResult: (person: CapturedFrame, reference: CapturedFrame) -> ByteArray,
    private val pollsUntilSuccess: Int = 2,
    private val latencyMs: Long = 0,
) : DripPopApi {

    companion object {
        /** Mirrors contracts/config/categories.json `fake_mode_enabled` (asserted by unit test). */
        val FAKE_MODE_CATEGORIES = setOf("upper_body", "full_body")
        private const val FIXTURE_JOB_ID = "job_7Qm2xK9pL4vN8rT1"
    }

    private enum class Status { QUEUED, PROCESSING, SUCCEEDED, CANCELED }

    private class Job(
        val id: String,
        val fingerprint: String,
        val person: CapturedFrame,
        val reference: CapturedFrame,
        var status: Status = Status.QUEUED,
        var polls: Int = 0,
    )

    private val mutex = Mutex()
    private val jobsByKey = mutableMapOf<String, Job>()
    private val jobsById = mutableMapOf<String, Job>()

    override suspend fun detect(frame: CapturedFrame): ApiResult<String> {
        simulateLatency()
        if (frame.bytes.isEmpty() || frame.width <= 0 || frame.height <= 0) {
            return ApiResult.Error(400, "invalid_image", false)
        }
        return ApiResult.Ok(fixtures.read("detection_response.basic.json"))
    }

    override suspend fun createJob(
        idempotencyKey: String,
        person: CapturedFrame,
        reference: CapturedFrame,
        category: String,
    ): ApiResult<String> {
        simulateLatency()
        return mutex.withLock {
            val fingerprint = fingerprint(person, reference, category)
            jobsByKey[idempotencyKey]?.let { existing ->
                return@withLock if (existing.fingerprint == fingerprint) {
                    ApiResult.Ok(render(existing))
                } else {
                    ApiResult.Error(409, "idempotency_conflict", false)
                }
            }
            if (category !in FAKE_MODE_CATEGORIES) return@withLock ApiResult.Error(422, "category_unavailable", false)
            if (jobsById.values.any { it.status == Status.QUEUED || it.status == Status.PROCESSING }) {
                return@withLock ApiResult.Error(409, "active_job_exists", false)
            }
            val job = Job(
                id = "job_fake_" + UUID.randomUUID().toString().replace("-", "").take(16),
                fingerprint = fingerprint,
                person = person,
                reference = reference,
            )
            jobsByKey[idempotencyKey] = job
            jobsById[job.id] = job
            ApiResult.Ok(render(job))
        }
    }

    override suspend fun getJob(jobId: String): ApiResult<String> {
        simulateLatency()
        return mutex.withLock {
            val job = jobsById[jobId] ?: return@withLock ApiResult.Error(404, "not_found", false)
            if (job.status == Status.QUEUED || job.status == Status.PROCESSING) {
                job.polls++
                job.status = if (job.polls >= pollsUntilSuccess) Status.SUCCEEDED else Status.PROCESSING
            }
            ApiResult.Ok(render(job))
        }
    }

    override suspend fun getResult(jobId: String): ApiResult<ByteArray> {
        simulateLatency()
        val job = mutex.withLock { jobsById[jobId] } ?: return ApiResult.Error(404, "not_found", false)
        return when (job.status) {
            Status.SUCCEEDED -> ApiResult.Ok(renderResult(job.person, job.reference))
            Status.CANCELED -> ApiResult.Error(409, "job_canceled", false)
            // Contract defines 409 result_not_ready (retryable) while queued/processing.
            else -> ApiResult.Error(409, "result_not_ready", true)
        }
    }

    override suspend fun deleteJob(jobId: String): ApiResult<String> {
        simulateLatency()
        return mutex.withLock {
            val job = jobsById[jobId] ?: return@withLock ApiResult.Error(404, "not_found", false)
            job.status = Status.CANCELED
            ApiResult.Ok(render(job))
        }
    }

    private fun render(job: Job): String {
        val fixture = when (job.status) {
            Status.QUEUED -> "job_response.queued.json"
            Status.PROCESSING -> "job_response.generating.json"
            Status.SUCCEEDED -> "job_response.succeeded.json"
            Status.CANCELED -> "job_response.canceled.json"
        }
        return fixtures.read(fixture).replace(FIXTURE_JOB_ID, job.id)
    }

    private fun fingerprint(person: CapturedFrame, reference: CapturedFrame, category: String): String {
        val md = MessageDigest.getInstance("SHA-256")
        md.update(person.bytes)
        md.update(0)
        md.update(reference.bytes)
        md.update(0)
        md.update(category.toByteArray())
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    private suspend fun simulateLatency() {
        if (latencyMs > 0) delay(latencyMs)
    }
}
