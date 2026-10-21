# 01 — `pyproject.toml`: Shared Config + Overlay Pattern

`pyproject.toml` is the **sole user-facing surface** for declaring how a Kivy app is built, for every platform. The configuration lives in tables inside the project's existing `pyproject.toml`:

- **`[project]`** — PEP 621. App name, version, description, dependencies, authors. *Shared* across all platforms.
- **`[tool.kivy]`** — cross-platform Kivy metadata (display name, app source layout, entry point, orientation). *Shared* across all platforms.
- **`[tool.kivy.<platform>]`** — a per-platform **additive overlay** (e.g. `[tool.kivy.ios]`, `[tool.kivy.macos]`, `[tool.kivy.android]`). Consumed only by that platform's backend.

The file is hand-edited (after being seeded by `kivyforge init`) and committed to version control. `kivyforge lock` generates a `pylock.<platform>.toml` from it for the resolved target; `kivyforge build` consumes the lock.

This document defines the **shared** tables and the overlay pattern. The full field reference for each platform lives in its own overlay doc — e.g. [iOS `[tool.kivy.ios]`](../platforms/ios/01-pyproject-ios.md).

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
# ... iOS-specific fields (see platforms/ios/01-pyproject-ios.md)

[tool.kivy.macos]
schema_version = 1
# ... macOS-specific fields (see platforms/macos/macos-spec.md)
```

The two tables `[project]` and `[tool.kivy]` are **the cross-platform contract**. Everything inside a `[tool.kivy.<platform>]` overlay is consumed only by that platform's backend. The cross-tool agreement is that **adding a Python dependency to `[project].dependencies` resolves for every platform the same way** — only the artifact-binding subtables (e.g. `[tool.kivy.ios.native.xcframeworks]`) differ.

## `[project]` (PEP 621)

Every platform backend consumes at least `name`, `version`, and `dependencies`; the rest are passed through where a platform exposes a slot for them. `dependencies` is a single PEP 508 list for all platforms — `kivyforge lock` evaluates environment markers against the *resolved target* and resolves the matching subset to wheels in that target's lockfile. Each platform overlay doc lists exactly how it consumes each PEP 621 key (see, e.g., [iOS `[project]` consumption](../platforms/ios/01-pyproject-ios.md#project-pep-621--ios-consumption)).

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
| `entry_point`  | string         | no       | the one `[project.gui-scripts]` entry, else `"main"` | Where the app starts, resolved after putting `app_dir` on `sys.path`. A dotted module (`"main"`, `"pkg.start"`) is **run as `__main__`** (the equivalent of `python -m entry_point`) on every platform — see the callout below for what that means for packages. A `module:function` reference (`"pkg.app:main"`) is **called**, the way an installed script calls it — see "[`module:function` and `[project.gui-scripts]`](#modulefunction-and-projectgui-scripts)". |
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
| `./src/myapp/app.py` with `def main()`, a package using relative imports | `"src"` | `"myapp.app:main"`, or unset with `[project.gui-scripts] myapp = "myapp.app:main"` |

> **`entry_point` runs as `__main__` on every platform — as of 2026-09-21, unified.** All five launchers now do the equivalent of `python -m entry_point`: `runpy.run_module(entry_point, run_name="__main__", alter_sys=True)` on Android/iOS, `runpy.run_module(..., run_name="__main__")` on Windows, an `-m`-style exec on Linux/macOS. `if __name__ == "__main__": App().run()` — the ordinary Python idiom, and how a buildozer/python-for-android app is normally written — now works everywhere. Calling `App().run()` unconditionally at module top level also still works everywhere (a `runpy`/`-m`-style run executes top-level code exactly like an import does), so either style is portable.
>
> **This was a real, silent migration trap until it was fixed, and existing code should be re-checked.** Before 2026-09-21, Android and iOS *imported* `entry_point` (`PyImport_ImportModule`) instead, so `__name__` was the module's own dotted name and `if __name__ == "__main__":` blocks silently never ran — no traceback, nothing in the log naming the cause (docs/design/dev/roadmap.md and test-matrix.md §7 have the full history; credit to [PR #1](https://github.com/ElliotGarbus/kivyforge/pull/1) for catching the iOS half first). If your project predates this fix and worked around it by calling `App().run()` unconditionally, no change is needed. If it relied on the *old* Android/iOS import-only behavior in some other way — see the next paragraph — check it against the new behavior.
>
> **Pointing `entry_point` at a package now requires a `__main__.py` on every platform**, matching ordinary `python -m` semantics (`runpy` runs the package's `__main__.py`, and fails if it has none). Before 2026-09-21, Android and iOS ran the package's `__init__.py` instead, since they used a plain import — if your project used a package-style `entry_point` relying on that, either add a `__main__.py` or move to an explicitly-named module (e.g. `myapp/start.py` with `entry_point = "myapp.start"`).

### `module:function` and `[project.gui-scripts]`

A project laid out as a package usually already declares how it starts, for `pip install` and `uv run`, as a PEP 621 script:

```toml
[project.gui-scripts]
myapp = "myapp.app:main"

[tool.kivy]
app_dir = "src"          # src/myapp/__init__.py, src/myapp/app.py, ...
# no entry_point: the one gui-script above is used
```

kivyforge resolves the entry point in this order:

1. `[tool.kivy].entry_point`, if set — in either form below.
2. Otherwise, the `[project.gui-scripts]` entry, if there is exactly one.
3. Otherwise, with no gui-scripts, `"main"`, as before.

More than one gui-script and no `entry_point` is a config error naming them: an app starts one entry point, so set `entry_point` to the one it should. `[project.scripts]` (console scripts) is never used: no kivyforge app is a console program. A gui-script must name a function (the entry-points spec's `module:object`), since that is all an installer accepts; a bare module there is an error that suggests setting `entry_point` to it instead. If `[project].dynamic` lists `gui-scripts`, the build backend may add entries kivyforge cannot see, so a static gui-script is not taken to be the only one: set `entry_point`.

The two forms of an entry point behave differently, and on purpose:

| Written as | What runs | Use it for |
| --- | --- | --- |
| `"main"`, `"pkg.start"` | that module, as `__main__` (`python -m`) | a script-style app, including every Buildozer-style app; **unchanged** |
| `"pkg.app:main"`, `"pkg.app:App.launch"` | `from pkg.app import main; sys.exit(main())` | a package whose code uses relative imports, and anything declared as a gui-script |

The function form follows the [entry-points spec](https://packaging.python.org/en/latest/specifications/entry-points/#use-for-scripts): the function is called with no arguments, and what it returns is the exit status (`None` is `0`). kivyforge generates the small launcher an installer would (`kivyforge/bundle/entry_launcher.py`) and runs *that* as `__main__`. That is the difference that matters: run as `__main__`, `src/pkg/app.py` is not part of its package, so `from . import helper` fails; imported by the launcher, it is `pkg.app`, exactly as under `uv run myapp`. The module part may also be a package (`"pkg:main"` imports `pkg/__init__.py`). Extras on a gui-script (`"pkg.app:main [gui]"`) are ignored, as the spec allows.

Where the launcher lives: Windows, macOS, Linux and Android write it into the bundle's copy of `app_dir` as `_kivyforge_main.py`, before byte-compiling, so a `strip_source` release ships it as a sourceless `.pyc` like the rest of the app; it is not listed in the app's `top_level.txt`. iOS compiles the same source into `main_config.h` (`ENTRY_LAUNCHER`), because a debug build's `app/` is a link to your source tree, which kivyforge never writes into. The package metadata (`entry_points.txt`) lists the gui-script exactly as declared, on every platform.

## Icons and splash screens are per-platform

Icons and splash screens are inherently platform-specific: iOS requires a 1024×1024 flat PNG (Xcode generates all sizes into an asset catalog); Android adaptive icons require separate foreground and background layers; splash-screen aspect ratios and conventions differ further. A single shared asset set cannot satisfy all platforms correctly, so **each platform declares its own icon and splash in its own overlay subtable** (e.g. `[tool.kivy.ios.icons]`). See the relevant overlay doc for the exact fields.

## Platform overlays

Each `[tool.kivy.<platform>]` overlay is documented in its own file:

- **iOS** — [`[tool.kivy.ios]` overlay schema](../platforms/ios/01-pyproject-ios.md)
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

- A backend **acts on** only its own overlay. Running an iOS command builds from `[tool.kivy.ios]`; a `[tool.kivy.macos]` table alongside it is inert for that command, though it is still validated (every overlay is parsed on every load).
- Every overlay follows the same **additive overlay + independent `schema_version`** convention.
- App developers may add an overlay for a not-yet-implemented platform today without breaking any current command: an unrecognised *table* directly under `[tool.kivy]` is accepted and ignored.

## Unknown keys

Any other key under `[tool.kivy]` that kivyforge does not read is a **validation error**, reported with its line and, when a known key is close, a "did you mean" hint. This covers a misspelt key (`deployment_targt`), a table a design doc specifies but no release implements yet, and a key from a newer kivyforge. Dropping such a key silently was worse than failing: the build went ahead as if it had never been written, and nothing told the user. The allow-list is `kivyforge/config/keys.py`, checked before any value is parsed so a misspelt *required* key reports as a typo rather than as missing.

Three things are deliberately not checked:

- **Keys outside `[tool.kivy]`.** `[project]` belongs to PEP 621 and the rest of `[tool]` to other tools.
- **Passthrough tables**, whose keys belong to another tool: `ios.info_plist`, `ios.entitlements`, `ios.xcode.build_settings`, `macos.entitlements`, `android.manifest.application`/`.activity`/`.placeholders`, and `android.gradle_properties`. Their own managed/reserved-key rules still apply.
- **An unrecognised table directly under `[tool.kivy]`**, per the reservation rule above. This does not reopen the typo hole: an overlay only takes effect when a verb targets it, and targeting a misspelt one fails as missing, naming the near-miss table (`found [tool.kivy.andriod]; rename it to [tool.kivy.android]`).

## Validation

Each platform's backend validates `[project]`, `[tool.kivy]`, and its own `[tool.kivy.<platform>]` overlay when a command targets that platform. The shared rules (present `[project].name`/`version`; `app_dir` names a real subdirectory; `entry_point` is a valid dotted identifier, optionally followed by `:function`; without `entry_point`, at most one `[project.gui-scripts]` entry; `orientation` values are in the allowed set) apply everywhere; platform-specific rules live in each overlay doc (e.g. [iOS validation rules](../platforms/ios/01-pyproject-ios.md#validation-rules-ios)). Validation errors are printed with the offending line number (TOML parsers expose this) and a remediation hint.
