---
title: Add Java libraries to your Android app
sources:
  - docs/design/platforms/android/01-pyproject-android.md
  - docs/design/platforms/android/02-pylock-android-spec.md
  - docs/design/platforms/android/03-artifact-distribution-android.md
  - docs/design/platforms/android/04-gradle-project-generation.md
  - docs/design/dev/test-matrix.md
  - kivyforge/config/loader.py
  - kivyforge/platforms/android/generate/project.py
  - examples/mobile/qr-maven/pyproject.toml
---

# Add Java libraries to your Android app

You can add Java or Kotlin code to your app in three ways: a Maven dependency, a
local or downloadable archive (`.aar` or `.jar`), or your own source files.
kivyforge adds them to the generated Gradle project, and you call them from
Python with [pyjnius](pyjnius.md).

Maven dependencies can also take their versions from a BOM, and some libraries
need a Gradle plugin too. Firebase needs both; see [Add Firebase](#add-firebase).

## Before you begin

- [Configure your Android app](configure.md).
- For Maven dependencies, have a JDK on the computer that runs
  `kivyforge lock`. Locking runs Gradle once to resolve the dependency graph.

## Add a Maven dependency

1. Declare the coordinate under `[tool.kivy.android.gradle]`. This example,
   from the `qr-maven` example project, adds ZXing, a QR code library:

    ```toml
    [tool.kivy.android.gradle]
    dependencies = [
        "com.google.zxing:core:3.5.3",
    ]
    ```

    Each coordinate must be a full `group:artifact:version`. Dynamic versions
    such as `3.+` are rejected. To resolve from a repository other than Google's
    Maven repository and Maven Central, list its URL in `repositories`.

2. Lock:

    ```bash
    kivyforge lock -p android
    ```

    kivyforge resolves the full dependency graph and records each artifact with
    its SHA-256 hash in `pylock.android.toml`.

## Use a BOM

A BOM (bill of materials) is a published list of library versions that are
tested together. Firebase, Jetpack Compose, and OkHttp publish one. List the BOM
under `platforms`, then leave the version off each library it covers:

```toml
[tool.kivy.android.gradle]
platforms = ["com.google.firebase:firebase-bom:34.15.0"]
dependencies = [
    "com.google.firebase:firebase-analytics",
    "com.google.firebase:firebase-messaging",
]
```

The BOM itself needs an exact version. A `dependencies` entry without a version
is rejected unless a BOM is listed. You can still give a library an explicit
version alongside a BOM; Gradle then uses the higher of that version and the
BOM's. `kivyforge lock` records the version Gradle chose for each library, and
the BOM file itself, with their SHA-256 hashes.

## Add a Gradle plugin

Some libraries need a Gradle plugin as well as a dependency. List each plugin
under `[tool.kivy.android.gradle.plugins]` with an exact version:

```toml
[tool.kivy.android.gradle.plugins]
"com.google.gms.google-services" = "4.4.2"
```

Quote each plugin ID. TOML splits a bare key on its dots, and kivyforge rejects
the result. kivyforge applies the plugins after the Android plugin, in the order
you list them.

!!! warning
    A plugin runs code during your build. kivyforge pins its version, but the
    lock does not record a hash for it, just as for the Android Gradle plugin
    itself. Add plugins only from sources you trust.

## Add Firebase

Firebase needs three things: the Firebase BOM, the Google Services plugin, and
your Firebase project's `google-services.json` file. The plugin reads that file
during the build and turns it into resources Firebase reads when it starts.

1. In the Firebase console, add an Android app whose package name matches
   `[tool.kivy.android].package`, and download its `google-services.json`. Save
   it in your project, for example as `config/google-services.json`.

2. Declare the BOM, the libraries you use, the plugin, and the file:

    ```toml
    [tool.kivy.android.gradle]
    platforms = ["com.google.firebase:firebase-bom:34.15.0"]
    dependencies = ["com.google.firebase:firebase-analytics"]

    [tool.kivy.android.gradle.plugins]
    "com.google.gms.google-services" = "4.4.2"

    [[tool.kivy.android.include_files]]
    dest = "app"
    sources = ["config/google-services.json"]
    ```

    `dest = "app"` puts the file in the `app/` folder of the generated project,
    where the plugin looks for it.

3. Lock and build:

    ```bash
    kivyforge lock -p android
    kivyforge build -p android --debug --abi x86_64
    ```

Firebase starts itself when your app launches. To confirm, run the app and look
for `FirebaseApp initialization successful` in `adb logcat`. Call Firebase APIs
from Python with [pyjnius](pyjnius.md).

Some Firebase products need more:

- **Crashlytics** needs its own plugin as well. List it after Google Services,
  because kivyforge applies plugins in the order you list them:
  `"com.google.firebase.crashlytics" = "VERSION"`.
- **Cloud Messaging** delivers push messages to a subclass of
  `FirebaseMessagingService`, which you write in Java or Kotlin. Add it with
  [your own source files](#add-your-own-java-or-kotlin-source) and declare the
  service with `extra_application_xml` in
  [`[tool.kivy.android.manifest]`](../../reference/pyproject/android.md).

`google-services.json` changes are lock drift like any other `include_files`
source: after you replace the file, run `kivyforge lock -p android` again.

## Add an .aar or .jar archive

1. Declare each archive by name under `[tool.kivy.android.native.aars]` or
   `[tool.kivy.android.native.jars]`, with its version and source:

    ```toml
    [tool.kivy.android.native.aars]
    LocalWidget = { version = "0.2.0", source = "libs/LocalWidget-0.2.0.aar" }

    [tool.kivy.android.native.jars]
    legacyutil = { version = "1.4.0", source = "libs/legacyutil-1.4.0.jar" }
    ```

    `source` is a download URL or a path relative to your project. An `.aar`
    can carry resources and manifest entries; a `.jar` contains only compiled
    classes.

2. Lock, so kivyforge records each archive's SHA-256 hash:

    ```bash
    kivyforge lock -p android
    ```

## Add your own Java or Kotlin source

List your source directories under `[tool.kivy.android.src]`:

```toml
[tool.kivy.android.src]
java = ["android/java"]
```

A non-empty `kotlin` list also works, and enables the Kotlin Gradle plugin.

## Verify

Build the app:

```bash
kivyforge build -p android --debug --abi x86_64
```

A Maven coordinate or BOM that cannot be resolved, or an archive source that
cannot be read, fails `kivyforge lock`. Gradle plugins are fetched only by the
build, so a plugin ID or version that does not exist fails `kivyforge build`.

## What's next

- [Call Android APIs with pyjnius](pyjnius.md) to use the library you added.
- [Add a background service](services.md).
- [Android overlay reference](../../reference/pyproject/android.md).
