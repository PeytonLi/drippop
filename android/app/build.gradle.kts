import org.gradle.api.file.DirectoryProperty
import org.gradle.api.tasks.OutputDirectory
import org.gradle.api.tasks.InputDirectory
import org.gradle.api.tasks.PathSensitive
import org.gradle.api.tasks.PathSensitivity

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

val repoRoot: File = rootDir.parentFile

android {
    namespace = "app.drippop"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.drippop"
        minSdk = 34
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0-stage1"

        // Live-backend wiring. Values come from -P gradle properties first, then env vars;
        // no endpoints or keys are committed. LIVE_API is true only when all three are set.
        fun prop(name: String): String? = providers.gradleProperty(name).orNull?.takeIf { it.isNotEmpty() }
        fun env(name: String): String? = providers.environmentVariable(name).orNull?.takeIf { it.isNotEmpty() }
        val apiBaseUrl = prop("drippop.apiBaseUrl") ?: env("DRIPPOP_API_BASE_URL") ?: ""
        val supabaseUrl = prop("drippop.supabaseUrl") ?: env("SUPABASE_URL") ?: ""
        val supabasePublishableKey = prop("drippop.supabasePublishableKey") ?: env("SUPABASE_PUBLISHABLE_KEY") ?: ""
        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
        buildConfigField("String", "SUPABASE_URL", "\"$supabaseUrl\"")
        buildConfigField("String", "SUPABASE_PUBLISHABLE_KEY", "\"$supabasePublishableKey\"")
        buildConfigField(
            "boolean",
            "LIVE_API",
            (apiBaseUrl.isNotEmpty() && supabaseUrl.isNotEmpty() && supabasePublishableKey.isNotEmpty()).toString(),
        )
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    testOptions {
        unitTests {
            isIncludeAndroidResources = true
            all {
                it.systemProperty("drippop.repoRoot", repoRoot.absolutePath)
                // Optional: point Robolectric's android-all download at a Maven Central mirror
                // (e.g. -Pdrippop.robolectricRepoUrl=https://maven-central.storage-download.googleapis.com/maven2/).
                providers.gradleProperty("drippop.robolectricRepoUrl").orNull?.let { url ->
                    it.systemProperty("robolectric.dependency.repo.url", url)
                }
            }
        }
    }

    lint {
        abortOnError = true
        checkDependencies = false
    }
}

/** Copies the JSON files in contracts/fixtures/valid into generated assets under fixtures/ for FakeDripPopApi. */
abstract class CopyContractFixtures : DefaultTask() {
    @get:InputDirectory
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val source: DirectoryProperty

    @get:OutputDirectory
    abstract val outputDir: DirectoryProperty

    @TaskAction
    fun copy() {
        val out = outputDir.get().asFile.resolve("fixtures")
        out.deleteRecursively()
        out.mkdirs()
        source.get().asFile.listFiles { f -> f.extension == "json" }!!.sorted().forEach {
            it.copyTo(out.resolve(it.name))
        }
    }
}

val copyContractFixtures = tasks.register<CopyContractFixtures>("copyContractFixtures") {
    source.set(File(repoRoot, "contracts/fixtures/valid"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(copyContractFixtures, CopyContractFixtures::outputDir)
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.androidx.lifecycle.viewmodel)
    implementation(libs.androidx.savedstate.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.compose.material3)
    implementation(libs.kotlinx.coroutines.android)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.okhttp)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.robolectric)
    testImplementation(libs.okhttp.mockwebserver)
}
