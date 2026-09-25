---
title: Prebuilt runtimes and wheels
sources:
  - docs/design/common/04-artifact-distribution.md
  - docs/design/common/07-runtime-provider-pattern.md
  - docs/design/platforms/android/03-artifact-distribution-android.md
  - docs/design/platforms/ios/03-artifact-distribution-ios.md
  - docs/design/platforms/ios/07-recipe-triage.md
---

# Prebuilt runtimes and wheels

kivyforge never builds Python or its C extensions from source. It assembles
prebuilt pieces. This explains which dependencies your app can use on each
target.

## The core rule: no from-source builds

kivyforge has no recipe system and does not cross-compile Python C extensions.
Instead, it:

- downloads a prebuilt, relocatable Python runtime for the target, and
- installs prebuilt, platform-tagged wheels,

then leaves any genuine compilation to the platform's own toolchain, for
example Xcode's Swift Package Manager for Swift packages. This keeps builds
fast and reproducible.

## Where runtimes come from

Each target uses an official or well-maintained prebuilt CPython:

- **iOS**: the official python.org `Python.xcframework`.
- **Android**: the official python.org Android runtime, one per ABI
  (application binary interface).
- **macOS, Linux, and Windows**: a relocatable
  [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
  CPython, bundled into the app.

You choose the version in the overlay's `python` table. For example:

```toml
[tool.kivy.macos.python]
version = "3.13.14"
```

## What this means for your dependencies

Each dependency must be available as a wheel for the target's platform tag:

- **Desktop** targets use ordinary PyPI wheels: `macosx_*` (arm64 or
  universal2), `manylinux_*`, and `win_amd64`.
- **iOS** uses wheels with `ios_*` platform tags.
- **Android** uses wheels with `android_*` platform tags, one per ABI.

A pure-Python dependency works everywhere. A dependency with a C extension works
only where a matching wheel exists. If no wheel exists for a target, kivyforge
cannot build one from source, and `kivyforge lock` fails to resolve it.

### Mobile wheels for Kivy

Kivy, pyjnius, and pyobjus are published as first-party prebuilt iOS and
Android wheels on the
[kivy-mobile-wheels](https://github.com/ElliotGarbus/kivy-mobile-wheels) index
until they land on PyPI. Add the index with `extra_index_urls` in the mobile
overlay, as the mobile examples do:

```toml
[tool.kivy.android]
extra_index_urls = ["https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"]
```

## Integrity

Every artifact is pinned by SHA-256 in the lockfile and verified on download. A
mismatch fails the build. Downloads are cached in a per-user cache shared by all
your projects. To empty it, run `kivyforge clean --cache`.

## What's next

- [Manage dependencies and re-lock](../guides/cross-platform/dependencies.md).
- [Ship native binaries](../guides/cross-platform/native-binaries.md) that are not
  wheels.
- [Lockfiles](lockfiles.md).
