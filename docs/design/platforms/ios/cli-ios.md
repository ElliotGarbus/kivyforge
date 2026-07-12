# iOS — CLI Behavior

This document defines the **iOS-specific behavior** of the kivyforge CLI verbs —
the flags, the `xcodebuild` integration, the iOS `doctor` checks, and the
`kivy.mobile` geometry surface. For the cross-platform verb model, the `--platform` / `-p` selector, the
`KIVYFORGE_PLATFORM` env var, and the platform-resolution chain, see
[common CLI + platform resolution](../../common/02-cli-and-platform-resolution.md).

All verbs look for `pyproject.toml` in the **current working directory only**; no
parent-directory traversal is performed. Run `kivyforge` commands from the
directory that contains your `pyproject.toml`.

## Verbs (iOS behavior)

| Verb | iOS behavior |
|------|--------------|
| `init` | Seed `[tool.kivy]` + `[tool.kivy.ios]` into `pyproject.toml`. See below. |
| `lock` | Resolve `[project].dependencies` and `[tool.kivy.ios.native.xcframeworks]`; write `pylock.ios.toml`. `--check` exits non-zero if the lock is out of date without writing (CI pre-flight). |
| `build` | Download artifacts, populate `pip-deps/` and `Frameworks/`, and (re)generate the `<app>-ios/` Xcode project. Without target flags, stops here — the project is ready to open in Xcode IDE. |
| `build --simulator\|--device\|--release` | Same as `build`, then invokes `xcodebuild`. `--simulator` / `--device`: Debug build. `--release`: archives and exports a `.ipa` to `<app>-ios/build/<app>.ipa` (App Store / TestFlight). |
| `open` | Open the generated `<app>-ios/<app>.xcodeproj` in Xcode. Typical developer flow: `kivyforge build` → `kivyforge open` → select device in Xcode → ⌘R. |
| `run [--simulator\|--device] [--destination NAME_OR_UDID]` | Build (unless `--no-build`), install, and launch the app on a simulator or connected device. Single-command alternative to the Xcode IDE flow. |
| `upgrade` | Re-download pinned `Python.xcframework` and xcframework artifacts per the existing lock. Does not touch pip-deps, the Xcode project, or app code. |
| `clean [--cache]` | Remove generated artifacts in the project folder. With `--cache`, also flush the artifact download cache. |
| `status` | Show current project state: app identity, Python version, lock sync, and build output for each target. Read-only; no side effects. |
| `doctor` | Substantive health check. |

## Verb-by-verb specifics

### `kivyforge init`

Flags:

- `--force` (overwrite an existing `[tool.kivy.ios]` table)

`kivyforge init` is a pure file-in / file-out operation: it reads the user's `pyproject.toml`, auto-fills metadata, and writes `[tool.kivy]` + `[tool.kivy.ios]`. A `pyproject.toml` is required — init does not migrate `requirements.txt` automatically.

**If `requirements.txt` is found but no `pyproject.toml`**, init exits non-zero with a migration pointer:

```
Error: requirements.txt found but no pyproject.toml.
  kivyforge requires pyproject.toml — it will not migrate requirements.txt
  automatically. Transfer your dependencies to a new pyproject.toml:

    [project]
    name = "myapp"  # your app name
    version = "0.1.0"
    dependencies = [
        "kivy>=3.0",
        # ... paste your other requirements here
    ]

  Then re-run kivyforge init.
```

Version pinning of `[project].dependencies` is **not** init's job — that is `kivyforge lock`'s responsibility (it resolves the full graph to exact wheels in `pylock.ios.toml`). Init never rewrites an existing `[project]`. A venv is not required; if one is active, init uses it only to **warn** when an installed version falls outside a declared specifier (an informational nudge, never a rewrite).

**Write path (`pyproject.toml` already exists):** init *only* adds or updates the `[tool.kivy]` and `[tool.kivy.ios]` tables. It never modifies `[project]`, `[tool.poetry]`, `[tool.pdm]`, or any other non-kivy namespace. Authoritative version pinning happens later, in `pylock.ios.toml`, via `kivyforge lock`.

**`app_dir` / `entry_point`**: init seeds `app_dir = "src"` and `entry_point = "main"` (the recommended layout). `app_dir` is required and must name a subdirectory — the project root (`"."`) is rejected (see [common pyproject spec §"`app_dir` + `entry_point` interaction"](../../common/01-pyproject-kivy-spec.md#app_dir--entry_point-interaction)). A project that keeps its code somewhere other than `src/` adjusts the seeded value by hand, the same way it fills in `bundle_id` and `signing.team_id`.

**Seeded tables and TODO stubs**: beyond the required `schema_version` / `bundle_id` / `build` / `deployment_target`, init seeds `[tool.kivy.ios.python]` (the pinned `Python.xcframework` version) and `[tool.kivy.ios.signing]`, and emits **commented TODO stubs** for the things most projects want next: `[tool.kivy.ios.icons]` (`source` — an app icon is required for App Store submission), `[tool.kivy.ios.splash]` (`source`/`background`), and a `simulator_archs` line. The stubs are commented so the build-time defaults stay in effect (no app icon configured, both simulator arches pinned) until the user fills them in — uncommenting an icon `source` that points at a missing file would otherwise fail icon validation. When `kivy` is a direct dependency, init also seeds the documented `exclude` block (see [iOS pyproject §"Excluding unused transitive dependencies"](pyproject-ios.md#excluding-unused-transitive-dependencies-exclude)).

**`--force`**: without it, init exits non-zero if `[tool.kivy.ios]` already exists. With it, the `[tool.kivy.*]` tables are regenerated, but the **user-specific values that init can't re-derive are preserved** rather than reset: the full `[tool.kivy.ios.signing]` table (`team_id`, `identity`, `provisioning_profile`, `auto_signing`), the pinned `[tool.kivy.ios.python].version`, the `simulator_archs` list, and the `[tool.kivy.ios.icons]` / `[tool.kivy.ios.splash]` sources/background. Each is preserved only when the user actually set it; an untouched commented stub is re-emitted as a stub so the default still holds. Silently resetting any of these would break a project that already has working signing, a chosen Python pin, a narrowed simulator set, or configured assets. (Other fields — `deployment_target`, `orientation`, the `exclude` block, etc. — are regenerated to their template defaults on `--force`.)

### `kivyforge lock`

Flags:

- `--update` (re-resolve even if `pylock.ios.toml` exists and the pyproject hash matches; useful for `pip`-side updates from new wheel releases)
- `--offline` (use cached resolution results; error if the cache is incomplete)
- `--check` (resolve and compute what the new lockfile would contain, diff against the existing `pylock.ios.toml`, exit non-zero if they differ, write nothing; for CI pre-flight)

Lock acts on the current working directory's `pyproject.toml`. Exits non-zero with a clear error if no pyproject is present or it lacks `[tool.kivy.ios]`.

**`--check` mode.** Performs the full resolution (same as a normal `kivyforge lock` run) but writes nothing. If the computed lockfile matches the existing `pylock.ios.toml` exactly, exits 0. If it differs, prints a summary of what changed (packages added/removed/updated, xcframework version changes) and exits non-zero. Typical CI use:

```yaml
- run: kivyforge lock --check   # fail PR if pyproject.toml was edited without re-locking
```

### `kivyforge build`

Flags:

- `--simulator` / `--device` / `--release` (optional; mutually exclusive; **no default**). When none is passed, `build` stops after generating the Xcode project (step 6) and leaves it ready to open in Xcode; because no target is named, the bare build collects **both** the device and simulator pip-deps slices (step 4) so the project builds either Xcode destination — Xcode usually defaults to a simulator — without re-running the toolchain. When one is passed, `build` collects only that target's slice and also invokes `xcodebuild` (step 7): `--simulator` → iphonesimulator SDK + Debug; `--device` → iphoneos SDK + Debug; `--release` → archive + export `.ipa` via iphoneos SDK + Release (see step 7 details below).
- `--arch arm64|x86_64` (default: auto-detect from host; needed for Intel simulator builds on `macos-15-intel`)
- `--no-verify-lock` (skip the `[tool.kivyforge].pyproject_sha256` drift check; for CI only)
- `--no-cache` (force re-download of every artifact)
- `--team-id ID` (override `[tool.kivy.ios.signing].team_id`; also read from `KIVYFORGE_TEAM_ID` env var; useful for CI and team projects where signing config is not committed)
- `--signing-identity NAME` (override `[tool.kivy.ios.signing].identity`; also read from `KIVYFORGE_SIGNING_IDENTITY` env var). The precedence chain differs by target: for `--device`, flag → env → `[tool.kivy.ios.signing].identity` (the pyproject default, `"Apple Development"`, applies — correct for a local debug build). For `--release`, only an explicit flag or env value is honored; the pyproject default is **never** applied to a distribution archive/export — forcing a `"Apple Development"` identity onto it would request a Development-type profile instead of letting automatic signing pick the Distribution certificate the chosen `--export-method` actually needs. Leave `--signing-identity` unset for `--release` unless you need to pin a specific certificate.
- `--export-method app-store|ad-hoc|development` (default `app-store`; only meaningful with `--release`). `app-store` produces an `.ipa` for both App Store submission and TestFlight — the same upload goes to App Store Connect and you choose the distribution path there. `ad-hoc` produces an `.ipa` for direct installation on up to 100 registered devices (no App Store Connect required). `development` produces a Release-configuration build for development team devices.

`build` always performs steps 1–6; step 7 only runs when a target flag is passed.

1. Verify `pyproject.toml` and `pylock.ios.toml` are present and in sync (drift check on `[tool.kivyforge].pyproject_sha256`).
2. Download (or cache hit) `Python.xcframework` from `[tool.kivyforge.python_xcframework]`, extract into `<app>-ios/Python.xcframework/`.
3. Download (or cache hit) every `[[tool.kivyforge.xcframeworks]]` artifact into `<app>-ios/Frameworks/`.
4. Install the pinned wheels for every `[[packages]]` entry with iOS cross-install flags (see step details below) into the per-target slice directory — `pip-deps-device/` or `pip-deps-simulator/` — never a shared `pip-deps/`, so device and simulator builds never mix compiled `.so` extensions. A targeted `build` populates only the slice it is about to build; a bare `build` (no target) populates both. The Xcode "Build Python" run script later `rsync`s the slice matching the active destination into the app bundle, and fails the build with an actionable error if that slice was never collected (see [Xcode project generation](xcode-project-generation.md)). The lock already holds the full transitive set with resolved URLs/hashes, so `--no-deps` is used and pip does not re-resolve. This does **not** go through pip's experimental `-r pylock.toml` reader (which, as of pip 26.1, ignores these platform-selection flags); `kivyforge build` installs the pinned wheels itself.
5. Walk every installed wheel in `pip-deps/` for a `.frameworks/` subdirectory; copy each `<name>.xcframework` found into `<app>-ios/Frameworks/`. This is how wheel-embedded xcframeworks arrive — for the canonical Kivy app, ANGLE and the SDL3 family ride inside the kivy wheel and land here. See [Xcode project generation §"Populating Frameworks/"](xcode-project-generation.md#populating-frameworks).
6. (Re)generate `<app>-ios/<app>.xcodeproj` via `pbxproj` per [Xcode project generation](xcode-project-generation.md).
7. *(Only when `--simulator`, `--device`, or `--release` is passed)* Invoke `xcodebuild` for the selected configuration.
   - **Signing pre-flight (fail fast).** When the selected target requires signing — `--device` or `--release` (`--simulator` does not) — `build` first resolves the effective `team_id` (precedence: `--team-id` flag → `KIVYFORGE_TEAM_ID` env var → `[tool.kivy.ios.signing].team_id`). If it is empty, `build` exits non-zero **before** invoking `xcodebuild`, rather than letting the archive fail deep inside Xcode with a cryptic signing error. The message is actionable:

     ```
     Error: code signing required for --device/--release, but no team_id is set.
       Set it one of these ways:
         • [tool.kivy.ios.signing].team_id = "ABCDE12345" in pyproject.toml, then re-lock
         • kivyforge build --release --team-id ABCDE12345
         • export KIVYFORGE_TEAM_ID=ABCDE12345
     ```

     `--simulator` and the default no-flag `build` (which stops after step 6) skip this check — neither signs.
   - **`-allowProvisioningUpdates`.** When `[tool.kivy.ios.signing].auto_signing = true` (the default), every signing `xcodebuild` invocation (`--device` build, `--release` archive, and `-exportArchive`) gets `-allowProvisioningUpdates`. Xcode's GUI registers the App ID and fetches-or-creates a matching provisioning profile invisibly; bare `xcodebuild` refuses to do either from the command line without this flag — omitting it surfaces as `Automatic signing is disabled and unable to generate a profile`. It is *not* passed when `auto_signing = false`, since manual signing (a pinned `identity` + `provisioning_profile`) shouldn't be mutating your account's provisioning state.
   - `--simulator` / `--device`: `xcodebuild build` with the appropriate SDK and Debug configuration. The compiled `.app` lands in Xcode's `DerivedData`.
   - `--release`: two-step pipeline matching Flutter's `flutter build ipa`:
     1. `xcodebuild archive -scheme <app> -configuration Release -archivePath <app>-ios/build/<app>.xcarchive` — produces a `.xcarchive` (kept for dSYM access). Because `DEBUG_INFORMATION_FORMAT = dwarf-with-dsym` is toolchain-managed for Release (see [Xcode project generation §"Toolchain-managed build settings"](xcode-project-generation.md#toolchain-managed-build-settings)), the archive always contains a `dSYMs/` folder. **For third-party crash-reporting services (Sentry, Crashlytics, etc.), point your symbol-upload tool at `<app>-ios/build/<app>.xcarchive/dSYMs/`** — this is independent of `[tool.kivy.ios.signing].upload_symbols`, which only governs upload to Apple's App Store Connect.
     2. `xcodebuild -exportArchive -archivePath <app>-ios/build/<app>.xcarchive -exportPath <app>-ios/build/ -exportOptionsPlist <generated>` — auto-generates `ExportOptions.plist` from `[tool.kivy.ios.signing]` and `--export-method`, then exports the `.ipa` to `<app>-ios/build/<app>.ipa`. The generated plist maps schema fields to export keys as follows: `--export-method` → `method` (`app-store` / `ad-hoc` / `development`); `[tool.kivy.ios.signing].team_id` → `teamID`; `[tool.kivy.ios.signing].upload_symbols` → `uploadSymbols` (`true` includes dSYMs for symbolicated crash reports; `false` sets `uploadSymbols = false` for a smaller export). The `.xcarchive` is retained regardless, so dSYMs remain available for manual symbol upload even when `upload_symbols = false`.
   - Without a target flag the project is left ready for Xcode IDE.

#### Step 4 — pip platform tag

The `--platform` tag passed to pip is derived from the build target and `--arch`:

| Target flag | `--arch` | Platform tag |
|-------------|----------|--------------|
| `--device` | *(always arm64)* | `ios_<target>_arm64_iphoneos` |
| `--simulator` | `arm64` (default on Apple Silicon) | `ios_<target>_arm64_iphonesimulator` |
| `--simulator` | `x86_64` (Intel host or explicit override) | `ios_<target>_x86_64_iphonesimulator` |
| *(none)* | n/a | Both iphoneos and iphonesimulator slices installed (project ready for either) |

`<target>` uses the platform-tag form with dots replaced by underscores (e.g. `13.0` → `13_0`). End users never type a raw pip command; the flags are derived from the lockfile and the CLI args.

### `kivyforge run`

Flags:

- `--simulator` / `--device` (mutually exclusive mode selectors; default `--simulator`; `--release` is not valid for `run`)
- `--destination NAME_OR_UDID` (which specific simulator or device to target, by name or UDID; default: most recently used simulator when `--simulator`, first connected device when `--device`)
- `--list-devices` (print available simulators and devices, exit)
- `--no-build` (skip the implicit build step; just install + launch the already-compiled app)

> **Note:** `--device` and `--destination` serve different roles and must not be conflated. `--device` is a boolean mode selector (iphoneos SDK); `--destination` is a string option naming the exact target. This mirrors xcodebuild's own `-destination` vocabulary.

**Implicit build step.** By default `kivyforge run` performs a full `kivyforge build` (steps 1–6) for the selected target before installing and launching. This makes `kivyforge run` a single command from source to running app, without requiring the user to remember to build first. Specifically:

- `kivyforge run` → equivalent to `kivyforge build --simulator && install && launch`
- `kivyforge run --device` → equivalent to `kivyforge build --device && install && launch`
- `kivyforge run --no-build` → skip steps 1–6; go straight to install + launch (requires a previously compiled `.app`)

If the lock is out of date (drift check fails in step 1), `run` propagates the same error as `kivyforge build` and exits non-zero before doing anything else.

**Install and launch sequence:**

1. For `--simulator`: boot the target simulator if not already running (`xcrun simctl boot`), install the `.app` (`xcrun simctl install`), launch (`xcrun simctl launch --console-pty`).
2. For `--device`: install via `xcrun devicectl device install app` (Xcode 15+), then launch via `xcrun devicectl device process launch`. Falls back to `ios-deploy` if `devicectl` is unavailable.

Implementation uses `xcrun simctl` for simulators and `xcrun devicectl` (or `ios-deploy` if needed) for devices.

### `kivyforge open`

Opens the generated Xcode project in Xcode IDE:

```bash
kivyforge open        # equivalent to: open <app>-ios/<app>.xcodeproj
```

No flags. Exits with a clear error if `kivyforge build` hasn't been run yet (i.e. the `.xcodeproj` doesn't exist). The typical Xcode-IDE-centred workflow is:

```bash
kivyforge init && kivyforge lock && kivyforge build
kivyforge open   # → select simulator/device in Xcode → ⌘R
```

### `kivyforge upgrade`

Flags:

- `--python` (only refresh Python.xcframework; skip xcframework artifacts)
- `--xcframeworks` (only refresh xcframework artifacts; skip Python)
- `--name NAME` (only refresh a specific artifact)

`upgrade` re-fetches the pinned `Python.xcframework` and/or `[[tool.kivyforge.xcframeworks]]` artifacts per the **existing lockfile** — it does not reinstall pip-deps, does not regenerate the Xcode project, and does not invoke xcodebuild. Its purpose is narrowly "refresh a downloaded artifact without touching the rest of the project": use it when an artifact was deleted from the local cache, when you want to verify the cached copy against the pinned SHA-256 again, or when a CI job needs a clean artifact cache warmed before the build step.

To pick up *newer* versions, the user edits `pyproject.toml` and re-runs `kivyforge lock` — then `kivyforge build` (or `kivyforge run`) materializes the new lock. Separation of concerns: `lock` changes versions; `upgrade` re-downloads the current pins; `build` installs everything and regenerates the project.

If none of `--python`, `--xcframeworks`, or `--name` is given, all pinned artifact downloads (Python.xcframework + every `[[tool.kivyforge.xcframeworks]]` entry) are refreshed. Pip-deps wheels are never touched by `upgrade`; re-running `kivyforge build` handles those.

### `kivyforge clean`

Flags:

- `--cache` (also flush `~/Library/Caches/kivyforge/artifacts/` — the macOS-standard cache location)
- `--project-only` (only the generated `<app>-ios/` folder; default)

### `kivyforge status`

No flags. Read-only; exits 0 always (even when the project is out of sync — it reports state, it does not enforce it).

Prints a concise project snapshot to stdout:

```
App:        touchtracer  (org.kivy.touchtracer)
Python:     3.15.0
Lock:       in sync
Build:
  simulator (arm64)   last built 3 minutes ago
  device              not built
```

| Field | Source |
|-------|--------|
| App name | `[project].name` / `[tool.kivy].display_name` |
| Bundle ID | `[tool.kivy.ios].bundle_id` |
| Python version | `[tool.kivy.ios.python].version` (from pyproject) |
| Lock | compares `pyproject_sha256` in lock against current `pyproject.toml` hash — reports `in sync`, `out of date` (run `kivyforge lock`), or `missing` |
| Build / simulator | presence and mtime of the simulator `.app` in `DerivedData` or `<app>-ios/build/` |
| Build / device | same for the device build |

`status` is intentionally read-only and has no side effects. It answers "what state is my project in?" without the system-health scope of `kivyforge doctor`. Exits non-zero only if no `pyproject.toml` is found in CWD.

### `kivyforge doctor`

Substantive checks (not a placeholder), inspired by `flutter doctor`:

`doctor` operates in two modes depending on context:

- **Environment mode** (no `pyproject.toml` in CWD): runs environment-only checks and marks all project-specific checks as SKIP with the note "no pyproject.toml found in current directory." Always gives useful output regardless of where it is invoked.
- **Project mode** (`pyproject.toml` present): runs all checks.

| Check | Scope | What it validates |
|-------|-------|-------------------|
| Xcode version | environment | At least the toolchain's documented minimum Xcode version |
| Command-line tools | environment | `xcode-select -p` resolves; `xcrun clang` present |
| Simulator runtimes | environment | At least one iOS simulator runtime installed; in project mode, matched against `[tool.kivy.ios].deployment_target` |
| kivyforge version | environment | Self-version + warn if a newer one is on PyPI (best-effort, suppressed by `--offline`) |
| App source directory | project | `[tool.kivy].app_dir` resolves to an existing directory. Config validation only checks the *string*; FAIL here if the directory is missing, since the build would otherwise ship an app with no Python source. |
| Signing identity | project | If `[tool.kivy.ios.signing].auto_signing = false`, the named identity is present in keychain |
| Provisioning profile | project | If `[tool.kivy.ios.signing].provisioning_profile` is set, it exists |
| App icon | project | If `[tool.kivy.ios.icons].source` is set, FAIL unless it is a valid 1024×1024 PNG (the hint names the exact problem — missing, not PNG, or wrong dimensions). SKIP if no icon is configured. |
| find_links directories | project | If `[tool.kivy.ios].find_links` is set, validate each entry: FAIL if it is not an existing directory; WARN if it exists but contains no `.whl` files. SKIP if not configured. |
| Required hosts reachable | project | TCP connect to every host the lockfile will actually fetch from — the union of hosts in all `[[packages.wheels]].url` entries (PyPI, supplemental indexes, or direct sources), all `[[tool.kivyforge.xcframeworks]].url` entries, and `[tool.kivyforge.python_xcframework].url` (normally `www.python.org`). The host list is derived from `pylock.ios.toml`; no hosts are hardcoded. `path`-based (vendored) entries are skipped — there is nothing to reach. |
| App-local native binaries | project | Scan `app_dir` for `.so`/`.dylib` files; FAIL on any non-iOS-architecture binary (a macOS-compiled extension dropped in `app/` won't load on device — native code belongs in an iOS wheel, see [iOS artifact distribution §"App-specific native extensions"](artifact-distribution-ios.md)). WARN on any binary whose platform can't be read (truncated, corrupt, or not a Mach-O) — it can't be confirmed iOS-safe. |
| App-level privacy manifest | project | WARN if `<app>-ios/PrivacyInfo.xcprivacy` is absent (project not yet built, or file was deleted). INFO note that the toolchain generates a minimal stub on next `kivyforge build`; if the app uses required-reason APIs the user must supply a `[tool.kivy.ios.privacy_manifest].source`. |
| xcframework privacy manifests | project | For each `.xcframework` in `<app>-ios/Frameworks/`, WARN if no `PrivacyInfo.xcprivacy` is found in any of its slices. The warning names the framework and notes that its author must add one; kivyforge cannot add it on their behalf. |

`doctor` reports each check as PASS / WARN / FAIL with a remediation hint. Exit code is non-zero only on FAIL.

## Mobile window/display geometry: `kivy.mobile`

Kivy apps need runtime geometry the platform owns — display DPI, scale, safe-area insets, and live software-keyboard height. Earlier previews of the toolchain vendored this as a pure-Python `ios.py` (plus a `mobile.py` preview) into every generated project at `<app>-ios/platform/`. That was always a placeholder: the implementation belongs in Kivy, not the build tool.

As of [kivy/kivy#9331](https://github.com/kivy/kivy/pull/9331) it lives in **Kivy core** as `kivy.mobile`, shipped inside the Kivy iOS wheel. `kivy.mobile._platform.ios` provides the same geometry via the ObjC runtime (`ctypes`, no extra dependency); Kivy's own `metrics.py` and `core/window` import from `kivy.mobile` instead of a bare `import ios`. **kivyforge no longer vendors any platform shim** — `kivyforge build` writes no `platform/` directory.

### Public API (provided by Kivy)

| Function | Return type | Units |
|----------|-------------|-------|
| `get_scale()` | `float` | pixels per point (e.g. `3.0` on iPhone 15 Pro) |
| `get_dpi()` | `float` | physical dots per inch (`nativeScale × base ppi`) |
| `get_safe_area()` | `dict[str, float]` | UIKit points — `{"top", "left", "bottom", "right"}` |
| `get_keyboard_height()` | `float` | UIKit points (0 when hidden) |
| `subscribe_keyboard_height(cb)` | — | register a height-change callback |

### Safe-area insets

`kivy.mobile` is **mobile-only** — it raises `ImportError` on desktop — so app code guards on platform:

```python
from kivy.utils import platform
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.core.window import Window

def safe_area_insets():
    if platform != "ios":
        return [0, 0, 0, 0]
    from kivy.mobile import get_safe_area, get_scale
    insets = get_safe_area()   # UIKit points
    scale  = get_scale()       # points → pixels
    return [insets["left"] * scale, insets["top"] * scale,
            insets["right"] * scale, insets["bottom"] * scale]

# In a root widget — refresh on startup and orientation change:
Clock.schedule_once(self._refresh_safe_area, 0)
Window.bind(on_resize=lambda *_: Clock.schedule_once(self._refresh_safe_area, 0))

def _refresh_safe_area(self, *_):
    base = dp(20)
    left, top, right, bottom = safe_area_insets()
    self.padding = [base + left, base + top, base + right, base + bottom]
```

Kivy 3.0 also exposes `Window.safe_area` (a `DictProperty` refreshed on startup and `on_rotate`), so most apps can bind to that directly rather than calling `kivy.mobile` themselves.

See [recipe triage §"Deleted recipes — `ios` recipe"](recipe-triage.md).
