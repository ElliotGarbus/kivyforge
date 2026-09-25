---
title: Run your Android app on a device or emulator
sources:
  - docs/design/platforms/android/06-cli-android.md
  - kivyforge/cli/run.py
  - kivyforge/platforms/android/cli.py
  - kivyforge/platforms/android/adb.py
---

# Run your Android app on a device or emulator

`kivyforge run -p android` builds your app, installs it on a device or an AVD
(Android Virtual Device, an emulator), and launches it. This page covers the
debug development loop and the on-device smoke test.

## Before you begin

- [Configure your Android app](configure.md) and lock it with
  `kivyforge lock -p android`.
- Have one of the following:
    - A physical device with USB debugging enabled and this computer authorized
      for `adb`.
    - An AVD, created in Android Studio's Device Manager or with `avdmanager`.
      It does not need to be running.

## Run the app

```bash
kivyforge run -p android
```

`run` picks a target, builds a debug APK (Android Package) for that target's ABI
(application binary interface), installs it, and launches it. Debug builds use
the standard Android debug keystore, so you need no signing setup.

Without target flags, `run` picks the first match in this order:

1. The only attached physical device. If several are attached, `run` stops and
   asks for `--serial`.
2. A running emulator.
3. The first AVD, which `run` boots.

## Choose a target

| To target | Add |
|---|---|
| A physical device only, never an emulator | `--device` |
| An emulator, even when a phone is attached | `--emulator` |
| A specific AVD to boot | `--avd AVD_NAME` |
| A specific attached device or emulator | `--serial SERIAL` |

Replace `AVD_NAME` with a name from your AVD list and `SERIAL` with a serial
number that `adb devices` shows, such as `emulator-5554`.

To list attached devices and available AVDs without running anything:

```bash
kivyforge run -p android --list-devices
```

`--device` cannot be combined with `--emulator` or `--avd`.

## Control the build

- `--abi arm64_v8a` or `--abi x86_64` builds for that ABI instead of the one the
  target reports. The ABI must be listed in `[tool.kivy.android].abis`.
- `--no-build` installs and launches the APK from the last build.
- `--release` builds the release variant, so `byte_compile` and `strip_source`
  apply as they do for `kivyforge package`. It uses your release key if
  `[tool.kivy.android.signing]` is configured and usable, and the debug keystore
  otherwise.

To build a debug APK without installing it:

```bash
kivyforge build -p android --debug --abi arm64_v8a
```

The APK is written to
`<app>-android/app/build/outputs/apk/debug/app-debug.apk`, where `<app>` is your
`[project].name`.

## Run the on-device smoke test

`--smoke` runs a generated instrumented test instead of launching your app. It
checks that the Python runtime, the extension-module loader, and the pyjnius
bridge work on the device:

```bash
kivyforge run -p android --smoke
```

Add `--release` to test the byte-compiled, stripped release variant. kivyforge's
own CI runs `run --smoke --release` on an x86_64 emulator.

## Verify

`run` prints the device it chose, launches the app, and then prints the app's
log lines tagged `kivyforge`, `python.std`, or `SDL` for about 25 seconds.
Python output and tracebacks appear there. A passing smoke test ends with
`Contract smoke test PASSED.`

## What's next

- [Sign and publish to Google Play](signing.md) when you are ready to distribute.
- [Handle mobile screen geometry](../cross-platform/mobile-geometry.md).
- [Diagnose a failing build](../../troubleshooting/index.md).
