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
- Kivy 3. kivyforge builds Kivy 3 only on iOS: a `kivy` requirement that
  admits only 2.x, such as `kivy<3`, fails `kivyforge lock -p ios` with
  `KF-IOS-KIVY-UNSUPPORTED`. kivy-ios serves Kivy 2.x.
- A project with `[project]` section (`kivyforge init` adds `[tool.kivy]`, below). See
  [Project configuration](../../concepts/configuration.md).

!!! tip "Start from a template"
    Run `kivyforge init -p ios` in the folder that holds your
    `pyproject.toml`. It adds `[tool.kivy]` and a `[tool.kivy.ios]` overlay with
    comments and `TODO` markers on the values you need to change, so you edit a
    working file instead of typing the iOS overlay by hand. To
    regenerate an overlay that already exists, add `--force`. See
    [Seed overlays with `init`](../../concepts/configuration.md#seed-overlays-with-init).

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
:   The minimum iOS version, for example `"16.0"`. Defaults to `"16.0"`, the
    oldest iOS that Kivy's own iOS wheels run on. Xcode also limits it: Xcode 27
    accepts 15.0 and later, and `kivyforge doctor -p ios` reports the range your
    Xcode accepts.

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

## Add files to the app bundle

Some SDKs read a file from the app bundle rather than from your Python code.
Firebase, for example, looks for `GoogleService-Info.plist` at the root of the
`.app`. Copy such files in with `include_files`:

```toml
[[tool.kivy.ios.include_files]]
dest = "."
sources = ["config/GoogleService-Info.plist"]
```

`dest` is a folder inside the `.app`, and `"."` is its root. A file source lands
in `dest` under its own name. A directory source copies its *contents*, with
their subfolders, so a `Settings.bundle` folder or a set of
`<lang>.lproj/InfoPlist.strings` translations keeps its layout:

```toml
[[tool.kivy.ios.include_files]]
dest = "Settings.bundle"
sources = ["ios/Settings.bundle"]

[[tool.kivy.ios.include_files]]
dest = "."
sources = ["ios/localized"]   # holds en.lproj/, fr.lproj/, ...
```

kivyforge copies every file byte for byte, so Xcode does not convert a `.plist`
to binary or compile anything. After the build, it checks that the `.app` (and,
for `--release`, the `.ipa`) holds each file as it was copied, and fails with
`KF-ARTIFACT-CONTENT` otherwise. Formats that only work compiled, such as a
String Catalog (`.xcstrings`) or a storyboard, are refused; include the
compiled `.strings` files instead. A file that would replace one the build
writes, such as `Info.plist`, is refused too: set Info.plist keys with
`[tool.kivy.ios.info_plist]`.

`kivyforge lock` records a hash for every file, so after adding, editing or
removing one, run `kivyforge lock -p ios` again. That rewrites only the file
hashes and resolves nothing. A file you remove from `sources` is removed from
the generated project, and from the app, on the next build.

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
