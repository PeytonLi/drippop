# Android build runbook (lane 1A)

Reproduces `./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug` on a clean Linux x86_64 VM
(verified on Ubuntu 22.04, 2026-10-11). Everything below runs as a normal user; only the JDK install and the
emulator `/dev/kvm` permission need sudo.

## Pinned toolchain

| Component | Version | Where it is pinned |
|---|---|---|
| JDK | OpenJDK 17 (`17.0.19`, Ubuntu `openjdk-17-jdk`) | `compileOptions` in `android/app/build.gradle.kts` |
| Gradle | 9.8.1 (wrapper, SHA-256 checked) | `android/gradle/wrapper/gradle-wrapper.properties` |
| AGP | 9.4.1 | `android/gradle/libs.versions.toml` |
| Kotlin / Compose compiler plugin | 2.4.21 | `libs.versions.toml` |
| Compose BOM | 2026.06.01 | `libs.versions.toml` |
| compileSdk / targetSdk / minSdk | 36 / 36 / 34 | `android/app/build.gradle.kts` (D-002) |
| SDK packages | `platforms;android-36`, `build-tools;36.0.0`, `platform-tools` (37.0.1) | installed by `sdkmanager` below |
| cmdline-tools | 23.0 | downloaded zip below |

Version sources are recorded at the top of `libs.versions.toml` (Google Maven `maven-metadata.xml`, Maven
Central metadata, developer.android.com release notes, checked 2026-10-11). Context7 was attempted first and
returned "Monthly quota exceeded", so official docs/metadata were used instead.

AGP 9 has built-in Kotlin support, so there is no `org.jetbrains.kotlin.android` plugin; only
`org.jetbrains.kotlin.plugin.compose` is applied.

## 1. JDK 17

```bash
sudo apt-get update && sudo apt-get install -y openjdk-17-jdk unzip
java -version   # openjdk version "17.0.x"
```

## 2. Android SDK (command-line only)

```bash
export ANDROID_HOME="$HOME/android-sdk"
mkdir -p "$ANDROID_HOME/cmdline-tools"
# Verified 2026-10-11 (cmdline-tools 23.0). Newer builds: https://developer.android.com/studio#command-line-tools-only
curl -fL --retry 5 --retry-delay 10 -o /tmp/clt.zip \
  https://dl.google.com/android/repository/commandlinetools-linux-16111833_latest.zip
echo "e025545c62a8e64c7559119566a569fb1dec5f60  /tmp/clt.zip" | sha1sum -c -
unzip -q /tmp/clt.zip -d "$ANDROID_HOME/cmdline-tools"
mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
yes | sdkmanager --licenses >/dev/null
sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"
echo "sdk.dir=$ANDROID_HOME" > android/local.properties   # or keep ANDROID_HOME exported
```

`local.properties` is git-ignored. AGP also auto-downloads missing SDK packages once licenses are accepted.

## 3. Build, test, lint

```bash
cd android
./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
```

Expected: `BUILD SUCCESSFUL`, 32 unit tests (contract verbatim check, CoordinateMath, DefaultCoordinateMapper
under Robolectric, FakeDripPopApi), lint `0 errors` (remaining warnings are newer-version notices for the
D-002 pins plus KTX style hints).

`copyContractFixtures` copies `contracts/fixtures/valid/*.json` into generated assets for the fake API, and
`ContractVerbatimTest` fails if `app.drippop.contract` drifts from `contracts/interfaces/android.md`.

## Maven Central HTTP 429 workaround

Some cloud VMs get `429 Too Many Requests` from `repo.maven.apache.org` (seen on 2026-10-11). Gradle's own
retries are not enough. Use Google's Maven Central mirror via a **user-level** init script (never commit it):

```bash
mkdir -p ~/.gradle/init.d
cat > ~/.gradle/init.d/maven-central-mirror.init.gradle.kts <<'EOF'
val mirror = "https://maven-central.storage-download.googleapis.com/maven2/"
beforeSettings {
    pluginManagement.repositories { maven(mirror) }
    dependencyResolutionManagement.repositories { maven(mirror) }
}
EOF
```

Robolectric downloads its `android-all` jar from Maven Central at test time; if that 429s too, pass the mirror:
`./gradlew :app:testDebugUnitTest -Pdrippop.robolectricRepoUrl=https://maven-central.storage-download.googleapis.com/maven2/`.

For `dl.google.com` failures use `curl --retry 5 --retry-delay 10` (above) and re-run `sdkmanager`; it
resumes partial downloads.

## Emulator (dev-only evidence)

```bash
sudo chmod 666 /dev/kvm          # or add the user to the kvm group
sdkmanager "emulator" "system-images;android-34;google_apis;x86_64"
echo no | avdmanager create avd -n dp34 -k "system-images;android-34;google_apis;x86_64" -d pixel_7
emulator -avd dp34 -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -no-snapshot &
adb wait-for-device && adb shell getprop sys.boot_completed   # 1
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Useful shortcuts while developing (they replace the manual Settings steps, never use them as product flow):

```bash
adb shell appops set app.drippop SYSTEM_ALERT_WINDOW allow
adb shell pm grant app.drippop android.permission.POST_NOTIFICATIONS
adb shell cmd statusbar add-tile app.drippop/.platform.tile.DripPopTileService
adb shell cmd statusbar click-tile app.drippop/.platform.tile.DripPopTileService
```

The API 34 `google_apis` image shows the whole-screen consent dialog only; the single-app picker must be
checked on the Galaxy S24 (`docs/evidence/gate1-native.md`).

## Install on the Galaxy S24

Enable Developer options → USB debugging, then `adb install -r app-debug.apk` (or sideload the APK attached
to the PR). Follow `docs/evidence/gate1-native.md`.
