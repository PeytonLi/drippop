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

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.robolectric)
}
