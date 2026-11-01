---
title: Add a Swift package to your macOS app
sources:
  - docs/design/dev/macos-swift-packages-proposal.md
  - docs/design/dev/macos-swift-packages-spike-findings.md
  - kivyforge/platforms/macos/swift_packages.py
  - examples/mobile/swift-bridge/swift-shims/Package.swift
---

# Add a Swift package to your macOS app

You can add Swift Package Manager (SPM) dependencies to your macOS app under
`[tool.kivy.macos.native.swift_packages]`: an SDK such as Firebase, or a shim
of `@objc` classes that your Python code calls. kivyforge pins each remote
package in the lock, builds every package into a framework with `xcodebuild`,
and puts the framework in the `.app`. Your Python code loads it and calls its
classes through [Rubicon-ObjC](https://github.com/beeware/rubicon-objc).

The keys are the iOS ones, but the result is not: a macOS `.app` has no Xcode
project, so nothing links the packages into your app's executable. Python
loads them when your code asks.

## Before you begin

- [Build a macOS .app](build.md) without packages first.
- Install the full Xcode and select it:
  `sudo xcode-select --switch /Applications/Xcode.app`. The command-line tools
  have `swift` but not `xcodebuild`, which the build needs.
- If you write a shim, read [Call Swift from Python](../ios/swift.md). Its rules
  for `@objc` classes and its Rubicon-ObjC examples apply on macOS unchanged.

## Declare the packages

1. Add the packages to your macOS overlay:

    ```toml
    [tool.kivy.macos.native.swift_packages]
    SwiftBridge = { path = "swift-shims", products = ["SwiftBridge"] }
    Promises = { url = "https://github.com/google/promises", requirement = { from = "2.4.0" }, products = ["Promises"] }
    ```

    `url`, `path`, `requirement` and `products` mean what they mean on iOS; see
    the [reference](../../reference/pyproject/macos.md#toolkivymacosnativeswift_packages).
    A local package's `path` is relative to the project root. `link` and
    `embed` are refused: every product goes into the same framework.

2. If a local package declares only `platforms: [.iOS(...)]`, it still builds
   for macOS at SwiftPM's default minimum. If it uses an API newer than that,
   add a macOS platform to its `Package.swift`, for example
   `.macOS(.v13)`, and set `minimum_system_version` in `[tool.kivy.macos]` to
   at least that version.

3. Add Rubicon-ObjC to your dependencies and lock:

    ```toml
    [project]
    dependencies = ["rubicon-objc>=0.5.7"]
    ```

    ```bash
    kivyforge lock -p macos
    ```

    The lock runs `swift package resolve` for remote packages and records each
    one's revision in `pylock.macos.toml`. Local packages are recorded by path
    and are not resolved.

## Build

```bash
kivyforge build -p macos
```

The build writes a root package in `build/macos/spm/` that depends on every
locked package, and builds its one dynamic library, `KivyforgePackages`, with
`xcodebuild`. The first build clones remote packages; later builds reuse the
checkouts and compiled code in `build/macos/spm/`.

The `.app` gets:

| What | Where |
|---|---|
| `KivyforgePackages.framework`, which links every product that leaves its type unset | `Contents/Frameworks/` |
| A framework for each product its package declares `type: .dynamic`, such as a shim's | `Contents/Frameworks/` |
| Each package's resource bundle, `<package>_<target>.bundle` | `Contents/Resources/` |

They are signed with the rest of the bundle, ad hoc or with your Developer ID.
`Bundle.module`, which package code uses to find its resources, looks in
`Contents/Resources/` first.

## Load the framework from Python

Load `KivyforgePackages` once, before you look up a class. Loading it loads the
other frameworks too:

```python
import sys
from pathlib import Path

from rubicon.objc import ObjCClass
from rubicon.objc.runtime import load_library

frameworks = Path(sys.prefix).parents[1] / "Frameworks"
load_library(str(frameworks / "KivyforgePackages.framework" / "KivyforgePackages"))

notebook = ObjCClass("SBNotebook").alloc().initWithTitle("Groceries")
```

`sys.prefix` is the bundled runtime, `Contents/Resources/python`, so two
levels up is `Contents/`. Nothing is loaded at launch: until this call, the
Objective-C runtime has none of the packages' classes.

## Verify

1. Run `kivyforge doctor -p macos`. With packages declared, it checks for
   `swift` (to lock), for `xcodebuild` (to build), and that each local
   package has a `Package.swift`.
2. Build, then run the app and call one of your classes. The
   [`swift-bridge` shim](../ios/swift.md) works as it is: a run on macOS
   constructed `SBNotebook`, polled an `SBWork` job to completion, and found a
   remote package's resource bundle in the main bundle.
3. Check the signature covers the frameworks:

    ```bash
    codesign --verify --deep --strict "build/macos/My App.app"
    ```

## Things to know

- **Remote packages are pinned, their dependencies are not.** The lock records
  the revision of each package you declare. SPM resolves the packages *they*
  depend on when the build runs, as on iOS.
- **Products that force `.dynamic`** stay separate frameworks. That is fine:
  each finds the others in `Contents/Frameworks/` by itself.
- **`-ObjC` is always on**, so a static library inside a package keeps its
  Objective-C classes and categories even when nothing in Swift refers to
  them.
- **A build error** fails with `KF-BUILD-TOOL-FAILED` and shows
  `xcodebuild`'s `error:` lines. The generated package is in
  `build/macos/spm/Package.swift`; `xcodebuild` run there reproduces it.

## What's next

- [Call Swift from Python](../ios/swift.md) to write a shim.
- [Sign, notarize, and staple a macOS app](signing.md).
