# 01 — `pyproject.toml`: Shared Config + Overlay Pattern

`pyproject.toml` is the **sole user-facing surface** for declaring how a Kivy app is built, for every platform. The configuration lives in tables inside the project's existing `pyproject.toml`:

- **`[project]`** — PEP 621. App name, version, description, dependencies, authors. *Shared* across all platforms.
- **`[tool.kivy]`** — cross-platform Kivy metadata (display name, app source layout, entry point, orientation). *Shared* across all platforms.
- **`[tool.kivy.<platform>]`** — a per-platform **additive overlay** (e.g. `[tool.kivy.ios]`, `[tool.kivy.macos]`, `[tool.kivy.android]`). Consumed only by that platform's backend.

The file is hand-edited (after being seeded by `kivyforge init`) and committed to version control. `kivyforge lock` generates a `pylock.<platform>.toml` from it for the resolved target; `kivyforge build` consumes the lock.

This document defines the **shared** tables and the overlay pattern. The full field reference for each platform lives in its own overlay doc — e.g. [iOS `[tool.kivy.ios]`](../platforms/ios/pyproject-ios.md).

## Design principles

- **Single source of truth.** One `pyproject.toml` per app. Every platform backend reads the same `[project]` and the same `[tool.kivy]` tables; only the `[tool.kivy.<platform>]` overlay differs.
- **PEP-aligned.** PEP 621 (`[project]`), PEP 518 (`[tool.*]` namespace). No invented file formats.
- **Declarative.** Every field describes intent, not action. No imperative statements, no shell hooks.
- **Additive overlays.** A `[tool.kivy.<platform>]` overlay only contains keys whose value must differ from the cross-platform default in `[tool.kivy]`, or keys meaningful only on that platform (e.g. `bundle_id` on iOS).
- **Schema-versioned per platform.** Each platform overlay carries its own `schema_version` integer — `[tool.kivy.ios].schema_version`, `[tool.kivy.macos].schema_version`, etc. Platform backends evolve on independent cadences; locking them to a shared number would force coupled releases. The shared `[tool.kivy]` table itself is **unversioned**: each platform's overlay documents which `[tool.kivy]` keys it consumes and validates them as part of its own `schema_version`. Adding a new key under `[tool.kivy]` is always backward-compatible at the parser level (extra TOML keys are ignored); semantic consumption is opt-in per platform via a `schema_version` bump on the side that adopts it.
- **TOML-native.** Stable, parseable by `tomllib` (stdlib since Python 3.11), readable to humans.

## Top-level structure

```toml
# Standard PEP 621 metadata — shared by every platform.
[project]
name = "myapp"
version = "0.1.0"
description = "A Kivy app"
requires-python = ">=3.15"
# One dependency list for all platforms; PEP 508 markers select platform-specific entries.
dependencies = [
    "kivy>=3.0,<4",
    "pillow>=11",
    "ios-only-helper>=1.0; sys_platform == 'ios'",
    "android-only-helper>=1.0; sys_platform == 'android'",
]
authors = [{ name = "Your Name", email = "you@example.com" }]

# Cross-platform Kivy configuration. Unversioned: each platform overlay
# declares its own schema_version and validates its consumption of these keys.
[tool.kivy]
display_name = "My App"
app_dir = "src"
entry_point = "main"
orientation = ["portrait"]

# Per-platform additive overlays. Each is consumed only by its own backend and
# carries an independent schema_version. Add one overlay per target you build.
[tool.kivy.ios]
schema_version = 1
# ... iOS-specific fields (see platforms/ios/pyproject-ios.md)

[tool.kivy.macos]
schema_version = 1
# ... macOS-specific fields (see platforms/macos/macos-spec.md)
```

The two tables `[project]` and `[tool.kivy]` are **the cross-platform contract**. Everything inside a `[tool.kivy.<platform>]` overlay is consumed only by that platform's backend. The cross-tool agreement is that **adding a Python dependency to `[project].dependencies` resolves for every platform the same way** — only the artifact-binding subtables (e.g. `[tool.kivy.ios.native.xcframeworks]`) differ.

## `[project]` (PEP 621)

Every platform backend consumes at least `name`, `version`, and `dependencies`; the rest are passed through where a platform exposes a slot for them. `dependencies` is a single PEP 508 list for all platforms — `kivyforge lock` evaluates environment markers against the *resolved target* and resolves the matching subset to wheels in that target's lockfile. Each platform overlay doc lists exactly how it consumes each PEP 621 key (see, e.g., [iOS `[project]` consumption](../platforms/ios/pyproject-ios.md#project-pep-621--ios-consumption)).

Anything PEP 621 specifies is honored by every PEP 621-compliant tool — so ruff, mypy, uv, pdm, and pip all stay happy with the same file.

## `[tool.kivy]`

```toml
[tool.kivy]
display_name = "My App"
app_dir = "src"      # folder holding your app code; the project root (".") is not allowed
entry_point = "main"
orientation = ["portrait", "portrait-upside-down"]
```

`[tool.kivy]` carries fields meaningful to every Kivy platform. It has **no `schema_version` of its own** — see "Schema-versioned per platform" above.

| Field          | Type           | Required | Default                 | Description |
| -------------- | -------------- | -------- | ----------------------- | ----------- |
| `display_name` | string         | no       | `[project].name` titled | App display name shown to the user. Each platform maps it to its native slot (iOS `CFBundleDisplayName`, Android `android:label`, etc.). |
| `app_dir`      | string         | yes      | —                       | Folder containing your `.py` source files, relative to `pyproject.toml`. **Must be a subdirectory** (e.g. `"src"`); the project root (`"."`), an empty value, an absolute path, or a path escaping the project are all rejected — see "`app_dir` + `entry_point` interaction" below. |
| `entry_point`  | string         | no       | `"main"`                | Python module reference (dotted name). The generated bootstrap does the equivalent of `PyImport_ImportModule(entry_point)` after putting `app_dir` on `sys.path`. |
| `orientation`  | list of string | no       | `["portrait"]`          | Allowed orientations. Valid: `portrait`, `portrait-upside-down`, `landscape-left`, `landscape-right`. Platforms map the declared list to their own conventions (see each overlay doc for platform-specific handling). |

### `app_dir` + `entry_point` interaction

These two fields together specify *what* code runs and *where it lives*. `entry_point` defaults to `"main"`; `app_dir` has **no default and is required** — `kivyforge init` seeds it to `"src"` (the recommended layout), and a project that keeps its code elsewhere adjusts it by hand.

> **`app_dir` must be a subdirectory — the project root (`"."`) is rejected.** Two problems make `"."` unsafe, so the toolchain refuses it outright:
> - **Bundle bloat / dev-file leakage.** The generated app copies `app_dir` wholesale into the bundle. Pointed at the project root, it sweeps in `.git/`, `.venv/`, `tests/`, `__pycache__/`, `pyproject.toml`, and everything else at the root.
> - **Build-output recursion.** The generated build output lives at the project root, so `app_dir = "."` would point the copy at a folder that *contains its own build product* — recursively copying generated artifacts into the bundle.
>
> Putting your code under a subdirectory like `src/` (with `app_dir = "src"`) avoids both. This also means kivyforge needs no per-*file* exclusion mechanism for bundle contents. A single-file app simply lives at `src/main.py`.

Example layouts:

| Layout                                                   | `app_dir` | `entry_point`   |
| -------------------------------------------------------- | --------- | --------------- |
| `./src/main.py`                                          | `"src"`   | `"main"`        |
| `./src/app.py`                                           | `"src"`   | `"app"`         |
| `./src/start.py` (no `src/__init__.py`)                  | `"src"`   | `"start"`       |
| `./src/myapp/start.py` (only `src/myapp/__init__.py`)    | `"src"`   | `"myapp.start"` |

> **`entry_point` is *imported*, not run as `__main__`.** The bootstrap does the equivalent of `PyImport_ImportModule(entry_point)`, so `entry_point` must name a module whose top-level code starts the app *on import*. Pointing it at a package (e.g. `"myapp"`) runs that package's `__init__.py`, **not** its `__main__.py`. If your launch code lives in `myapp/__main__.py`, either move it to an explicitly-named module (e.g. `myapp/start.py` with `entry_point = "myapp.start"`) or have `__init__.py` import and run it.

## Icons and splash screens are per-platform

Icons and splash screens are inherently platform-specific: iOS requires a 1024×1024 flat PNG (Xcode generates all sizes into an asset catalog); Android adaptive icons require separate foreground and background layers; splash-screen aspect ratios and conventions differ further. A single shared asset set cannot satisfy all platforms correctly, so **each platform declares its own icon and splash in its own overlay subtable** (e.g. `[tool.kivy.ios.icons]`). See the relevant overlay doc for the exact fields.

## Platform overlays

Each `[tool.kivy.<platform>]` overlay is documented in its own file:

- **iOS** — [`[tool.kivy.ios]` overlay schema](../platforms/ios/pyproject-ios.md)
- **macOS** — [`[tool.kivy.macos]` overlay](../platforms/macos/macos-spec.md)
- **Linux** — [`[tool.kivy.linux]` overlay](../platforms/linux/linux-spec.md#toolkivylinux-overlay)
- **Windows** — [`[tool.kivy.windows]` overlay](../platforms/windows/windows-spec.md#toolkivywindows-overlay) (design settled; implementation not started)
- **Android** — reserved (see below); documented when the platform lands.

## Reserved platform namespaces

The `[tool.kivy]` namespace accommodates every current and future Kivy platform. Overlay subtable names are reserved per platform:

| Namespace             | Platform |
| --------------------- | -------- |
| `[tool.kivy.ios]`     | iOS |
| `[tool.kivy.macos]`   | macOS |
| `[tool.kivy.android]` | Android |
| `[tool.kivy.windows]` | Windows (all architectures). Field reference in the [Windows spec](../platforms/windows/windows-spec.md#toolkivywindows-overlay). |
| `[tool.kivy.linux]`   | Linux, including Raspberry Pi (any architecture). Architecture-specific settings, if needed, belong as sub-keys within `[tool.kivy.linux]` (e.g. `[tool.kivy.linux.aarch64]`) rather than a separate namespace — mirroring how `sys_platform` and `platform_machine` are separate concepts in PEP 508 markers. |

Reservation semantics:

- A backend **ignores** overlays for other platforms (unknown keys are silently passed over by TOML parsers and are not validated). Running an iOS command reads only `[tool.kivy.ios]`; a `[tool.kivy.macos]` table alongside it is inert for that command.
- Every overlay follows the same **additive overlay + independent `schema_version`** convention.
- App developers may add an overlay for a not-yet-implemented platform today without breaking any current command.

## Validation

Each platform's backend validates `[project]`, `[tool.kivy]`, and its own `[tool.kivy.<platform>]` overlay when a command targets that platform. The shared rules (present `[project].name`/`version`; `app_dir` names a real subdirectory; `entry_point` is a valid dotted identifier; `orientation` values are in the allowed set) apply everywhere; platform-specific rules live in each overlay doc (e.g. [iOS validation rules](../platforms/ios/pyproject-ios.md#validation-rules-ios)). Validation errors are printed with the offending line number (TOML parsers expose this) and a remediation hint.
