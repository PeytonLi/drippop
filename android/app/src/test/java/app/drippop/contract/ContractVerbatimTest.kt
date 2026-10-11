package app.drippop.contract

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/** Guards that app.drippop.contract.* is byte-for-byte the frozen block in contracts/interfaces/android.md. */
class ContractVerbatimTest {
    @Test
    fun contractSourceMatchesFrozenInterfaceDoc() {
        val root = File(System.getProperty("drippop.repoRoot") ?: error("drippop.repoRoot not set"))
        val doc = File(root, "contracts/interfaces/android.md").readText()
        val block = Regex("```kotlin\\n(.*?)```", RegexOption.DOT_MATCHES_ALL).find(doc)!!.groupValues[1]
        val source = File(root, "android/app/src/main/java/app/drippop/contract/Contracts.kt").readText()
        assertEquals(block, source)
    }
}
