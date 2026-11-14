---
title: "Quickstart: build an Android app"
sources:
  - docs/design/platforms/android/06-cli-android.md
  - examples/mobile/hello-android/pyproject.toml
  - .github/workflows/kivyforge.yml
---

# Quickstart: build an Android app

In this quickstart you build a minimal Kivy app as a debug APK (Android
application package) and run it on an emulator or a device. You can do this
from Windows, macOS, or Linux. Android does not require a Mac.

## Before you begin

- kivyforge, installed as described in [Install kivyforge](install.md).
- A JDK (Java Development Kit) in the range listed in
  [Supported versions](../guides/android/supported-versions.md#build-tools), in
  `JAVA_HOME` or on your `PATH`. It must be a full JDK: a JRE has no `javac`, and
  `kivyforge doctor -p android` fails it. Android Studio's bundled JDK may be newer than
  that range; `kivyforge doctor -p android` tells you. If it is, install a
  separate one, such as [Eclipse Temurin](https://adoptium.net/).
- The Android SDK with command-line tools, build-tools, platform-tools, and the
  NDK version listed in
  [Supported versions](../guides/android/supported-versions.md#build-tools).
  Builds use only that NDK version and ignore any other NDK you have installed,
  such as a newer one. [Android Studio](https://developer.android.com/studio)
  installs the SDK. Add the command-line tools and the NDK from its SDK Manager:
  on the **SDK Tools** tab, select **Show Package Details** to pick the NDK
  version. Then accept the SDK licenses (see
  [SDK licenses and `sdkmanager`](#sdk-licenses-and-sdkmanager)).
- Somewhere to run the app: a physical device with USB debugging turned on (see
  [Set up a physical device](../guides/android/run.md#set-up-a-physical-device)),
  or an AVD (Android Virtual Device, an emulator image) created in Android
  Studio's Device Manager. The SDK's emulator package is needed only for an
  AVD.
- [git](https://git-scm.com/), to fetch the example app.

### SDK licenses and `sdkmanager`

A build installs a missing NDK or CMake of the pinned version, and Gradle
installs other missing SDK packages, but only once the SDK license is recorded
under `<sdk>/licenses/`. The NDK is a download of several hundred MB.

- Older command-line tools record it when you run `sdkmanager --licenses` and
  accept.
- Command-line tools 23 and later replace `sdkmanager` with a wrapper around
  Google's Android CLI. There, `sdkmanager --licenses` prints "no longer needed"
  and does nothing; installing any package, such as `sdkmanager platform-tools`,
  records the license without asking.

Two more differences with the new wrapper. An install that fails, such as a
mistyped package name, prints "not found" but still exits with status 0, so
check the result with `sdkmanager --list_installed`. And the Android CLI
collects usage data unless you run it with `--no-metrics`, which the
`sdkmanager` wrapper does not pass; the `android` binary next to it in
`cmdline-tools/latest/bin` accepts the flag (`android --no-metrics sdk install
<package>`).

## Step 1: Get the example app

```bash
git clone https://github.com/ElliotGarbus/kivyforge.git
cd kivyforge/examples/mobile/hello-android
```

This example ships a committed `pylock.android.toml`, so you can build without
running `kivyforge lock`. Do not change the dependencies or the `[tool.kivy.android]` table's
build settings during this quickstart: those edits make the lockfile out of
date, and the build then asks you to re-lock.

## Step 2: Check your environment

```bash
kivyforge doctor -p android
```

`doctor` checks the JDK, the SDK and its licenses, build-tools, the NDK, the
emulator, and `adb` (Android Debug Bridge). Fix any `FAIL` before you continue.
It prints the `sdkmanager` command for anything that is missing. If you run
only on a phone, you can ignore the `WARN` for a missing AVD.

!!! note "Preview"
    This describes behavior that is on `main` but not yet in a released
    version. It will ship in a future release.

    `doctor` checks for the NDK version that builds use. If only other NDK
    versions are installed, it warns that builds do not use them. A missing NDK
    is a `WARN`, not a `FAIL`, because the first build installs it. To install
    it ahead of time, run the `sdkmanager` command that `doctor` prints.

## Step 3: Build the debug APK

```bash
kivyforge build -p android --debug --abi ABI
```

Replace `ABI` with the ABI (application binary interface) of the device you
plan to run on:

- `x86_64` for an emulator on an Intel or AMD computer.
- `arm64_v8a` for a physical device, or for an emulator on an Apple Silicon Mac.

kivyforge generates a Gradle project in `hello-android-android/`, stages the
Python runtime and wheels, and drives Gradle to produce
`hello-android-android/app/build/outputs/apk/debug/app-debug.apk`. The first
build downloads Gradle and its dependencies, so it takes several minutes.

`build` doesn't need a device or an emulator, so the phone can stay unplugged.

## Step 4: Run it

```bash
kivyforge run -p android
```

`run` picks a target: a single connected physical device, else a running
emulator, else it boots your first AVD. It then rebuilds the debug APK for that
target's ABI, installs it, launches it, and prints the app's log lines. The app
opens full screen and shows **Hello from kivyforge**.

To run only on a phone, add `--device`. `run` then never looks for an
emulator, and it stops with an error if `adb` can't see the phone:

```bash
kivyforge run -p android --device
```

If the phone isn't found, see
[Set up a physical device](../guides/android/run.md#set-up-a-physical-device).

!!! tip "Contract smoke test"
    `kivyforge run -p android --smoke` runs an instrumented test that kivyforge
    generates, instead of launching the app. It checks the Python runtime, the
    extension-module loader, and the pyjnius bridge on the device. CI runs it
    as `kivyforge run --smoke --release -p android`.

## Verify

The launcher on the device shows the app as **Hello Android**, the
`display_name` from `pyproject.toml`. To see what a build produced as
structured data, run:

```bash
kivyforge build -p android --debug --abi ABI --json
```

Replace `ABI` as in Step 3. The `data.artifacts` array names the generated
project and the `.apk`, with paths relative to the project root.

## What's next

- [Configure your Android app](../guides/android/configure.md): package ID, SDK
  levels, permissions, icons.
- [Sign and publish to Google Play](../guides/android/signing.md).
- [Call Android APIs with pyjnius](../guides/android/pyjnius.md).
