package app.drippop.platform.fake

import app.drippop.contract.ApiResult
import app.drippop.contract.CapturedFrame
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class FakeDripPopApiTest {
    private val root = File(System.getProperty("drippop.repoRoot")!!)
    private val fixtures = FixtureSource { name -> File(root, "contracts/fixtures/valid/$name").readText() }
    private val frame = CapturedFrame("f1", byteArrayOf(1, 2, 3), "image/jpeg", 1080, 1920, 1L)
    private val person = frame.copy(frameId = "person")

    private fun api() = FakeDripPopApi(fixtures, renderResult = { _, _ -> byteArrayOf(9, 9) }, pollsUntilSuccess = 2)

    private fun ApiResult<String>.ok(): String = (this as ApiResult.Ok).value
    private fun jobId(json: String) = Regex("\"job_id\"\\s*:\\s*\"([^\"]+)\"").find(json)!!.groupValues[1]
    private fun status(json: String) = Regex("\"status\"\\s*:\\s*\"([^\"]+)\"").find(json)!!.groupValues[1]

    @Test
    fun detectReturnsTheBasicContractFixture() = runTest {
        val json = api().detect(frame).ok()
        assertEquals(fixtures.read("detection_response.basic.json"), json)
    }

    @Test
    fun detectRejectsEmptyFrame() = runTest {
        val r = api().detect(frame.copy(bytes = ByteArray(0)))
        assertEquals(ApiResult.Error(400, "invalid_image", false), r)
    }

    @Test
    fun jobAdvancesQueuedProcessingSucceededThenServesResult() = runTest {
        val api = api()
        val created = api.createJob("key-0123456789abcdef", person, frame, "upper_body").ok()
        assertEquals("queued", status(created))
        val id = jobId(created)
        assertTrue(Regex("^[A-Za-z0-9_-]{16,64}$").matches(id))
        assertEquals(ApiResult.Error(409, "result_not_ready", true), api.getResult(id))
        assertEquals("processing", status(api.getJob(id).ok()))
        val done = api.getJob(id).ok()
        assertEquals("succeeded", status(done))
        assertEquals(id, jobId(done))
        assertTrue((api.getResult(id) as ApiResult.Ok).value.contentEquals(byteArrayOf(9, 9)))
    }

    @Test
    fun sameKeySameInputsReturnsSameJob() = runTest {
        val api = api()
        val a = jobId(api.createJob("key-0123456789abcdef", person, frame, "upper_body").ok())
        val b = jobId(api.createJob("key-0123456789abcdef", person, frame, "upper_body").ok())
        assertEquals(a, b)
    }

    @Test
    fun sameKeyChangedInputsConflicts() = runTest {
        val api = api()
        api.createJob("key-0123456789abcdef", person, frame, "upper_body")
        assertEquals(
            ApiResult.Error(409, "idempotency_conflict", false),
            api.createJob("key-0123456789abcdef", person, frame, "full_body"),
        )
    }

    @Test
    fun secondActiveJobWithNewKeyIsRejected() = runTest {
        val api = api()
        api.createJob("key-0123456789abcdef", person, frame, "upper_body")
        assertEquals(
            ApiResult.Error(409, "active_job_exists", false),
            api.createJob("key-fedcba9876543210", person, frame, "upper_body"),
        )
    }

    @Test
    fun categoryOutsideFakeModeIsUnavailable() = runTest {
        assertEquals(
            ApiResult.Error(422, "category_unavailable", false),
            api().createJob("key-0123456789abcdef", person, frame, "lower_body"),
        )
    }

    @Test
    fun fakeModeCategoriesMatchContractConfig() {
        val cfg = File(root, "contracts/config/categories.json").readText()
        val block = Regex("\"fake_mode_enabled\"\\s*:\\s*\\[(.*?)]", RegexOption.DOT_MATCHES_ALL).find(cfg)!!.groupValues[1]
        val expected = Regex("\"([a-z_]+)\"").findAll(block).map { it.groupValues[1] }.toSet()
        assertEquals(expected, FakeDripPopApi.FAKE_MODE_CATEGORIES)
    }

    @Test
    fun deleteCancelsAndFreesTheActiveSlot() = runTest {
        val api = api()
        val id = jobId(api.createJob("key-0123456789abcdef", person, frame, "upper_body").ok())
        assertEquals("canceled", status(api.deleteJob(id).ok()))
        assertEquals("canceled", status(api.getJob(id).ok()))
        assertEquals(ApiResult.Error(409, "job_canceled", false), api.getResult(id))
        // replaying the canceled key never regenerates
        assertEquals(id, jobId(api.createJob("key-0123456789abcdef", person, frame, "upper_body").ok()))
        assertEquals("canceled", status(api.getJob(id).ok()))
        val second = jobId(api.createJob("key-fedcba9876543210", person, frame, "upper_body").ok())
        assertNotEquals(id, second)
    }

    @Test
    fun unknownJobIsNotFound() = runTest {
        assertEquals(ApiResult.Error(404, "not_found", false), api().getJob("job_doesnotexist0000"))
    }
}
