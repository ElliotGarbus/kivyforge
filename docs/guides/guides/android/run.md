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

The test runs only on the device `run` chose, so a phone and an emulator can
both be attached.

## Verify

`run` prints the device it chose, launches the app, and then follows the app's
log as it runs: everything the app's own process writes, including Python
output, tracebacks and Android crash reports, and nothing from other apps. It
keeps following until the app exits or you press Ctrl+C. Ctrl+C stops the log,
not the app.

If the app never starts, `run` prints the whole device log since launch, where
the reason is, and fails.

For a script, add `--no-follow`: `run` then prints the app's log once, about 25
seconds after launch, and returns.

A passing smoke test ends with `Contract smoke test PASSED.`

## Filter the app's log

The followed log includes everything the app's process writes, including
Android's own messages, which can bury your output. kivyforge does not filter
it, but standard tools can. Two facts make that easy:

- Python's output has its own logcat tags: `print()` and Kivy's log go to
  `python.stdout` and `python.stderr`. Java's `System.out.println` goes to
  `System.out`, and `Log.d("MyTag", ...)` uses the tag you pass.
- `run` writes the app's log to stdout and its own `[run]` messages to stderr,
  so a filter on stdout keeps kivyforge's messages.

### Filter as `run` follows the log

=== "PowerShell"
    ```powershell
    # Python only
    kivyforge run -p android | Select-String ' [VDIWEF] python\.std'

    # Java only; add your own Log tags to the pattern
    kivyforge run -p android | Select-String ' [VDIWEF] System\.(out|err)'

    # Python and Java
    kivyforge run -p android | Select-String ' [VDIWEF] (python\.std|System\.(out|err))'

    # Everything except one noisy tag
    kivyforge run -p android | Select-String -NotMatch BLASTBufferQueue
    ```

=== "bash"
    ```bash
    # Python only
    kivyforge run -p android | grep -E ' [VDIWEF] python\.std'

    # Java only; add your own Log tags to the pattern
    kivyforge run -p android | grep -E ' [VDIWEF] System\.(out|err)'

    # Python and Java
    kivyforge run -p android | grep -E ' [VDIWEF] (python\.std|System\.(out|err))'

    # Everything except one noisy tag
    kivyforge run -p android | grep -v BLASTBufferQueue
    ```

### Use logcat's own filters

logcat filters by tag and level on the device. Launch with `--no-follow`, then
read the log with `adb`. Replace `PACKAGE` with your
`[tool.kivy.android].package`:

=== "PowerShell"
    ```powershell
    kivyforge run -p android --no-follow
    adb logcat --pid=$(adb shell pidof -s PACKAGE) python.stdout:V python.stderr:V System.out:V "*:S"
    ```

=== "bash"
    ```bash
    kivyforge run -p android --no-follow
    adb logcat --pid=$(adb shell pidof -s PACKAGE) python.stdout:V python.stderr:V System.out:V '*:S'
    ```

`*:S` silences every tag you don't list, so list only the tags you want. Leave
it out to see everything. This command stops when the app's process ends; run it
again after a restart.

### Use Android Studio's Logcat window

Launch with `kivyforge run -p android --no-follow`, open **View > Tool Windows >
Logcat** in Android Studio, and type a query into its search field:

| To see | Query |
|---|---|
| Python only | `package:PACKAGE tag:python` |
| Java only | `package:PACKAGE tag:System.out` |
| Python and Java | `package:PACKAGE tag:python tag:System.out` |
| Everything except one noisy tag | `package:PACKAGE -tag:BLASTBufferQueue` |
| Crashes only | `package:PACKAGE is:crash` |

`tag:` matches tags that contain the text, so `tag:python` matches both Python
tags. Several `tag:` terms match any of them, and a leading `-` excludes. Add
`tag:MyTag` for your own Java tags, or `level:WARN` to hide anything less
severe. If you open the generated project with `kivyforge open -p android`,
`package:mine` replaces `package:PACKAGE`. Logcat keeps following across app
restarts. See Android's [Logcat
documentation](https://developer.android.com/studio/debug/logcat) for the full
query syntax.

## What's next

- [Sign and publish to Google Play](signing.md) when you are ready to distribute.
- [Handle mobile screen geometry](../cross-platform/mobile-geometry.md).
- [Diagnose a failing build](../../troubleshooting/index.md).
