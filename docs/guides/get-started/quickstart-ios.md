---
title: "Quickstart: build an iOS app"
sources:
  - docs/design/platforms/ios/04-cli-ios.md
  - docs/design/platforms/ios/05-xcode-project-generation.md
  - examples/mobile/hello-kivy/pyproject.toml
  - .github/workflows/kivyforge.yml
---

# Quickstart: build an iOS app

In this quickstart you build a Kivy app and run it on the iOS Simulator.
Building for iOS requires a Mac with Xcode. There is no way to build an iOS app
from Windows or Linux.

## Before you begin

- A Mac with Apple Silicon.
- kivyforge, installed as described in [Install kivyforge](install.md).
- [Xcode](https://developer.apple.com/xcode/) 15 or newer, from the Mac App
  Store, with an iOS 16 or newer Simulator runtime (Xcode > Settings >
  Components).
- Xcode selected as the active developer directory, with its license accepted:

    ```bash
    sudo xcode-select --switch /Applications/Xcode.app
    sudo xcodebuild -license accept
    ```

- [git](https://git-scm.com/), to fetch the example app.

## Step 1: Get the example app

```bash
git clone https://github.com/ElliotGarbus/kivyforge.git
cd kivyforge/examples/mobile/hello-kivy
```

This example ships a committed `pylock.ios.toml`, so you can build without
running `kivyforge lock`. Do not edit `pyproject.toml` during this quickstart:
any edit makes the lockfile out of date, and the build then asks you to re-lock.

## Step 2: Check your environment

```bash
kivyforge doctor -p ios
```

Fix any `FAIL` before you continue. The Simulator needs no signing identity,
and the example uses automatic signing, so the signing checks pass on a Mac
with no certificates.

## Step 3: Build for the Simulator

```bash
kivyforge build -p ios --simulator
```

kivyforge downloads the `Python.xcframework` and the iOS wheels, generates an
Xcode project in `hello-kivy-ios/`, and builds it for the Simulator. The built
`.app` lands under
`hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/`.

## Step 4: Run it

```bash
kivyforge run -p ios --simulator
```

`run` boots a Simulator if none is running, installs the app, and launches it.
The app shows **Hello Kivy**. `run` then streams the app's console output to
your terminal until you stop it with Ctrl+C.

!!! tip "Open in Xcode"
    To build and run from Xcode instead, run `kivyforge open -p ios`. It opens
    the generated project so you can use the Run button. See
    [Open the project in Xcode](../guides/ios/xcode.md).

## Verify

To see what the build produced as structured data, run:

```bash
kivyforge build -p ios --simulator --json
```

The `data.artifacts` array names the generated Xcode project and the built
`.app`, with paths relative to the project root.

## What's next

- [Configure your iOS app](../guides/ios/configure.md): bundle ID, deployment
  target, icons.
- [Run on the simulator or a device](../guides/ios/run.md).
- [Sign the app](../guides/ios/signing.md) for a real device or distribution.
