---
title: Migrate from buildozer, python-for-android, or kivy-ios
sources:
  - docs/design/common/00-overview.md
  - docs/design/common/01-pyproject-kivy-spec.md
  - docs/design/platforms/android/06-cli-android.md
  - docs/design/platforms/ios/04-cli-ios.md
  - docs/design/platforms/ios/07-recipe-triage.md
  - kivyforge/cli/init.py
---

# Migrate from buildozer, python-for-android, or kivy-ios

kivyforge replaces buildozer, python-for-android, and kivy-ios with one tool.
Instead of a spec file and per-app recipe builds, you describe the app in
`pyproject.toml` and kivyforge installs prebuilt wheels pinned in a lockfile.
This page maps the old concepts to the new ones and walks through moving an
Android or iOS project.

kivyforge doesn't convert a `buildozer.spec` automatically, but it prints a key
map to help you move the settings by hand.

## Before you begin

- [Install kivyforge](../../get-started/install.md).
- Check that every compiled dependency has a wheel for your target. See
  [The recipe model is gone](#the-recipe-model-is-gone).

## What changes

| Before | With kivyforge |
|---|---|
| `buildozer.spec` | `[project]`, `[tool.kivy]`, and `[tool.kivy.android]` or `[tool.kivy.ios]` in `pyproject.toml` |
| `requirements =` in `buildozer.spec` | `[project].dependencies`, as standard Python requirement strings |
| Recipes that cross-compile dependencies | Prebuilt wheels and runtimes, pinned in `pylock.<platform>.toml` |
| `android.ndk`, `android.sdk`, and other toolchain pins | Pinned by kivyforge. `kivyforge doctor -p android` checks your host against them. |
| `buildozer android debug` | `kivyforge build -p android --debug` |
| `buildozer android release` | `kivyforge package -p android` |
| kivy-ios recipe builds and an Xcode project | `kivyforge build -p ios` generates the Xcode project. Add `--simulator` or `--device` to build it as well. |

## The recipe model is gone

kivyforge has no recipe system and never builds a dependency from source. Every
dependency must be available as a wheel for the target: an `android_*` wheel for
Android, or an `ios_*` wheel for iOS. Pure-Python packages work everywhere. A
compiled package with no wheel for your target can't be used there. See
[Prebuilt runtimes and wheels](../../concepts/runtimes-and-wheels.md).

On iOS, most legacy kivy-ios recipes are no longer needed: the Python runtime
or the Kivy wheel bundles what they built, a pure-Python package installs from
PyPI, or a prebuilt iOS wheel exists. For a few, such as the barcode-scanning
recipes, the replacement is an Apple framework that you call through
[pyobjus](../ios/pyobjus.md).

## Migrate an Android project

1. In the directory that contains your `buildozer.spec`, print the migration
   map:

    ```bash
    kivyforge init -p android
    ```

    Because there is no `pyproject.toml` yet, `init` writes nothing and exits
    with an error that maps each `buildozer.spec` key to its kivyforge key,
    showing your current values. It also lists the settings that have no
    counterpart, and why.

2. Create a `pyproject.toml` with a `[project]` table: your app's `name`,
   `version`, `requires-python`, and `dependencies`. Move the entries of
   `requirements` into `dependencies`.

3. Seed the kivyforge tables:

    ```bash
    kivyforge init -p android
    ```

4. Using the map from step 1, move your settings into `[tool.kivy]` and
   `[tool.kivy.android]`. For example, `title` becomes `display_name`,
   `source.dir` becomes `app_dir`, and `android.permissions` becomes
   `[tool.kivy.android.permissions].uses`. See
   [Configure your Android app](../android/configure.md) and the
   [Android overlay reference](../../reference/pyproject/android.md).

5. Set `kivy_generation` to match your Kivy version: `2` for Kivy 2.3.1 on SDL2,
   or `3` for Kivy 3.0 on SDL3.

6. Lock the dependencies:

    ```bash
    kivyforge lock -p android
    ```

7. [Build and run the app](../android/run.md).

Only 64-bit ABIs are supported: `arm64_v8a` and `x86_64`. The 32-bit
`armeabi-v7a` and `x86` ABIs from `android.archs` have no equivalent.

## Migrate an iOS project

You need a Mac to build for iOS.

1. Create a `pyproject.toml` with a `[project]` table, listing your dependencies.
   iOS builds use Kivy 3.0.

2. Seed the kivyforge tables:

    ```bash
    kivyforge init -p ios
    ```

3. Fill in `[tool.kivy]` and `[tool.kivy.ios]`. See
   [Configure your iOS app](../ios/configure.md).

4. Lock the dependencies:

    ```bash
    kivyforge lock -p ios
    ```

5. [Build and run the app on the simulator](../ios/run.md).

## Add desktop targets

buildozer, python-for-android, and kivy-ios build only for mobile. kivyforge also
builds macOS, Windows, and Linux apps from the same `[project]` and `[tool.kivy]`
tables: add an overlay for each desktop target. See the
[desktop quickstart](../../get-started/quickstart-desktop.md).

## Verify

Your migration is complete when `kivyforge doctor -p android` (or `-p ios`)
reports no FAIL results and the app starts on a device or emulator.

## What's next

- [Project configuration](../../concepts/configuration.md)
- [How kivyforge works](../../concepts/how-it-works.md)
- [Configure your Android app](../android/configure.md) or
  [configure your iOS app](../ios/configure.md)
