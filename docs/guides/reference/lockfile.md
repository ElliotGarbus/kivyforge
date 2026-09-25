---
title: Lockfile format
sources:
  - docs/design/common/03-lockfile-concept.md
  - docs/design/platforms/android/02-pylock-android-spec.md
  - docs/design/platforms/ios/02-pylock-ios-spec.md
  - kivyforge/lock/pep751.py
  - kivyforge/lock/reader.py
  - kivyforge/lock/wheelruntime/serialize.py
  - kivyforge/platforms/ios/lock/writer.py
  - kivyforge/platforms/android/lock/writer.py
  - kivyforge/cli/lock.py
---

# Lockfile format

`kivyforge lock` writes one lockfile per target, named `pylock.<platform>.toml`,
next to `pyproject.toml`. Each file is a valid
[PEP 751](https://peps.python.org/pep-0751/) lockfile plus kivyforge's own
`[tool.kivyforge]` extension table. For why the lock exists and when to commit
it, see [Lockfiles](../concepts/lockfiles.md).

kivyforge generates these files. Don't edit them by hand; re-lock instead.

## Filenames

The filename identifies the target. There is no platform field inside the file.

| Target | Lockfile |
|---|---|
| Android | `pylock.android.toml` |
| iOS | `pylock.ios.toml` |
| macOS | `pylock.macos.toml` |
| Linux | `pylock.linux.toml` |
| Windows | `pylock.windows.toml` |

## Top-level PEP 751 keys

| Key | Description |
|---|---|
| `lock-version` | PEP 751 format version. kivyforge refuses a lock whose major version is newer than it understands. |
| `created-by` | Always `"kivyforge"`. |
| `requires-python` | Copied from `[project].requires-python`, or a kivyforge default if you don't set it. |
| `extras`, `dependency-groups`, `default-groups` | Present for PEP 751 conformance. |

## `[[packages]]`

One entry per resolved Python package, in the standard PEP 751 shape: `name`,
`version`, optional `requires-python`, `marker`, and `dependencies`, and one or
more `[[packages.wheels]]` entries. Each wheel has a `name`, a `url` (or a
project-relative `path` for a local wheel), and `hashes = { sha256 = "..." }`.
A compiled package can list several wheels, one per platform tag the target
needs. See the [PEP 751 specification](https://peps.python.org/pep-0751/) for
the field definitions.

A package can also carry a `[packages.tool.kivyforge]` table, which other PEP 751
tools ignore:

| Key | Description |
|---|---|
| `direct_requirement` | `true` if the package is listed in `[project].dependencies`, rather than pulled in by another package. |
| `source_index` | The index the wheel was resolved from. |

## `[tool.kivyforge]`

Every lock has these keys:

| Key | Description |
|---|---|
| `schema_version` | Version of the `[tool.kivyforge]` table layout. |
| `kivyforge_version` | The kivyforge version that wrote the lock. |
| `generated_at` | When the lock was written. |
| `pyproject_sha256` | SHA-256 of the whole `pyproject.toml` the lock was resolved from. Used for drift detection. |

The rest of the table depends on the target.

### Desktop: macOS, Linux, and Windows

| Table or key | Description |
|---|---|
| `tool_kivyforge_schema_version` | The overlay's `schema_version`, echoed from `pyproject.toml`. |
| `archs` | The architectures the lock covers. |
| `[tool.kivyforge.python_runtime]` | The bundled CPython runtime: `provider`, `version`, and an optional OS `floor`. |
| `[[tool.kivyforge.python_runtime.artifacts]]` | One runtime archive per architecture: `arch`, `url`, `sha256`, `archive_format`. |
| `[[tool.kivyforge.native_binaries]]` | One entry per [native binary](../guides/cross-platform/native-binaries.md): `name`, `version`, `url` or `path`, `sha256`. |

### iOS

| Table or key | Description |
|---|---|
| `tool_kivyforge_schema_version` | The overlay's `schema_version`, echoed from `pyproject.toml`. |
| `[tool.kivyforge.python_xcframework]` | The `Python.xcframework` runtime: `version`, `url`, `sha256`. |
| `[[tool.kivyforge.xcframeworks]]` | Standalone native xcframeworks: `name`, `version`, `url` or `path`, `sha256`, `slices`, `archive_format`, `link`, `embed`, and optional fields. |
| `[[tool.kivyforge.swift_packages]]` | [Swift packages](../guides/ios/swift-packages.md): `name`, `url` or `path`, the requirement and resolved `revision` or `version`, `products`, `link`, `embed`. |

### Android

| Table or key | Description |
|---|---|
| `tool_kivy_android_schema_version` | The overlay's `schema_version`, echoed from `pyproject.toml`. |
| `kivy_generation` | The Kivy generation the lock was resolved for (`2` or `3`). |
| `[[tool.kivyforge.python_android]]` | The python.org Android runtime, one entry per ABI (application binary interface): `version`, `abi`, `url` or `path`, `sha256`, `min_api`. |
| `[[tool.kivyforge.android_libs]]` | [`.aar` and `.jar` libraries](../guides/android/java-libraries.md): `name`, `kind`, `version`, `url` or `path`, `sha256`. |
| `[tool.kivyforge.gradle]` | Present only when you declare Maven dependencies: the declared `dependencies` and `repositories`, plus `[[tool.kivyforge.gradle.resolved]]` entries, each with a `coordinate` and per-file SHA-256 `artifacts`. |
| `[[tool.kivyforge.include_files]]` | One entry per file copied by `include_files`: `source`, `dest`, `sha256`. |

## Integrity

Every wheel, runtime, and native artifact is pinned by SHA-256 and verified when
it is downloaded. A mismatch fails the build. Entries are written in a fixed
order, so re-locking changes only the lines whose pins changed.

## Drift

Because `pyproject_sha256` hashes the whole `pyproject.toml`, any edit to the
file, including a comment, makes the lock stale:

- `build` and `package` refuse a stale lock with `KF-LOCK-DRIFT` and exit code `4`.
  `--no-verify-lock` skips this check.
- `lock --check` re-resolves, compares the result with the committed lock
  (ignoring `generated_at`), and exits `4` if they differ. It writes nothing.

To fix a stale lock, run `kivyforge lock -p PLATFORM`, replacing `PLATFORM` with
the target. See
[Manage dependencies and re-lock](../guides/cross-platform/dependencies.md).

## What's next

- [Lockfiles](../concepts/lockfiles.md)
- [Manage dependencies and re-lock](../guides/cross-platform/dependencies.md)
- [CLI reference](cli.md)
