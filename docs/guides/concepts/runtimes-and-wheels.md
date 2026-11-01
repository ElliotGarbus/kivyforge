---
title: Prebuilt runtimes and wheels
sources:
  - docs/design/common/04-artifact-distribution.md
  - docs/design/common/07-runtime-provider-pattern.md
  - docs/design/platforms/android/03-artifact-distribution-android.md
  - docs/design/platforms/ios/03-artifact-distribution-ios.md
  - docs/design/platforms/ios/07-recipe-triage.md
  - docs/design/dev/package-index-proposal.md
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
until they land on PyPI. Rubicon-ObjC, the bridge to Objective-C the iOS
guides use, is pure Python and comes from PyPI. Add the index with `extra_index_urls` in the mobile
overlay, as the mobile examples do:

```toml
[tool.kivy.android]
extra_index_urls = ["https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"]
```

## Where packages come from

!!! note "Preview"
    This describes behavior that is on `main` but not yet in a released
    version. It will ship in a future release. In 3.0.0.dev1 and earlier,
    there were no pins or named indexes, and pip chose among all sources by
    version and wheel tag alone, so a wheel in `find_links` lost to an index
    wheel of the same version.

A package can be available from several places: PyPI, the indexes in
`extra_index_urls` and `[[tool.kivy.index]]`, and the local directories in
`find_links`. When you run `kivyforge lock`, kivyforge decides which of them
each package may come from. The first rule that applies wins:

1. **The package is pinned in `sources`.** It comes only from the index it is
   pinned to. Any wheels for it in `find_links` are ignored, and `lock` warns
   that it ignored them.
1. **The package has a wheel in `find_links`.** It comes only from
   `find_links`, even when an index has a newer version or a better-matching
   wheel.
1. **Otherwise**, it can come from any index except an `explicit` one. pip
   chooses the newest version the specifier allows, then the wheel that best
   matches the target. If two indexes still tie, kivyforge takes the one
   ranked first: the target's `extra_index_urls` in the order you list them,
   then the `[[tool.kivy.index]]` entries in the order you declare them, then
   PyPI.

An index marked `explicit = true` serves only the packages pinned to it. To
declare indexes and pins, see the
[`[tool.kivy]` reference](../reference/pyproject/tool-kivy.md#package-indexes-and-sources).

The source and the version are chosen separately. `lock --update` moves a
package to a newer version within its source. It never moves a package from
your `find_links` directory to an index, or back. To switch a package's
source, change the configuration: add or remove a pin, or a wheel.

A local wheel applies to every architecture or ABI you lock. If `find_links`
has a wheel for a package on one ABI but not another, `lock` fails with
`KF-LOCK-SOURCE-UNAVAILABLE` instead of taking the missing one from an index,
so a lock never mixes your build of a package with someone else's.

Each package in the lockfile records the index its wheels came from, in the
standard `index` field. A package from `find_links` has a `path` instead. See
the [lockfile format](../reference/lockfile.md#packages).

## Integrity

Every artifact is pinned by SHA-256 in the lockfile and verified on download. A
mismatch fails the build. Downloads are cached in a per-user cache shared by all
your projects. To empty it, run `kivyforge clean --cache`. pip keeps a separate
cache for what `lock` resolves, which that leaves alone; `pip cache purge`
clears it.

## What's next

- [Manage dependencies and re-lock](../guides/cross-platform/dependencies.md),
  including [using your own wheels](../guides/cross-platform/dependencies.md#use-your-own-wheels).
- [Ship native binaries](../guides/cross-platform/native-binaries.md) that are not
  wheels.
- [Lockfiles](lockfiles.md).
