package app.drippop.platform.fake

import android.content.res.AssetManager

/** Reads contract fixtures copied into assets/fixtures by the copyContractFixtures Gradle task. */
class AssetFixtureSource(private val assets: AssetManager) : FixtureSource {
    override fun read(name: String): String =
        assets.open("fixtures/$name").bufferedReader().use { it.readText() }
}
