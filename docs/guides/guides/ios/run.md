---
title: Run your iOS app on the simulator or a device
sources:
  - docs/design/platforms/ios/04-cli-ios.md
  - docs/design/platforms/ios/08-signing-prerequisites-ios.md
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
    device name or identifier from `kivyforge run -p ios --list-devices`.

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
  [call iOS APIs with pyobjus](pyobjus.md).
- [Sign your iOS app](signing.md) for distribution.
