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
- A JDK (Java Development Kit), version 17 or newer, on your `PATH` or in
  `JAVA_HOME`.
- The Android SDK with command-line tools, build-tools, platform-tools, and the
  Android NDK. [Android Studio](https://developer.android.com/studio) installs
  the SDK. Add the NDK and command-line tools from its SDK Manager, then accept
  the SDK licenses with `sdkmanager --licenses`.
- Somewhere to run the app: a physical device with USB debugging turned on, or
  an AVD (Android Virtual Device, an emulator image) created in Android Studio's
  Device Manager.
- [git](https://git-scm.com/), to fetch the example app.

## Step 1: Get the example app

```bash
git clone https://github.com/ElliotGarbus/kivyforge.git
cd kivyforge/examples/mobile/hello-android
```

This example ships a committed `pylock.android.toml`, so you can build without
running `kivyforge lock`. Do not edit `pyproject.toml` during this quickstart:
any edit makes the lockfile out of date, and the build then asks you to re-lock.

## Step 2: Check your environment

```bash
kivyforge doctor -p android
```

`doctor` checks the JDK, the SDK and its licenses, build-tools, the NDK, the
emulator, and `adb` (Android Debug Bridge). Fix any `FAIL` before you continue.
It prints the `sdkmanager` command for anything that is missing.

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

## Step 4: Run it

```bash
kivyforge run -p android
```

`run` picks a target: a single connected physical device, else a running
emulator, else it boots your first AVD. It then rebuilds the debug APK for that
target's ABI, installs it, launches it, and prints the app's log lines. The app
opens full screen and shows **Hello from kivyforge**.

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
