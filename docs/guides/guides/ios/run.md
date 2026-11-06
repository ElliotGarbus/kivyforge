---
title: Run your iOS app on the simulator or a device
sources:
  - docs/design/platforms/ios/04-cli-ios.md
  - docs/design/platforms/ios/08-signing-prerequisites-ios.md
  - docs/design/platforms/ios/05-xcode-project-generation.md
  - FAQ.md
---

# Run your iOS app on the simulator or a device

This page shows you how to build and launch your app on the iOS Simulator, which
needs no signing, and on a connected iPhone or iPad, which does.

## Before you begin

- [Configure your iOS app](configure.md) and lock it with
  `kivyforge lock -p ios`.
- For a device: a `team_id` and an Apple account added to Xcode. See
  [Sign your iOS app](signing.md).

## Run on the Simulator

1. Build, install, and launch the app:

    ```bash
    kivyforge run -p ios --simulator
    ```

    `--simulator` is the default target for `run`, so you can omit it. `run`
    builds the app, boots a Simulator if none is running, installs the app, and
    launches it.

2. Optional: to target a specific Simulator, list the available simulators and
   devices, then pass a name or UDID (unique device identifier) with
   `--destination`:

    ```bash
    kivyforge run -p ios --list-devices
    kivyforge run -p ios --simulator --destination "DEVICE_NAME"
    ```

    Replace `DEVICE_NAME` with a simulator name or UDID from the list.

!!! tip "Iterate on Python source"
    For development builds, the generated project links your `app_dir` through a
    symbolic link. After you edit Python source, pressing Run in Xcode picks up
    the change without rerunning kivyforge. Run `kivyforge build` again when you
    change `pyproject.toml`.

## Run on a device

1. Set up signing. See [Sign your iOS app](signing.md).
2. Connect the device, then build, sign, install, and launch the app:

    ```bash
    kivyforge run -p ios --device
    ```

    To choose between several connected devices, pass `--destination` with a
    device name or UDID from `kivyforge run -p ios --list-devices`.

`run` streams the app's console to your terminal until the app ends. To end
it on the device, close it from the app switcher; going to the Home Screen
only suspends it. iOS often ends a closed app with SIGKILL, which `devicectl`
reports as "App terminated due to signal 9.", so `run` then exits with an
error even though the app ran normally. Pressing Ctrl+C in the terminal stops
`run` instead.

### Where the app's output goes

`run` builds the Debug configuration, which keeps the app's `print()` output and
Kivy's log on the console, so they stream to your terminal. A Release build,
which `package` makes, sends them to the Apple system log instead: a shipped app
has no console, and the system log is where a crash's traceback can be found.

To read a Release build's output:

- **On a device**, open Console.app on your Mac, select the device, and filter
  on the app's process name.
- **Kivy's own log file** is in the app's data container. Copy it to your Mac
  with `devicectl`, replacing `DEVICE_UDID`, `BUNDLE_ID` and the date in the
  file name:

    ```bash
    xcrun devicectl device copy from --device DEVICE_UDID --domain-type appDataContainer --domain-identifier BUNDLE_ID --source Documents/.kivy/logs/kivy_YY-MM-DD_0.txt --destination kivy.txt
    ```

    To list the log files, run `xcrun devicectl device info files --device DEVICE_UDID --domain-type appDataContainer --domain-identifier BUNDLE_ID --subdirectory Documents/.kivy/logs`.

To install an app you already built, add `--no-build`.

## Build without running

- `kivyforge build -p ios --simulator` or `kivyforge build -p ios --device`
  builds the `.app` without installing it.
- `kivyforge build -p ios` with no target stops after generating the Xcode
  project, ready to [open in Xcode](xcode.md).

## Verify

The app window appears in the Simulator or on the device. To get the path of the
built `.app`, run a `build` command with `--json` and read `data.artifacts`:

```bash
kivyforge build -p ios --simulator --json
```

## What's next

- [Open the iOS project in Xcode](xcode.md).
- [Add a Swift package to your iOS app](swift-packages.md) or
  [call iOS APIs with Rubicon-ObjC](rubicon.md).
- [Sign your iOS app](signing.md) for distribution.
