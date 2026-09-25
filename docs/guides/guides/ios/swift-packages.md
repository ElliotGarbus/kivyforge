---
title: Add a Swift package to your iOS app
sources:
  - docs/design/platforms/ios/06-swift-packages.md
  - examples/mobile/keychain-spm/pyproject.toml
  - CHANGELOG.md
---

# Add a Swift package to your iOS app

You can add Swift Package Manager (SPM) dependencies to your iOS app under
`[tool.kivy.ios.native.swift_packages]`. kivyforge pins each remote package in
the lock and wires every package into the generated Xcode project; Xcode
resolves and builds them.

## Before you begin

- [Configure your iOS app](configure.md).
- Decide whether you call the package from Python. Python reaches Swift code
  through [pyobjus](pyobjus.md), which sees only Objective-C-compatible APIs.
  A pure-Swift API, such as one built on throwing functions, generics, or
  subscripts, needs a small `@objc` wrapper, called a *shim*.

## Add a remote package

1. Declare the package by URL, version requirement, and the products to link:

    ```toml
    [tool.kivy.ios.native.swift_packages]
    KeychainAccess = { url = "https://github.com/kishikawakatsumi/KeychainAccess", requirement = { from = "4.2.2" }, products = ["KeychainAccess"] }
    ```

    `requirement` takes exactly one rule: `exact`, `from`, `up_to_next_minor`,
    `range` (a two-item list, lower bound inclusive and upper bound exclusive),
    `branch`, or `revision`.

2. Lock the project:

    ```bash
    kivyforge lock -p ios
    ```

    kivyforge resolves the package with Xcode's Swift toolchain and pins the
    exact revision in `pylock.ios.toml`. `build` writes that pin into the
    generated project's `Package.resolved`, so Xcode resolves the same revision.

!!! note "Embedding a remote package"
    `embed` defaults to `false` for a remote package, because most remote
    products resolve to static libraries, which have no framework to copy into
    the app. If a remote package's product is a dynamic framework, set
    `embed = true` explicitly. Setting `embed = true` on a static product fails
    the Xcode build.

## Add a local shim to call Swift from Python

To call a pure-Swift API from Python, write a local package that re-exports the
calls you need from an `@objc` class, and declare it with `path`. The
`keychain-spm` example uses this pattern:

```toml
[tool.kivy.ios.native.swift_packages]
KeychainAccess = { url = "https://github.com/kishikawakatsumi/KeychainAccess", requirement = { from = "4.2.2" }, products = ["KeychainAccess"], link = false, embed = false }
KeychainBridge = { path = "swift-shims", products = ["KeychainBridge"] }
```

- `KeychainBridge` is the shim in the project's `swift-shims/` directory. Its
  `Package.swift` depends on `KeychainAccess` and declares a dynamic library
  product. A local package is linked and embedded by default.
- Embedding the shim brings in its whole dynamic dependency closure, including
  `KeychainAccess`. That is why `KeychainAccess` is declared
  `link = false, embed = false`: the declaration still pins it in the lock
  without embedding it a second time.

A `path` must be relative to the project and must not point outside it.

## Verify

Lock and build for the Simulator. The build fails if a package does not resolve:

```bash
kivyforge lock -p ios
kivyforge build -p ios --simulator
```

## What's next

- [Call iOS APIs with pyobjus](pyobjus.md) to reach your shim's `@objc` class.
- [Open the iOS project in Xcode](xcode.md) to inspect the resolved packages.
- [`[tool.kivy.ios]` reference](../../reference/pyproject/ios.md).
