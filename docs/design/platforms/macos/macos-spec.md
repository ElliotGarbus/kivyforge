# macOS — Design Spec

The macOS backend produces a self-contained **`.app` bundle**: a double-clickable
application containing a bundled Python runtime, the app's resolved wheels, and
the user's source. It is the first desktop target and the first *new* platform
after iOS, and it exercises the cross-platform architecture (shared
`[project]`/`[tool.kivy]`, a `[tool.kivy.macos]` overlay, a `pylock.macos.toml`,
and the `Platform` backend interface).

> **Status: implemented and verified.** The macOS backend ships:
> `[tool.kivy.macos]` parsing, `pylock.macos.toml` resolution (PBS runtime +
> macOS-tagged wheels), the `.app` generator, `build`/`run`/`package -f app`
> with `--arch`, ad-hoc signing, macOS `doctor` checks, and the full
> **Developer ID sign + notarize + staple** distribution path. The latter has
> been exercised end-to-end on real hardware with a real, paid-account
> Developer ID Application certificate: `package -p macos` deep-signed all
> bundled Mach-O binaries with Hardened Runtime, submitted to the notary
> service, and got the ticket back accepted and stapled. A couple of
> implementation details differ from the original design and are noted inline
> below (the bundled runtime lives under `Contents/Resources/` rather than
> `Contents/Frameworks/`, and the launcher is a tiny compiled Mach-O stub
> rather than a shell script).

## Scope

In scope for the macOS backend:

- `[tool.kivy.macos]` overlay parsing + a `MacosConfig` dataclass.
- `pylock.macos.toml` resolution (macOS Python runtime + macOS-tagged wheels).
- A `.app` bundle generator (Info.plist, bundled Python + wheels + app source, a launcher).
- `build` / `run` (launch the `.app`) and `package -f app`.
- A declared **native-binaries channel** (`[tool.kivy.macos.native.binaries]`)
  for non-wheel dylibs / helper executables
  (see ["Native binaries that are not wheels"](#native-binaries-that-are-not-wheels-toolkivymacosnativebinaries)).
- **Ad-hoc** code signing (the mandatory Apple-Silicon floor).
- **Full Developer ID signing + notarization + stapling** — see
  ["Developer ID sign + notarize + staple"](#developer-id-sign--notarize--staple) below.
- macOS `doctor` checks.

Out of scope for kivyforge (permanently, not deferred):

- **`.dmg` creation** — wrap the `.app` with an external tool (`create-dmg`, `dmgbuild`, DropDMG). See [common packaging scope](../../common/06-packaging-scope.md).

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

Signing: `[tool.kivy.macos.signing]` (`identity`, `team_id`, `notary_profile`)
and the free-form `[tool.kivy.macos.entitlements]` table configure the
Developer ID distribution path — see
["Developer ID sign + notarize + staple"](#developer-id-sign--notarize--staple).
Both are optional; without them `package` ships the ad-hoc floor.

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
(PBS) now**, behind the shared
[`RuntimeProvider` abstraction](../../common/07-runtime-provider-pattern.md)
that lets us adopt an official python.org relocatable framework the moment it
ships (see the watch item there). PBS is purpose-built to be
relocatable/embeddable, is actively maintained (Astral-stewarded, tracks
CPython releases closely), and its patches are being upstreamed into CPython —
so it is both the pragmatic choice today and directly on the path to the
official artifact.

The macOS backend's concrete `RuntimeProvider` implementation is
`PythonBuildStandaloneProvider` (a future `PythonOrgFrameworkProvider` lands
when the official framework ships). `pylock.macos.toml` pins `provider` +
`version` + per-artifact `url` + `sha256` — PBS ships **per-architecture**
macOS archives, so a universal2 lock has two artifact entries (see below).

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

See the [common watch item](../../common/07-runtime-provider-pattern.md#watch-item-official-prebuilt-cpython-pythonprebuilt-cpython)
for the cross-platform `python/prebuilt-cpython` effort. macOS-specific
upstream tracking:

- **[cpython#86680](https://github.com/python/cpython/issues/86680)** ("Relocatable
  framework for macOS") + in-flight PR
  **[cpython#144305](https://github.com/python/cpython/pull/144305)** (make framework
  builds relocatable via `@rpath`). BeeWare's Russell Keith-Magee frames this as a
  CPython "release artefact" effort: an unversioned, relocatable `Python.framework`
  (a "macOS Embedded" download, analogous to the Windows embeddable build), shipped
  **separately** from the non-relocatable `.pkg` installer. Main holdup: macOS
  release-process automation.

Whichever of these lands first, we add `PythonOrgFrameworkProvider`, make it
the default, and existing projects pick it up on their next `kivyforge lock`.
The current PBS choice is deliberately a **bridge on the same lineage** (PBS →
upstreamed into CPython → official python.org), not a divergent path.

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
│       ├── bin/                   ← declared native binaries (native.binaries);
│       │                            absent when the table is empty
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

### Native binaries that are not wheels (`[tool.kivy.macos.native.binaries]`)

> **Implementation status: implemented.** A scoped addition to the shipped
> backend, specified alongside the Windows backend (which defines the same
> channel; see the
> [Windows spec](../windows/windows-spec.md#native-binaries-that-are-not-wheels)).
> The lock field lives in the *shared* wheel+runtime engine
> (`[[tool.kivyforge.native_binaries]]`), so Linux/Windows adopt it with no
> lock-format rework. See [`examples/desktop/hello-native`](../../../../examples/desktop/hello-native)
> for a runnable end-to-end example (a helper executable used by name + a dylib
> loaded by path).
>
> **Delta from design:** single-file sources are staged under their *source*
> basename (copied "as-is"), so a `.dylib` keeps its extension for by-path
> `ctypes` loads — the config key names the lock entry, not the on-disk file.
> Staged single files also get their exec bit set (harmless for a dylib, and it
> makes a downloaded helper runnable even when the source lost its mode).

Some apps need native binaries that no wheel delivers: vendor SDK `.dylib`s
or helper executables (a bundled `ffmpeg`). The
**`[tool.kivy.macos.native.binaries]`** table is the declared channel — the
desktop sibling of iOS's `[tool.kivy.ios.native.xcframeworks]`, same
name → `{ version, source }` shape, same explicit-source rules (a direct
download URL or a repo-relative path; absolute/escaping paths rejected):

```toml
[tool.kivy.macos.native.binaries]
sdk    = { version = "2.1.0", source = "https://vendor.example/sdk-2.1.0-macos.zip" }
ffmpeg = { version = "7.1",   source = "binaries/macos/ffmpeg" }
```

Semantics, per pipeline stage:

- **`lock`** — resolves each artifact's SHA-256 and pins
  `name`/`version`/`source`/`sha256` in a
  `[[tool.kivyforge.native_binaries]]` array in `pylock.macos.toml` — the
  same integrity discipline as wheels and the runtime.
- **`build`** — fetches through the shared download/cache/verify machinery
  and stages into **`Contents/Resources/bin/`** (single files copied under
  their source basename with the exec bit set; `.zip` sources extracted
  preserving structure, each file made executable). `bin/` is one flat
  namespace, so staging rejects (a build error) any two entries that would
  write the same path — two single files sharing a basename, two zips sharing
  a member, or a single file colliding with a zip member — rather than letting
  the later one silently overwrite the earlier. `doctor` catches the
  statically-detectable subset (single-file basename clashes) before a build.
- **launcher** — prepends `Resources/bin` to the child `PATH`, so helper
  executables run by name (`subprocess.run(["ffmpeg", ...])`).
- **`.dylib`s still load by absolute path.** macOS has no safe by-name
  registration analog to Windows' `os.add_dll_directory`:
  `DYLD_LIBRARY_PATH` is ignored by Hardened-Runtime processes (short of the
  `allow-dyld-environment-variables` entitlement, which invites notarization
  trouble). The stable cross-platform recipe is
  `Path(sys.prefix).parent / "bin"` — `sys.prefix` is the bundled runtime
  (`Resources/python`), so its parent is `Resources/`; the same derivation
  yields the `bin` directory on Windows and Linux too.
- **`doctor`** — each declared source exists/is reachable, no two single-file
  sources share a staged basename, and each staged Mach-O covers the assembled
  archs (a thin `arm64` vendor dylib in a universal2 app fails only at load
  time on Intel; FAIL names the file and missing arch).
- **signing** — no new work: the deep sign already walks *every* Mach-O
  under the `.app` by file magic, so `Resources/bin` is swept — ad-hoc, or
  Developer ID with Hardened Runtime + timestamp — automatically. This is a
  requirement, not a convenience: notarization rejects any unsigned Mach-O
  anywhere in the bundle.

**The boundary:** kivyforge fetches, verifies, stages, and signs declared
binaries. It does **not** resolve their dependencies or rewrite their
`install_name`/`@rpath` load commands — a dylib that hard-codes absolute
install paths is the vendor's problem to fix (the consume-prebuilt-artifacts
principle).

**The escape hatch remains:** files dropped under `app_dir` are copied
wholesale into `Resources/app/` (exec bits preserved; the launcher `chdir`s
there) and are still swept by the signer — but get no pinning, no `PATH`
entry, and no arch check. Two edges of the sweep, recorded rather than
solved: (1) nested binaries are signed *without* the app's entitlements
(those apply only to the bundle seal / main executable) — a helper that
itself needs a hardened exception (e.g. its own W+X allocation) would need
per-file entitlements, a revisit-on-demand item. (2) The Mach-O detector
matches the `0xCAFEBABE` magic, which is also the Java class-file magic —
its walks-only-runtime-and-wheels assumption predates sweeping `app_dir`
content, so a `.class` file under `app_dir` would be misidentified and fail
`codesign`. A known limitation; fix if anyone ever hits it.

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

### Developer ID sign + notarize + staple

The typical distribution path for most macOS apps is **sign + notarize + staple**
(signing alone is insufficient since macOS 10.15) — see Apple's
[Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution),
[Customizing the notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)
(the `notarytool`/`stapler` CLI path kivyforge automates), and
[Resolving common notarization issues](https://developer.apple.com/documentation/security/resolving-common-notarization-issues).
Requires Apple Developer Program membership (paid) and a *Developer ID
Application* certificate; without one, `package` keeps producing the ad-hoc
artifact.

**Config** — `[tool.kivy.macos.signing]` plus optional entitlements:

```toml
[tool.kivy.macos.signing]
identity = "Developer ID Application: Jane Doe (ABC1234XYZ)"
team_id = "ABC1234XYZ"                  # informational; notary auth uses the profile
notary_profile = "kivyforge-notary"     # keychain profile (see below)

[tool.kivy.macos.entitlements]          # optional; merged over the defaults
"com.apple.security.device.camera" = true
```

Notary credentials never live in `pyproject.toml`: `notary_profile` names a
**keychain profile** created once (locally or in a CI keychain) with:

```bash
xcrun notarytool store-credentials kivyforge-notary \
    --apple-id you@example.com --team-id ABC1234XYZ --password <app-specific>
```

> **Troubleshooting: `codesign failed: ... errSecInternalComponent`.** If every
> real-identity `codesign` call fails immediately with this error — including
> on files that ad-hoc sign fine, and even after `kivyforge`'s own retry
> (`machotools.codesign_identity` retries a few times for genuinely transient
> `securityd` flakiness) — the private key's Access/ACL object in your login
> keychain is likely corrupted rather than the failure being transient. This
> has been observed after using Keychain Access's "reset my default keychain"
> flow. Symptoms: `security set-key-partition-list ...` on `login.keychain-db`
> aborts with `SecKeychainItemCopyAccess: The specified item is no longer
> valid`, and the problem survives rebooting and re-issuing the certificate.
> The fix is to stop fighting the corrupted keychain: create a dedicated
> keychain for signing (`security create-keychain`), make it temporarily
> default so Xcode's *Manage Certificates → +* writes the new key pair there
> instead, add it to the keychain search list (`security list-keychains -d
> user -s <new>.keychain-db login.keychain-db`), and run
> `set-key-partition-list` scoped to just that keychain. If the same
> certificate name ends up matching in both keychains, `codesign` refuses to
> guess and reports `ambiguous` — delete the broken copy from
> `login.keychain-db` (Keychain Access → Certificates tab) so only the working
> one remains. Storing the `notarytool` credential profile with `--keychain
> <new>.keychain-db` keeps everything for Developer ID distribution in one
> known-good place, immune to future login-keychain resets. This isn't an
> ad-hoc workaround: Apple DTS's
> [The Care and Feeding of Developer ID](https://developer.apple.com/forums/thread/732320)
> recommends keeping a Developer ID identity in its own keychain (separate
> password/locking policy) precisely because these identities are hard to
> replace, and recommends an independent `.p12` export as a backup. For the
> general `errSecInternalComponent` failure mode (locked keychains, ACL
> prompts, SSH/CI contexts), see Apple DTS's
> [Resolving errSecInternalComponent errors during code signing](https://developer.apple.com/forums/thread/712005).

**Behavior of `package -p macos`** (config-driven, flag-overridable):

- No `identity` configured → the ad-hoc floor (unchanged Phase-3 behavior).
- `identity` set (or `--signing-identity`) → **Developer ID deep sign**:
  every bundled Mach-O (the runtime's `python3`/`libpython`/`.dylib`s and the
  wheels' `.so`s) is signed inside-out (deepest first, the `.app` seal last)
  with **Hardened Runtime** (`--options runtime`) + secure `--timestamp`.
- `notary_profile` also set → **notarize + staple** by default: `ditto -c -k
  --keepParent` zip → `xcrun notarytool submit --wait` → on acceptance
  `xcrun stapler staple`. On rejection the notary log's per-file issues are
  surfaced in the error. `--no-notarize` skips the submission (sign only);
  `--notarize` forces it (an error when no profile is available);
  `--notary-profile` overrides the config.

The `.app` seal carries the merged entitlements — defaults a hardened Python
bundle needs, with `[tool.kivy.macos.entitlements]` layered on top (user wins):

- `com.apple.security.cs.allow-unsigned-executable-memory` — ctypes/cffi
  trampolines allocate W+X pages the Hardened Runtime otherwise forbids.
- `com.apple.security.cs.disable-library-validation` — the app loads wheel
  `.so`/`.dylib` binaries signed by other teams.

`build` / `run` stay ad-hoc regardless of config — Developer ID signing (and its
keychain prompts / timestamp round-trips) belongs to the distribution verb, not
the dev loop.

**`.dmg`-level signing/notarization stays external** (a post-packaging step on a
container kivyforge does not build — `.dmg` creation is permanently out of
kivyforge's scope). For users who wrap the already-notarized `.app` in a `.dmg`
and want the container notarized too, the mechanics are the same and
copy-paste-able:

```bash
codesign --sign "Developer ID Application: Jane Doe (ABC1234XYZ)" MyApp.dmg
xcrun notarytool submit MyApp.dmg --keychain-profile kivyforge-notary --wait
xcrun stapler staple MyApp.dmg
```

## `doctor` checks (macOS)

| Check | Scope | What it validates |
|-------|-------|-------------------|
| Host is macOS | environment | The macOS backend requires a macOS host (host-capability check). |
| Codesign available | environment | `codesign` present (ships with the Xcode command-line tools). |
| Not running as root | environment | WARN if `kivyforge` itself is running as root/sudo — Apple DTS notes this mixes execution contexts and is a common source of `errSecInternalComponent` (see [FAQ.md](../../../../FAQ.md#macos-developer-id-signing-fails-with-errsecinternalcomponent)). |
| kivyforge version | environment | Self-version; warn if newer on PyPI (best-effort). |
| App source directory | project | `[tool.kivy].app_dir` resolves to an existing directory. |
| Runtime floor vs. `minimum_system_version` | project | `[tool.kivy.macos].minimum_system_version` ≥ the bundled runtime's floor. |
| Architecture coverage | project | Every arch in `[tool.kivy.macos].archs` has a resolvable wheel (per-arch or universal2) for each compiled dependency, and a per-arch runtime is available; FAIL names the offending package/arch. |
| App icon | project | If `[tool.kivy.macos.icons].source` is set, FAIL unless a valid 1024×1024 PNG. SKIP if unset. |
| find_links directories | project | If set, each entry is an existing directory containing `.whl` files. |
| Required hosts reachable | project | TCP-connect to every host the lockfile fetches from (derived from `pylock.macos.toml`). |
| Signing identity | project | When Developer ID signing is configured, the identity is present in exactly one keychain (`security find-identity`). SKIP when unconfigured (ad-hoc floor). FAIL if it's present in more than one keychain (`codesign` refuses to disambiguate). WARN if it's found scoped to `login.keychain-db` — Apple's "Care and Feeding of Developer ID" recommends a dedicated keychain so unrelated login-keychain churn can't corrupt the signing key's ACL. |
| Signing identity type | project | WARN if the configured identity isn't a `Developer ID Application`/`Developer ID Installer` certificate — notarization rejects any other type (e.g. `Apple Development`). SKIP when unconfigured. |
| Notary setup | project | When `notary_profile` is configured, `xcrun notarytool` is available. Profile *validity* needs a network round-trip and is verified at submit time. |

`doctor` reports each check as PASS / WARN / FAIL with a remediation hint; exit
code is non-zero only on FAIL.

Config-time (`kivyforge lock`/`build`/`package`, not `doctor`): setting
`com.apple.security.get-task-allow = true` in `[tool.kivy.macos.entitlements]`
while `[tool.kivy.macos.signing]` is configured is a hard `ConfigError` —
notarization always rejects that entitlement (see Apple's "Resolving common
notarization issues"), so failing fast at config-load time beats a slow
build-then-notarize round trip.

## Host requirements

- A macOS host (Apple Silicon or Intel). The Xcode command-line tools provide
  `codesign`; the full Xcode IDE is **not** required for a macOS `.app` (unlike
  iOS).
- No Apple Developer account is needed for ad-hoc signing. Developer ID signing
  + notarization needs a **paid** Apple Developer Program membership (a free
  Apple ID cannot issue Developer ID certificates or use the notary service).
