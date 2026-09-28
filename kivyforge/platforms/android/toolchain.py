"""kivyforge-emitted Android toolchain pins (android/06 §versioning, layer 2).

These move with a kivyforge release and are validated together — the exact
combination the Phase-0 prototype proved on-device
(docs/design/dev/android-loadmodel-findings.md §runtime-package facts). The
generated project is regenerated on every build, so bumping kivyforge and
rebuilding is how projects move across these pins.
"""

from __future__ import annotations

# Gradle wrapper distribution the generated project pins (the python.org
# testbed's own combo, proven with AGP below).
GRADLE_VERSION = "8.11.1"
GRADLE_DISTRIBUTION_URL = (
    f"https\\://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip"
)

# The JDKs the pinned Gradle can run on, checked by `doctor`. AGP 8 needs 17;
# Gradle 8.11 cannot run on anything newer than 23 (Gradle's compatibility
# matrix), and fails with "Unsupported class file major version" -- which is
# what Android Studio's bundled JDK 25 produces. Move MAX_JDK with GRADLE_VERSION.
MIN_JDK = 17
MAX_JDK = 23

# Android Gradle Plugin version emitted into the root build.gradle.
AGP_VERSION = "8.10.0"

# Kotlin plugin version (applied only when [tool.kivy.android.src].kotlin is
# non-empty).
KOTLIN_VERSION = "1.9.22"

# ndkVersion emitted into app/build.gradle: the launcher compile is
# deterministic across hosts (android/04 §native launcher). r27.3 is the
# proven prototype pin; cibuildwheel's wheels pin the same family.
NDK_VERSION = "27.3.13750724"
