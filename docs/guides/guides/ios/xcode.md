---
title: Open the iOS project in Xcode
sources:
  - docs/design/platforms/ios/04-cli-ios.md
  - docs/design/platforms/ios/05-xcode-project-generation.md
---

# Open the iOS project in Xcode

kivyforge generates a complete Xcode project in `<app>-ios/`, where `<app>` is
your `[project].name`. You can build and run entirely from the command line, or
open the project in Xcode to pick a destination, press Run, and use the debugger
and Instruments.

## Before you begin

- [Configure your iOS app](configure.md) and lock it with
  `kivyforge lock -p ios`.

## Open the project

1. Generate the project. A bare `build` generates it for both the Simulator and
   a device:

    ```bash
    kivyforge build -p ios
    ```

2. Open it in Xcode:

    ```bash
    kivyforge open -p ios
    ```

    `open` launches Xcode on `<app>-ios/<app>.xcodeproj` and prints the path it
    opened. If the project does not exist yet, `open` fails and tells you to run
    `kivyforge build` first.

3. In Xcode, pick a Simulator or a connected device and click Run.

## What Xcode owns

- **Compiling and signing.** Xcode compiles the project and, for a device or
  release build, signs it. kivyforge writes the signing build settings from your
  `[tool.kivy.ios.signing]` table. See [Sign your iOS app](signing.md).
- **Swift Package Manager.** Xcode resolves and builds any
  [Swift packages](swift-packages.md) that you declare.

## Regenerate the project

kivyforge owns the generated `<app>-ios/` folder and regenerates it on every
`build`. Changes you make to the project in Xcode do not survive a regenerate,
so put configuration in `pyproject.toml` instead. For extra Xcode build settings,
use `[tool.kivy.ios.xcode.build_settings]`; see the
[iOS overlay reference](../../reference/pyproject/ios.md).

To start from a clean slate, remove the generated trees and build again:

```bash
kivyforge clean
kivyforge build -p ios
```

`kivyforge clean` removes the generated output for every platform in the
project, not only iOS.

## Verify

Xcode opens with your app's project, and the scheme builds and runs on the
destination you selected.

## What's next

- [Run your iOS app on the simulator or a device](run.md).
- [Add a Swift package to your iOS app](swift-packages.md).
- [Sign your iOS app](signing.md).
