---
title: Configure your iOS app
sources:
  - docs/design/platforms/ios/01-pyproject-ios.md
  - examples/mobile/hello-kivy/pyproject.toml
---

# Configure your iOS app

Your iOS configuration lives in the `[tool.kivy.ios]` overlay of your
`pyproject.toml`. This page covers the settings you change most often. For the
full key list, see the [iOS overlay reference](../../reference/pyproject/ios.md).

## Before you begin

- A Mac with [Xcode](https://developer.apple.com/xcode/) installed. iOS builds
  run only on macOS.
- [Install kivyforge](../../get-started/install.md).
- A project with `[project]` and `[tool.kivy]` sections. See
  [Project configuration](../../concepts/configuration.md).

## Add the overlay

1. Add a `[tool.kivy.ios]` table and a `[tool.kivy.ios.python]` table to your
   `pyproject.toml`:

    ```toml
    [tool.kivy.ios]
    schema_version = 1
    bundle_id = "org.example.hello-kivy"
    build = 1
    deployment_target = "16.0"
    extra_index_urls = ["https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"]
    exclude = ["kivy-garden", "docutils", "pygments"]

    [tool.kivy.ios.python]
    version = "3.15.0b4"
    ```

2. Optional: add an app icon:

    ```toml
    [tool.kivy.ios.icons]
    source = "assets/icon-ios.png"
    ```

    The source must be a 1024x1024 PNG. Apple also requires it to be opaque and
    full-bleed, with no transparency.

## Key settings

`schema_version`
:   Required. The overlay schema version. Set it to `1`.

`bundle_id`
:   Required. The bundle identifier, a reverse-DNS string that is your app's
    identity. It may contain only letters, digits, hyphens, and periods. An
    underscore is rejected.

`deployment_target`
:   The minimum iOS version, for example `"16.0"`. Defaults to `"13.0"`.

`build`
:   The build number, an integer you increment for each submission. Defaults to
    `1`.

`python.version`
:   Required. The CPython version to bundle. kivyforge downloads the matching
    iOS `Python.xcframework` from python.org, so the version must be one that
    python.org publishes for iOS, such as the prerelease `3.15.0b4`. Your
    `[project].requires-python` must allow it; a prerelease needs an explicit
    floor such as `">=3.15.0b4"`.

`extra_index_urls`
:   Extra package indexes to search. The mobile Kivy wheels are published on the
    index shown above, not on PyPI.

`exclude`
:   Dependencies to drop from the resolve, such as packages Kivy declares but
    your app does not use.

## Verify

Lock the dependencies and generate the project for the iOS Simulator, which
needs no signing:

```bash
kivyforge lock -p ios
kivyforge build -p ios --simulator
```

kivyforge validates the overlay strictly and names the offending key when it
rejects one. If `python.version` is not published by python.org, `kivyforge lock`
fails; correct the version and lock again.

## What's next

- [Run your iOS app on the simulator or a device](run.md).
- [Open the iOS project in Xcode](xcode.md).
- [Sign your iOS app](signing.md) for a device or distribution.
