---
title: Build a macOS .app
sources:
  - docs/design/platforms/macos/macos-spec.md
  - examples/desktop/dice-roller/pyproject.toml
---

# Build a macOS .app

This page shows you how to build a double-clickable `.app` bundle for macOS. The
bundle contains a relocatable CPython from python-build-standalone, your app, and
its wheels, so it runs on a Mac that has no Python installed.

## Before you begin

- A Mac with Apple Silicon. macOS builds run only on macOS.
- The Xcode command-line tools, which provide `clang`, `codesign`, and `lipo`.
  Install them with `xcode-select --install`. The full Xcode IDE is not required.
- [Install kivyforge](../../get-started/install.md).

!!! note "Apple Silicon only"
    kivyforge builds `arm64` macOS apps only. Intel (`x86_64`) and `universal2`
    apps are not a build target, and `archs = ["x86_64"]` is rejected. A
    `universal2` wheel is still accepted as a dependency, because it contains an
    `arm64` slice.

## Build and run the app

1. Add the macOS overlay to your `pyproject.toml`:

    ```toml
    [tool.kivy.macos]
    schema_version = 1
    bundle_id = "org.example.myapp"

    [tool.kivy.macos.python]
    version = "3.13.14"

    [tool.kivy.macos.icons]
    source = "assets/icon.png"
    ```

    The icon source must be a 1024x1024 PNG. For every key, see the
    [macOS overlay reference](../../reference/pyproject/macos.md).

2. Lock the dependencies:

    ```bash
    kivyforge lock -p macos
    ```

3. Build and launch the app:

    ```bash
    kivyforge run -p macos
    ```

    `run` builds `build/macos/<name>.app`, where `<name>` is your
    `[tool.kivy].display_name` (or `[project].name`), and runs it in the
    foreground, so the app's output and tracebacks appear in your terminal. To
    iterate, edit your source and run the command again.

## Package the .app

```bash
kivyforge package -p macos
```

`package` builds the release flavor of the `.app`, which applies the
`byte_compile` and `strip_source` build settings. Without a
`[tool.kivy.macos.signing]` identity, the result is *ad-hoc signed*: signed
without a certificate, which is the minimum Apple Silicon needs to run the app.
An ad-hoc-signed app runs on the Mac that built it, but Gatekeeper blocks a
downloaded copy until you [sign it with a Developer ID and notarize it](signing.md).
kivyforge reports this as a `KF-SIGNING-UNCONFIGURED` warning.

## Verify

```bash
kivyforge package -p macos --json
```

The command exits with status `0`, and `data.artifacts` gives the path of the
`.app`. To test a downloaded ad-hoc-signed copy on another Mac, remove its
quarantine attribute:

```bash
xattr -dr com.apple.quarantine APP_PATH
```

Replace `APP_PATH` with the path to the `.app`.

## What's next

- [Sign, notarize, and staple a macOS app](signing.md) for distribution.
- [Package a macOS app in a .dmg](dmg.md).
- [`[tool.kivy.macos]` reference](../../reference/pyproject/macos.md).
