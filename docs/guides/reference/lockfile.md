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
  - kivyforge/lock/sources.py
---

# Lockfile format

`kivyforge lock` writes one lockfile per target, named `pylock.<platform>.toml`,
next to `pyproject.toml`. Each file is a valid
[PEP 751](https://peps.python.org/pep-0751/) lockfile plus kivyforge's own
`[tool.kivyforge]` extension table. For why the lock exists and when to commit
it, see [Lockfiles](../concepts/lockfiles.md).

kivyforge generates these files. Change a version in `[project].dependencies`
and re-lock. See
[Pin a package version](../guides/cross-platform/dependencies.md#pin-a-package-version).
The next `lock` overwrites a hand-edited file.

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
`version`, optional `requires-python`, `marker`, `dependencies`, and `index`,
and one or more `[[packages.wheels]]` entries. Each wheel has a `name`, a `url`
(or a project-relative `path` for a local wheel), and
`hashes = { sha256 = "..." }`. A compiled package can list several wheels, one
per platform tag the target needs. See the
[PEP 751 specification](https://peps.python.org/pep-0751/) for the field
definitions.

`index` is the base URL of the index the package's wheels came from, such as
`https://pypi.org/simple/`. A package from `find_links` has no `index`; its
wheels have a `path`. A package whose wheels came from different indexes on
different targets, or from a page that matches no configured index, also has
none. `build` installs from each wheel's `url` or `path` and does not use
`index`. See
[Where packages come from](../concepts/runtimes-and-wheels.md#where-packages-come-from).

!!! note "Preview"
    This describes behavior that is on `main` but not yet in a released
    version. It will ship in a future release. Locks written by 3.0.0.dev1 and
    earlier have no `index`. They stay valid, and `lock --check` does not count
    the missing `index` as drift. The next re-lock adds it.

A package can also carry a `[packages.tool.kivyforge]` table, which other PEP 751
tools ignore:

| Key | Description |
|---|---|
| `direct_requirement` | `true` if the package is listed in `[project].dependencies`, rather than pulled in by another package. |

## `[tool.kivyforge]`

Every lock has these keys:

| Key | Description |
|---|---|
| `schema_version` | Version of the `[tool.kivyforge]` table layout. |
| `kivyforge_version` | The kivyforge version that wrote the lock. |
| `generated_at` | When the lock was written. |
| `lock_inputs_sha256` | SHA-256 of the lock inputs: the parsed `pyproject.toml` values the lock was resolved from. Used for drift detection. |

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
| `[tool.kivyforge.gradle]` | Present only when you declare Maven dependencies: the declared `dependencies` and `repositories`, the declared BOMs as `platforms` (only when you list any), plus `[[tool.kivyforge.gradle.resolved]]` entries, each with a `coordinate` and per-file SHA-256 `artifacts`. A dependency you declared without a version appears in `resolved` with the version its BOM chose. Gradle plugins are not recorded in the lock. |
| `[[tool.kivyforge.include_files]]` | One entry per file copied by `include_files`: `source`, `dest`, `sha256`. |

## Integrity

Every wheel, runtime, and native artifact is pinned by SHA-256 and verified when
it is downloaded. A mismatch fails the build. Entries are written in a fixed
order, so re-locking changes only the lines whose pins changed.

## Drift

`lock_inputs_sha256` hashes the lock inputs: `[project].dependencies` and
`requires-python`, plus the target's Python version, architectures, OS floor,
indexes, `find_links`, `exclude`, and native libraries. When one of them
changes, the lock is stale. Comments, key order, and every other field are
not inputs.

- `build` and `package` refuse a stale lock with `KF-LOCK-DRIFT` and exit code `4`.
  `--no-verify-lock` skips this check.
- `lock --check` re-resolves, keeping the locked versions, compares the result
  with the committed lock (ignoring `generated_at`), and exits `4` if they
  differ. It writes nothing.

To fix a stale lock, run `kivyforge lock -p PLATFORM`, replacing `PLATFORM` with
the target. That command keeps the locked versions and moves only what the
change requires. If it cannot, it fails with `KF-LOCK-PINS-CONFLICT`, and
`kivyforge lock -p PLATFORM --update` takes the newest version each specifier
allows. See
[Pin a package version](../guides/cross-platform/dependencies.md#pin-a-package-version).

## What's next

- [Lockfiles](../concepts/lockfiles.md)
- [Manage dependencies and re-lock](../guides/cross-platform/dependencies.md)
- [CLI reference](cli.md)
