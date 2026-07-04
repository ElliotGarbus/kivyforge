# macOS — Design Spec

The macOS backend produces a self-contained **`.app` bundle**: a double-clickable
application containing a bundled Python runtime, the app's resolved wheels, and
the user's source. It is the first desktop target and the first *new* platform
after iOS, and it exercises the cross-platform architecture (shared
`[project]`/`[tool.kivy]`, a `[tool.kivy.macos]` overlay, a `pylock.macos.toml`,
and the `Platform` backend interface).

> **Status: implemented (Phase 3).** The macOS backend ships: `[tool.kivy.macos]`
> parsing, `pylock.macos.toml` resolution (PBS runtime + macOS-tagged wheels),
> the `.app` generator, `build`/`run`/`package -f app` with `--arch`, ad-hoc
> signing, and macOS `doctor` checks. A couple of implementation details differ
> from the original design and are noted inline below (the bundled runtime lives
> under `Contents/Resources/` rather than `Contents/Frameworks/`, and the
> launcher is a tiny compiled Mach-O stub rather than a shell script).

## Scope

In scope for the first macOS phase:

- `[tool.kivy.macos]` overlay parsing + a `MacosConfig` dataclass.
- `pylock.macos.toml` resolution (macOS Python runtime + macOS-tagged wheels).
- A `.app` bundle generator (Info.plist, bundled Python + wheels + app source, a launcher).
- `build` / `run` (launch the `.app`) and `package -f app`.
- **Ad-hoc** code signing (the mandatory Apple-Silicon floor).
- macOS `doctor` checks.

Out of scope for the first macOS phase:

- **`.dmg` creation** — wrap the `.app` with an external tool (`create-dmg`, `dmgbuild`, DropDMG). See [common packaging scope](../../common/06-packaging-scope.md).
- **Full Developer ID signing + notarization + stapling** — a later workstream, outlined at the end of this document.

## `[tool.kivy.macos]` overlay

An additive overlay on top of the shared `[project]` + `[tool.kivy]` tables (see
[common pyproject spec](../../common/01-pyproject-kivy-spec.md)). Only fields
that differ from the cross-platform defaults or are macOS-specific appear here.

```toml
[tool.kivy.macos]
schema_version = 1
bundle_id = "org.example.myapp"        # CFBundleIdentifier
build = 1                               # CFBundleVersion
minimum_system_version = "12.0"         # LSMinimumSystemVersion
archs = ["arm64", "x86_64"]             # lock/build architectures; two = universal2

[tool.kivy.macos.python]
version = "3.15.0"                       # bundled Python runtime version

[tool.kivy.macos.icons]
source = "assets/icon-macos.png"        # 1024×1024 PNG → generated .icns

# extra_index_urls / find_links / exclude behave as on iOS (macOS-tagged wheels).
```

Proposed field set (finalized in implementation):

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `schema_version` | integer | yes | — | macOS overlay schema version; independent of other platforms'. |
| `bundle_id` | string | yes | — | `CFBundleIdentifier` (reverse-DNS). |
| `build` | integer | no | `1` | `CFBundleVersion`. |
| `minimum_system_version` | string | no | *(runtime floor)* | `LSMinimumSystemVersion`; must be ≥ the bundled runtime's floor. |
| `archs` | list of string | no | `["arm64", "x86_64"]` | Target architecture set the lock must cover; allowed values `arm64`, `x86_64`. Two entries ⇒ a universal2 build; one entry ⇒ a thin build. Drives required macOS wheel tags and the per-arch runtime pins. See ["Architectures"](#architectures-archs) below. |
| `extra_index_urls` | list of string | no | `[]` | Supplemental wheel indexes (macOS tags), same semantics as iOS. |
| `find_links` | list of string | no | `[]` | Repo-relative vendored-wheel directories for `lock`. |
| `exclude` | list of string | no | `[]` | Prune unused transitive deps from the resolved graph. |

Icons: `[tool.kivy.macos.icons].source` (1024×1024 PNG) is converted to a macOS
`.icns` asset. Splash screens are not a macOS concept and have no subtable.

Shared `[tool.kivy]` keys consumed: `display_name` (→ `CFBundleName` /
`CFBundleDisplayName`), `app_dir`, `entry_point`. `orientation` is not meaningful
on desktop and is ignored by the macOS backend.

## Python runtime acquisition

macOS needs a **relocatable, bundleable** CPython, and here it differs from iOS:
iOS pins python.org's official, ready-to-embed `Python.xcframework`, but python.org
ships **no relocatable macOS artifact** today. Its only macOS build is the *"macOS
64-bit universal2 installer"* `.pkg`, which installs a `Python.framework` hard-coded
to `/Library/Frameworks` (absolute link references); embedding it in a `.app` would
require rewriting dylib `install_name`/`@rpath`, re-signing, and trimming.

**Decision: use [`python-build-standalone`](https://github.com/astral-sh/python-build-standalone)
(PBS) now, behind a swappable "runtime provider" abstraction that lets us adopt the
official python.org relocatable framework the moment it ships** (see the watch item
below). PBS is purpose-built to be relocatable/embeddable, is actively maintained
(Astral-stewarded, tracks CPython releases closely), and its patches are being
upstreamed into CPython — so it is both the pragmatic choice today and directly on
the path to the official artifact.

### The runtime-provider abstraction

The whole point is that the *source* of the runtime is an implementation detail
hidden behind one seam, so the future switch is a re-lock, not a rewrite:

- **`RuntimeProvider` interface** (macOS backend). A provider resolves a CPython
  version to a concrete, pinned artifact and normalizes it to a **canonical
  relocatable layout** the `.app` bundler consumes. Implementations:
  `PythonBuildStandaloneProvider` (now) and a future `PythonOrgFrameworkProvider`
  (when python.org's relocatable framework lands). The bundler, launcher, signing,
  and `doctor` code depend only on the canonical layout — never on the provider.
- **The lock records the provider, not just the version.** `[tool.kivyforge]` in
  `pylock.macos.toml` pins `provider` + `version` + per-artifact `url` + `sha256`
  (PBS ships per-arch archives, so this may be two entries — see universal2 below),
  exactly the URL+SHA-256 discipline used for the iOS `python_xcframework` pin.
  Switching providers is therefore just `kivyforge lock` regenerating the pin; the
  built `.app` is provider-agnostic and nothing downstream changes.
- **User config stays provider-neutral.** `[tool.kivy.macos.python].version` is just
  the CPython version. An optional advanced `provider` key may override the default,
  but the default is chosen by kivyforge (PBS now → python.org later). When the
  official artifact ships, flipping the default requires **no change to anyone's
  `pyproject.toml`** — only a re-lock.

### Architectures (`archs`)

macOS apps can be `arm64`-only, `x86_64`-only, or **universal2** (both). Because
this choice changes dependency resolution, it is a **lock-level** property set by
`[tool.kivy.macos].archs` (default `["arm64", "x86_64"]` → universal2), with a
build-time `--arch` override for the dev loop. The model mirrors iOS device/simulator
slices: the lock is the superset, and `build`/`run`/`package` assemble a subset.

Architecture propagates through three stages:

- **Resolution (lock).** Each arch in `archs` requires every compiled dependency to
  be available for it — either a `macosx_*_universal2` wheel or a matching
  per-arch (`macosx_*_arm64` / `macosx_*_x86_64`) wheel. A dependency missing a
  required arch (with no universal2 fallback) is a **fail-fast at lock time** with an
  actionable message (the same treatment as a missing iOS slice). `pylock.macos.toml`
  records the arch set and pins the wheels and per-arch runtimes accordingly. This is
  also why the default is explicit: an Apple-Silicon-only project can set
  `archs = ["arm64"]` to avoid requiring Intel wheels its deps may not publish.
- **Runtime provider.** PBS publishes **per-architecture** macOS builds
  (`aarch64-apple-darwin`, `x86_64-apple-darwin`), not universal2. For a two-arch
  build the provider fetches both archives and `lipo`-merges the executable,
  `libpython`, and every bundled `.dylib`/`.so` into a universal2 tree during
  normalization; a thin build fetches one. (The eventual python.org framework may be
  universal2 or per-arch — still unsettled upstream — and the bundler won't care
  either way, since it consumes the canonical layout.)
- **Assembly (`--arch`).** `build` / `run` / `package` produce a universal2 `.app`
  from a two-arch lock by default. `--arch {arm64,x86_64,universal2}` selects a
  **subset of the locked `archs`** for a faster/smaller build during iteration
  (analogous to `--device` / `--simulator`); it needs no re-lock. Requesting an arch
  not present in the lock is an actionable error (adjust `archs` and re-lock).

### Watch item: official python.org relocatable macOS build

There is active upstream work to make an official relocatable macOS runtime, which
is the intended end-state for this provider:

- **[cpython#86680](https://github.com/python/cpython/issues/86680)** ("Relocatable
  framework for macOS") + in-flight PR
  **[cpython#144305](https://github.com/python/cpython/pull/144305)** (make framework
  builds relocatable via `@rpath`). BeeWare's Russell Keith-Magee frames this as a
  CPython "release artefact" effort: an unversioned, relocatable `Python.framework`
  (a "macOS Embedded" download, analogous to the Windows embeddable build), shipped
  **separately** from the non-relocatable `.pkg` installer. Main holdup: macOS
  release-process automation.
- **[python/prebuilt-cpython](https://github.com/python/prebuilt-cpython)** — the
  PSF's effort to distribute official prebuilt, **relocatable** CPython from
  python.org (signed by official keys), unblocked by upstreaming PBS patches; a PEP
  is imminent. Note early discussion leans toward **per-arch** ("one distribution
  per arch with a conservative baseline"), which the provider must accommodate.

When either lands, we add `PythonOrgFrameworkProvider`, make it the default, and
existing projects pick it up on their next `kivyforge lock`. The current PBS choice
is deliberately a **bridge on the same lineage** (PBS → upstreamed into CPython →
official python.org), not a divergent path.

## `pylock.macos.toml`

Same pattern as every platform (see [common lockfile concept](../../common/03-lockfile-concept.md)):
PEP 751 `[[packages]]` for wheels + a single `[tool.kivyforge]` extension table
holding the runtime pin and provenance. The platform is identified by the
filename. macOS wheels use standard macOS platform tags
(`macosx_<ver>_arm64`, `macosx_<ver>_x86_64`, or `macosx_<ver>_universal2`);
`kivyforge lock` resolves wheels for every arch in `[tool.kivy.macos].archs`
(accepting a `universal2` wheel for either), records the arch set, and pins the
matching **per-arch runtime artifacts** under `[tool.kivyforge]` (see
["Architectures"](#architectures-archs)). Pure-Python deps resolve to
`py3-none-any`, and everything is pinned by URL + SHA-256. Unlike iOS there is no
per-slice framework conversion — macOS loads `.dylib`/`.so` extensions directly — so
the lock is simpler.

## `.app` bundle layout

`package -f app` (and `build`) produce a standard macOS application bundle:

```
MyApp.app/
├── Contents/
│   ├── Info.plist                 ← from [project] + [tool.kivy.macos]
│   ├── MacOS/
│   │   └── MyApp                  ← launcher (compiled Mach-O stub; sets env, execs Python)
│   └── Resources/
│       ├── MyApp.icns             ← from [tool.kivy.macos.icons].source
│       ├── app/                   ← user code (from [tool.kivy].app_dir)
│       ├── lib/                   ← installed wheels (site-packages)
│       └── python/                ← bundled CPython runtime + stdlib
```

The bundled runtime is the active provider's normalized, relocatable CPython tree
(PBS today, the official python.org framework later — the bundler consumes the
canonical layout regardless of provider).

> **Implementation note — runtime under `Resources/`, not `Frameworks/`.** A
> python-build-standalone tree is a *unix prefix* (`bin/`, `lib/python3.x/`,
> `lib/tk*`), not an Apple framework bundle. Placing it under
> `Contents/Frameworks/` triggers `codesign`'s framework auto-discovery on the
> non-framework subdirectories (it rejects `lib/tk9.0` with "bundle format
> unrecognized"). Under `Contents/Resources/python/` the tree is sealed as data,
> and each nested Mach-O (the interpreter, `libpython`, `.dylib`s, wheel `.so`s)
> is still signed individually — so the bundle both signs and runs correctly.

> **Implementation note — the launcher is a compiled Mach-O, not a shell
> script.** The bundle's `CFBundleExecutable` must be a real Mach-O binary. When
> it is a text script, Finder/LaunchServices treats it as a *document* and opens
> a Terminal/console window alongside the app (and a script can't be
> ad-hoc-signed as the bundle's main image). This is why every real bundler
> (py2app, Briefcase, PyInstaller) ships a compiled stub. kivyforge compiles a
> ~40-line C launcher with `clang` — always present, since `codesign` already
> requires the Xcode command-line tools — for the assembled `archs` (universal2
> when both). It's a trivial addition to the toolchain requirement, not a new
> one.

The launcher resolves the bundle relative to itself (via `_NSGetExecutablePath`,
so the `.app` stays relocatable), points `PYTHONHOME` at the bundled runtime and
`PYTHONPATH` at `Resources/app` + `Resources/lib`, sets `PYTHONNOUSERSITE`, then
`execv`s `Resources/python/bin/python3 Resources/app/<entry_point>.py` — the
desktop analog of the iOS `main.m` bootstrap. It is itself ad-hoc-signed along
with the Mach-O binaries in the runtime + wheels.

## `build` / `run` / `package`

- **`build`** — resolve (if needed), acquire the runtime and wheels, and assemble
  the `.app` staging tree.
- **`run`** — build (unless `--no-build`), then **launch the `.app`** on the host
  (the desktop analog of installing to a simulator). The fast dev loop.
- **`package -f app`** — produce the finished, **signed** `.app` (ad-hoc for now).
  `-f app` is the only format this phase supports; `.dmg`/installer is external.

All three accept **`--arch {arm64,x86_64,universal2}`** to assemble a subset of the
locked `archs` (default: the full locked set, i.e. universal2). A thin `--arch`
speeds up the `run` iteration loop; requesting an arch not in the lock is an
actionable error (adjust `[tool.kivy.macos].archs` and re-lock).

## Code signing

### Ad-hoc (this phase)

```
codesign --sign - MyApp.app
```

Ad-hoc signing is the **mandatory floor**: arm64 (Apple-Silicon) executables must
be at least ad-hoc signed or the kernel refuses to run them. It provides
*integrity*, not *trust*:

- The `.app` runs locally, and runs when shared **without** a quarantine attribute.
- A **downloaded** (quarantined) copy is Gatekeeper-blocked and needs
  right-click → Open (or `xattr -dr com.apple.quarantine MyApp.app`).
- No Apple Developer account is required.

kivyforge signs the bundled binaries as part of producing a correct artifact
(signing operates on the bundle's Mach-O files); this stays inside the tool.

### Developer ID sign + notarize + staple (later workstream)

The typical distribution path for most macOS apps is **sign + notarize + staple**
(signing alone is insufficient since macOS 10.15). This is deferred because it is
a real workstream for a Python bundle, not a one-liner:

- Config under `[tool.kivy.macos.signing]` (`team_id`, `identity` = *Developer ID
  Application*, entitlements), reusing iOS signing-config patterns where sensible;
  secure notary credentials (app-specific password or App Store Connect API key),
  CI-friendly.
- **Nested, inside-out signing**: sign every bundled Mach-O (`.so`/`.dylib`/
  frameworks from Python + wheels like Kivy/SDL) first, then the `.app` last. This
  ordered deep-signing of dozens of binaries is the main complexity.
- **Hardened Runtime** (`--options runtime`) + secure `--timestamp`; entitlements
  as needed (e.g. `com.apple.security.cs.disable-library-validation` to load
  third-party unsigned `.so`s).
- **Notarize + staple the app**: zip the signed `.app` → `xcrun notarytool submit`
  (submit → poll → report) → `xcrun stapler staple MyApp.app`. Result: Gatekeeper
  trusts the app offline, and any external `.dmg` just wraps an already-trusted app.
- Requires Apple Developer Program membership and a Developer ID Application
  certificate.

**`.dmg`-level signing/notarization stays external** (a post-packaging step on a
container kivyforge does not build). The docs will include a copy-paste snippet
(`codesign` → `notarytool submit` → `stapler staple` on the `.dmg`) for users who
distribute a `.dmg` and want it notarized too. An optional small generic
"notarize + staple this file" helper (usable on a `.zip`/`.dmg`/`.pkg`, since the
mechanics are container-agnostic) may be added — but kivyforge still never builds
`.dmg`s.

## `doctor` checks (macOS)

| Check | Scope | What it validates |
|-------|-------|-------------------|
| Host is macOS | environment | The macOS backend requires a macOS host (host-capability check). |
| Codesign available | environment | `codesign` present (ships with the Xcode command-line tools). |
| Toolchain version | environment | Self-version; warn if newer on PyPI (best-effort). |
| App source directory | project | `[tool.kivy].app_dir` resolves to an existing directory. |
| Runtime floor vs. `minimum_system_version` | project | `[tool.kivy.macos].minimum_system_version` ≥ the bundled runtime's floor. |
| Architecture coverage | project | Every arch in `[tool.kivy.macos].archs` has a resolvable wheel (per-arch or universal2) for each compiled dependency, and a per-arch runtime is available; FAIL names the offending package/arch. |
| App icon | project | If `[tool.kivy.macos.icons].source` is set, FAIL unless a valid 1024×1024 PNG. SKIP if unset. |
| find_links directories | project | If set, each entry is an existing directory containing `.whl` files. |
| Required hosts reachable | project | TCP-connect to every host the lockfile fetches from (derived from `pylock.macos.toml`). |
| Signing identity (later) | project | When Developer ID signing is configured, the identity is present in the keychain. |

`doctor` reports each check as PASS / WARN / FAIL with a remediation hint; exit
code is non-zero only on FAIL.

## Host requirements

- A macOS host (Apple Silicon or Intel). The Xcode command-line tools provide
  `codesign`; the full Xcode IDE is **not** required for a macOS `.app` (unlike
  iOS).
- No Apple Developer account is needed for ad-hoc signing; a Developer ID
  certificate is needed only for the later notarization workstream.
