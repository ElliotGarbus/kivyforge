# Abstraction Leak Retro (pre-Windows)

A factual record of where KivyForge's shared abstractions bent, leaked, or were
bypassed across the three shipped backends (iOS, macOS, Linux). This document
records what happened; it proposes nothing. Findings are ordered by how
load-bearing the seam is.

Backends read as `ios` / `macos` / `linux` throughout.

---

## Seam 1 — the `Platform` backend ABC (`kivyforge/platforms/base.py`)

Every verb resolves a backend (`cli/_platform.py:resolve_target`) and dispatches
to it. This is the most load-bearing seam; it is also where the most iOS-shaped
concessions sit in nominally shared code.

### 1.1 Widening — the `build` signature carries three iOS-only signing params

`Platform.build` takes `team_id`, `signing_identity`, `export_method`
(`base.py:75-87`). Only `ios` consumes them.

```75:87:kivyforge/platforms/base.py
    def build(
        self,
        project_root: Path,
        *,
        target: str | None,
        arch: str | None,
        no_verify_lock: bool,
        no_cache: bool,
        team_id: str | None,
        signing_identity: str | None,
        export_method: str,
    ) -> None:
```

`macos` (`platforms/macos/__init__.py:44-64`) and `linux`
(`platforms/linux/__init__.py:45-65`) accept all three and forward none of them
to `macos_build` / `linux_build`. The CLI passes the full superset unconditionally
(`cli/build.py:90-99`).

### 1.2 Widening — `run` carries `destination`; `package` carries five cross-backend params

`Platform.run` carries `destination` (`base.py:89-98`); only `ios` uses it
(`platforms/ios/__init__.py:74-81` passes it through, `macos`/`linux` drop it —
`platforms/macos/__init__.py:66-77`, `platforms/linux/__init__.py:67-78`).

`Platform.package` (`base.py:100-113`) carries `team_id`, `signing_identity`,
`export_method` (iOS), `notarize`, `notary_profile` (macOS), and `fmt` (Linux)
in one signature. No backend uses more than a subset: `ios`
(`platforms/ios/__init__.py:99-106`) uses `team_id`/`signing_identity`/
`export_method`; `macos` (`platforms/macos/__init__.py:95-103`) uses
`signing_identity`/`notarize`/`notary_profile` and drops `team_id`/`export_method`/
`fmt`; `linux` (`platforms/linux/__init__.py:96-102`) uses `fmt`/`arch` only.

### 1.3 iOS concession in shared code — `reject_ios_only_target`

`base.py:131-144` exists only to let the desktop backends reject the iOS
`--simulator/--device/--release` flags, and it contains a host-name branch:

```131:144:kivyforge/platforms/base.py
    def reject_ios_only_target(self, target: str | None) -> None:
        """Desktop backends reject the iOS-only ``--simulator/--device/--release``."""
        if target is None:
            return
        from kivyforge.cli._common import ToolchainError

        artifact = ".app" if self.name == "macos" else "AppDir"
        raise ToolchainError(
            f"--{target} is an iOS target; {self.name} has no simulator/device/"
            "release targets.\n"
            f"  Use `kivyforge build -p {self.name}` (optionally --arch) to build "
            f"the {artifact}, or `kivyforge package -p {self.name}` for the "
            "distributable."
        )
```

`self.name == "macos"` is a backend-name string comparison inside the shared base
class. This method is called by `macos` and `linux` `build`
(`platforms/macos/__init__.py:56`, `platforms/linux/__init__.py:57`); `ios` never
calls it. The `--simulator/--device/--release` flags themselves are declared on
the shared `build` command (`cli/build.py:26-37`) and `run` command
(`cli/run.py:13-22`).

### 1.4 Under-abstraction — `open_project` is meaningful for exactly one backend

`base.py:116-121` defaults to raising an iOS/Xcode-worded error:

```116:121:kivyforge/platforms/base.py
    def open_project(self, project_root: Path) -> None:
        from kivyforge.cli._common import ToolchainError

        raise ToolchainError(
            f"`open` is an iOS/Xcode command; {self.name} has no project to open."
        )
```

Only `ios` overrides it (`platforms/ios/__init__.py:108-111`). `macos`/`linux`
inherit the raise. The `open` verb (`cli/open_cmd.py:10-15`) is a shared command
that resolves any backend and calls `open_project`.

### 1.5 Bypass — the shared `run` verb reaches directly into the iOS backend

`cli/run.py:7` imports `ios_list_devices` at module top and calls it before any
target is resolved:

```51:53:kivyforge/cli/run.py
    if list_devices:
        ios_list_devices()
        return
```

`--list-devices` (`cli/run.py:32-36`) is a shared `run` option wired straight to
iOS, not routed through `Platform`.

### 1.6 `status` is now a `Platform` verb; `upgrade` dispatches on backend name

`status` was promoted to a `Platform` method (`base.py:123-124`, default
`NotImplementedError`) and is now implemented by all three backends
(`platforms/ios/__init__.py:113-116`, `platforms/macos/__init__.py:105-108`,
`platforms/linux/__init__.py:104-107`). The verb resolves the target and
dispatches (`cli/status.py`):

```15:20:kivyforge/cli/status.py
@click.command()
@platform_option
def status(cli_platform: str | None) -> None:
    """Show app identity, Python version, lock sync, and build state."""
    backend, project_root = resolve_target(cli_platform)
    backend.status(project_root)
```

`upgrade` is now platform-aware (`-p`) but branches on the backend name in the
verb body rather than dispatching through `Platform` (`cli/upgrade.py:59-72`):

```59:72:kivyforge/cli/upgrade.py
    if backend.name == "ios":
        _upgrade_ios(project_root, python_only, xcframeworks_only, name)
    elif backend.name in ("macos", "linux"):
        if xcframeworks_only:
            raise ToolchainError(
                f"--xcframeworks is iOS-only; {backend.name} locks have no "
                "xcframework artifacts. Use --python (or no flag) to refresh "
                "the bundled runtime."
            )
        _upgrade_wheelruntime(backend.name, project_root, name)
    else:
        raise ToolchainError(
            f"`kivyforge upgrade` does not support platform {backend.name!r} yet."
        )
```

`--xcframeworks` (`cli/upgrade.py:38-43`) is an iOS-only flag on the shared
`upgrade` command, rejected for macOS/Linux at runtime. `upgrade` is not routed
through a `Platform` method — the per-backend refresh logic (`_upgrade_ios` at
`cli/upgrade.py:82`, `_upgrade_wheelruntime` at `cli/upgrade.py:156`) lives in the
shared verb module and imports the iOS loader at module top
(`cli/upgrade.py:23`) while lazily importing the macOS/Linux loaders inside
`_load_wheelruntime_lock` (`cli/upgrade.py:200-203`).

### 1.6a Duplication — the `status` helpers are triplicated across backends

The `status` implementations each re-declare identical `_build_state` and
`_humanize` helpers: `platforms/ios/cli.py:493-513`,
`platforms/macos/cli.py:209-227`, `platforms/linux/cli.py:180-198`. The three
`_lock_state` variants differ only in the platform name in their messages
(`platforms/macos/cli.py:195-206`, `platforms/linux/cli.py`). macOS/Linux locate
the built artifact by `config.display_name` (`platforms/macos/cli.py:191`); iOS
uses `config.app_slug` and reports two build slices (`platforms/ios/cli.py:474-479`).

### 1.7 Silent iOS default in shared entry points

The top-level CLI help calls the whole tool an iOS bundler
(`cli/__init__.py:31-34`): `"kivyforge 3.0 — a declarative iOS bundler for Kivy
apps."`.

`doctor` falls back to iOS when no target resolves
(`cli/doctor.py:46-48`):

```46:48:kivyforge/cli/doctor.py
    except PlatformResolutionError:
        # Environment-mode fallback: no project/target to infer from.
        return get_platform("ios")
```

`config.load_config` defaults `require_ios=True` (`config/loader.py:53-56`), so
every caller that does not explicitly pass `require_ios=False` demands the iOS
overlay.

### 1.8 Over-broad shared interface — the `Probe` protocol

The backend `doctor` verb (`base.py:126-129`) dispatches to per-backend doctors,
but all of them depend on one flat `Probe` protocol (`doctor/probe.py:34-54`) that
mixes iOS methods (`xcode_version`, `simulator_runtimes`, `keychain_identities`),
macOS methods (`has_codesign`, `has_notarytool`, `login_keychain_identities`), and
Linux methods (`linux_libc`, `shared_libraries`, `display_session`,
`has_desktop_file_validate`, `desktop_file_errors`) on one interface. A single
`RealProbe` implements all 24; any test fake must satisfy the same union.

### 1.9 Shared verb enumerates each backend's output tree by hand

`cli/clean.py:42-47` hard-codes each backend's generated paths in shared code:

```42:47:kivyforge/cli/clean.py
        targets = [
            cwd / f"{config.app_slug}-ios",
            cwd / "build" / "macos",
            cwd / "build" / "linux",
            cwd / "dist" / "linux",
        ]
```

`clean` does not go through `Platform`; the layout of every backend's output is
duplicated here.

---

## Seam 2 — the config schema (`[tool.kivy]` vs `[tool.kivy.<platform>]`)

Read by every verb, backend, and lock builder. `config/model.py` +
`config/loader.py`.

### 2.1 The "swappable Signer" does not exist; two unrelated signing configs do

There is no `Signer` protocol anywhere in `kivyforge/` (only `Downloader`,
`MetadataFetcher`, `RuntimeProvider`, `PythonRuntime`, `Probe`,
`WheelResolver`, `Resolver`, `SpmResolver`, `PythonXcframeworkProvider`,
`_HasPyprojectSha`). Signing is two disjoint config dataclasses and two
free-function code paths:

- `SigningConfig` (iOS) — `team_id`, `identity` (default `"Apple Development"`),
  `provisioning_profile`, `auto_signing`, `upload_symbols`
  (`config/model.py:187-193`).
- `MacosSigningConfig` — `identity`, `team_id`, `notary_profile`, plus a
  `configured` property (`config/model.py:220-236`).
- `linux` has no signing config at all.

The actual macOS signing is plain functions (`sign_bundle_adhoc`,
`sign_bundle_developer_id` — `platforms/macos/signing.py:37-71`); iOS signing is
carried into Xcode build settings, not a signer object. The two config shapes are
parsed by two separate parsers (`_parse_signing` — `config/loader.py:1386-1411`;
`_parse_macos_signing` — `config/loader.py:567-588`). This seam (a "swappable
signing Protocol") is not present in the code; see Unverified Claims.

### 2.2 Silent desktop/mobile assumptions in the cross-platform `[tool.kivy]` table

`KivyMeta` (`config/model.py:291-298`) is the cross-platform table. It carries
`orientation`, validated against a fixed set of mobile screen orientations
(`config/model.py:57-59`, `config/loader.py:259-274`):

```57:59:kivyforge/config/model.py
VALID_ORIENTATIONS = frozenset(
    {"portrait", "portrait-upside-down", "landscape-left", "landscape-right"}
)
```

`orientation` is only consumed by iOS Info.plist generation; it lives in the
neutral table and defaults to `("portrait",)` for every target.

`app_dir` validation, also in the neutral `[tool.kivy]` parser, hard-codes the iOS
build-output name in its hint (`config/loader.py:221-224`): "keep app code in a
subdirectory (e.g. src/) so the bundle excludes .git/, .venv/, and the
`<app>-ios/` build output."

### 2.3 iOS-shaped derived property on the shared `Config`

`Config.app_slug` (`config/model.py:317-320`) is documented and named for Xcode:

```317:320:kivyforge/config/model.py
    @property
    def app_slug(self) -> str:
        """The Xcode target / folder slug derived from [project].name."""
        return self.project.name
```

It is used by all three backends' output paths (`ios`: `platforms/ios/cli.py:164`;
`macos`/`linux` via `clean.py:43` and `linux/cli.py:69`).

### 2.4 The OS-floor concept has three different config keys and types

Each overlay names the same idea differently: `ios.deployment_target`
(str, default `"13.0"` — `config/model.py:203`), `macos.minimum_system_version`
(`str | None` — `config/model.py:251`), `linux.glibc_floor` (`str | None` —
`config/model.py:281`). The app-identity key also diverges: `ios.bundle_id`,
`macos.bundle_id`, `linux.app_id` (`config/model.py:198,241,280`).

### 2.5 Two parallel parsers for keys that are described as a shared surface

`find_links` is called "a shared iOS/macOS/Linux surface"
(`config/loader.py:1104-1105`), but iOS has its own parser and scope validator
(`_parse_find_links` — `config/loader.py:1057-1079`; `_validate_find_link_scope`
defaulting `key_path="tool.kivy.ios.find_links"` — `config/loader.py:1090-1095`),
while macOS/Linux share `_parse_platform_find_links`
(`config/loader.py:866-890`). Likewise the Python version: iOS uses
`_parse_python_version` (`config/loader.py:988-1015`) and its own
`_check_requires_python` (`config/loader.py:1018-1054`); macOS/Linux use
`_parse_platform_python_version` (`config/loader.py:834-854`) and
`_check_requires_python_generic` (`config/loader.py:906-943`). The two
`_check_requires_python*` bodies differ only in wording.

### 2.6 iOS schema constant sits apart from the generic platform-schema helper

`_parse_ios` inlines its own `schema_version` validation
(`config/loader.py:296-321`) against `SUPPORTED_IOS_SCHEMA_VERSION`, whereas
`macos`/`linux` call the shared `_parse_platform_schema_version`
(`config/loader.py:799-831`). The iOS block predates the shared helper and was not
folded into it.

---

## Seam 3 — the artifact / wheel / download path

`fetch_artifact` + `ArtifactCache` + `verify` are genuinely shared; the wheel and
framework machinery around them is iOS-only but lives in the shared package.

### 3.1 The shared `artifacts/` package is mostly iOS, and reaches into the iOS backend

`artifacts/__init__.py:1` describes itself as the neutral artifact layer, but of
its modules only `cache.py`, `download.py`, `verify.py` are backend-neutral.
`artifacts/wheels.py`, `artifacts/frameworks.py`, `artifacts/collect.py`, and
`artifacts/runtime.py` are iOS-specific:

- `artifacts/wheels.py:14-18` — `TARGET_SUFFIX` keyed on `device`/`simulator` and
  `ios_*` tags; `BuildSlice.platform_tag` produces `ios_<dt>_<suffix>`
  (`wheels.py:27-33`).
- `artifacts/collect.py:19` imports the iOS lock model directly:
  `from ..platforms.ios.lock.model import Lockfile`. The shared artifact package
  depends on the iOS backend, inverting the platform→artifacts direction.
- `artifacts/collect.py:134-162` (`_install_python_xcframework`) and the
  `.frameworks/` handling (`frameworks.py`) have no desktop counterpart.

`artifacts/__init__.py:12-19,30-40` re-exports `PythonOrgRuntime`,
`BuildSlice`, `select_wheel`, `copy_wheel_frameworks`,
`extract_xcframework_archive` — all iOS — as the package's public surface.

### 3.2 Wheel location is two separate mechanisms

iOS selects a per-slice wheel from an already-resolved lock by matching
`ios_<major>_<minor>_<arch>_<sdk>` tags with compatibility matching
(`artifacts/wheels.py:36-85`). macOS/Linux never do slice selection at build time;
their wheels are resolved and coverage-checked at lock time in the generic engine
(`lock/wheelruntime/builder.py:185-210`) using per-profile tag rules
(`macos.wheel_covers` — `platforms/macos/lock/profile.py:70-76`;
`linux.wheel_coverage` — `platforms/linux/lock/profile.py:200-213`). The Linux
profile additionally source-gates plain `linux_*` wheels on `wheel.path is not
None` (`platforms/linux/lock/profile.py:100-122`) — a `find_links`-provenance
branch that no other profile has.

### 3.3 `find_links` diagnostics carry an iOS branch and an iOS default

`lock/find_links.py` parameterizes messages by `platform` but defaults every
entry point to `"ios"` (`find_links.py:26,70,115,134`) "for backward
compatibility with the original iOS-only call sites" (`find_links.py:5-6`), and
branches on the backend name for the example wheelhouse hint:

```138:148:kivyforge/lock/find_links.py
    if "examples" in project_root.parts and project_root.name != "wheels":
        if platform == "ios":
            # iOS ships a helper script to build its examples wheelhouse.
            shared_note = (
                "  Shared example wheels live under examples/wheels/ios/ — run "
                "`scripts/build_ios_wheels.sh` from the repo root.\n"
            )
        else:
            shared_note = (
                f"  Shared example wheels live under examples/wheels/{platform}/.\n"
            )
```

`examples/wheels/` contains only `ios/` (which holds only `.gitkeep` +
`.gitignore`); there is no `examples/wheels/macos/` or `.../linux/`.

### 3.4 Host-OS branch in the neutral cache root

`ArtifactCache`'s root selection branches on the host OS, including a
Windows arm already present pre-Windows (`artifacts/cache.py:24-35`): `if system
== "Darwin"` / `if system == "Windows"` / else XDG. This is a host-OS branch (not
a build-target branch) in otherwise target-neutral code.

---

## Seam 4 — the Python runtime abstraction

The stated seam is "one interface spanning python-build-standalone (macOS, Linux)
and python.org's `Python.xcframework` (iOS)." In the code there is no single
interface spanning them. There are two, with colliding type names.

### 4.1 Two `PythonRuntime` types and two `RuntimeArtifact` types, unrelated

- iOS: `artifacts/runtime.py:24` `class PythonRuntime(Protocol)` with
  `xcframework_artifact` + `build_python_invocation`; `RuntimeArtifact` is
  `(version, url, archive_format)` (`runtime.py:16-21`); the only implementation
  is `PythonOrgRuntime` (`runtime.py:38-59`), selected via `get_runtime`
  (`runtime.py:62-65`).
- macOS/Linux: `lock/wheelruntime/model.py:43` `class PythonRuntime` is a
  frozen dataclass `(provider, version, artifacts, floor)`; `RuntimeArtifact` is
  `(arch, url, sha256, archive_format)` (`model.py:28-39`). The provider seam is a
  different protocol, `RuntimeProvider` (`lock/wheelruntime/runtime.py:81-86`),
  implemented by `PbsProvider` (`runtime.py:89-145`).

macOS re-exports the wheelruntime `PythonRuntime` under an alias to avoid the name
clash (`platforms/macos/lock/__init__.py:17-19`): `PythonRuntime as
MacosPythonRuntime`.

### 4.2 The iOS runtime "seam" has one implementation and is used only by iOS + tests

`PythonOrgRuntime` / `get_runtime` / `xcframework_artifact` /
`build_python_invocation` are referenced only in `artifacts/runtime.py`, the
`artifacts/__init__.py` re-export, and `tests/artifacts/test_wheels_runtime.py`
(no non-test caller of `get_runtime` outside that module). The `PythonRuntime`
Protocol (`runtime.py:24-35`) has exactly one implementer.

### 4.3 The desktop runtime provider is duplicated per backend

`get_runtime_provider` + `PythonBuildStandaloneProvider` exist twice, differing
only in the arch→triple map and default floor:

- `platforms/macos/lock/runtime.py:30-58` — `DARWIN_TRIPLES`, no floor.
- `platforms/linux/lock/runtime.py:45-75` — `LINUX_TRIPLES`,
  `floor=DEFAULT_GLIBC_FLOOR="2.17"`.

Both subclass the generic `PbsProvider` (`lock/wheelruntime/runtime.py:89`), and
both re-declare an identical `get_runtime_provider` factory with the same accepted
aliases and the same error string.

### 4.4 Runtime staging is duplicated across the two desktop backends

`platforms/macos/runtime_stage.py` and `platforms/linux/runtime_stage.py` share
`stage_runtime` / `_fetch` / `_extract` / `_safe_extractall` almost verbatim; they
differ in the exception type (`AppBundleError` vs `AppDirError`) and in macOS's
extra universal2 `lipo` merge (`macos/runtime_stage.py:71-74,121-137`). Linux's
`stage_runtime` takes a single `arch` (`linux/runtime_stage.py:33-41`); macOS
takes `archs: tuple[...]` (`macos/runtime_stage.py:31-39`). Both consult the
provider-keyed layout via `normalized_runtime_root`
(`lock/wheelruntime/runtime.py:37-57`), whose registry currently has exactly one
entry (`_PROVIDER_ARCHIVE_ROOTS = {PBS_PROVIDER_NAME: "python"}` —
`runtime.py:32-34`).

### 4.5 The linux glibc floor is a pinned constant, flagged as such

`platforms/linux/lock/runtime.py:32-45` records `DEFAULT_GLIBC_FLOOR = "2.17"` as
a "pinned assumption about PBS's build baseline, not a value derived from
inspecting the resolved artifact," with a note that it must be bumped in lockstep
with PBS. macOS has no equivalent floor (it passes `floor=None`).

---

## Seam 5 — the lock engine split

Not listed separately in scope, but it underlies seams 3 and 4 and determines the
runtime/wheel/config shapes above.

### 5.1 iOS has a complete parallel lock stack; macOS/Linux share one

`platforms/ios/lock/` is ~1,800 lines of its own `builder`, `resolver`, `reader`,
`writer`, `model`, `spm`, `xcframework`, `python_meta`
(`platforms/ios/lock/__init__.py:13-38`). macOS and Linux are thin profiles over
one generic engine (`lock/wheelruntime/`): `platforms/macos/lock/__init__.py:74-95`
and `platforms/linux/lock` both call `build_wheel_runtime_lock` with a
`PlatformLockProfile` (`lock/wheelruntime/profile.py:20`). iOS is explicitly
excluded from that family (`lock/wheelruntime/model.py:6-9`): "iOS is deliberately
not part of this family — its per-slice framework conversion,
`Python.xcframework` runtime, and SPM extension give it a genuinely different lock
shape."

### 5.2 Backend-name string dispatch + iOS asymmetry in the shared `lock` verb

`cli/lock.py:51-96` dispatches by backend name string:

```51:66:kivyforge/cli/lock.py
def _lock_ops(platform: str) -> _LockOps:
    if platform == "ios":
        # Reference the module globals (not a local import) so tests can patch
        # ``lock_cli.build_lockfile`` with a fake-injecting wrapper.
        return _LockOps(
            build=build_lockfile,
            dumps=dumps,
            load=load,
            semantic_equal=semantic_equal,
            diff_summary=diff_summary,
            build_error=BuildError,
            require_ios=True,
            require_macos=False,
        )
    if platform == "macos":
```

iOS's lock ops are imported at module top (`cli/lock.py:21-28`) so tests can patch
them; macOS/Linux are lazily imported inside their branches
(`cli/lock.py:66,80`). `_LockOps` carries three `require_ios`/`require_macos`/
`require_linux` booleans (`cli/lock.py:43-45`). `WheelRuntimeLock.platform` is a
free-form string field documented as `"macos" | "linux" | "windows" | "android"`
(`lock/wheelruntime/model.py:59-62`); the iOS `Lockfile` has no such field.

### 5.3 `LOCKFILE_NAME` is hard-coded to the iOS lockfile in shared CLI code

`cli/_common.py:14-16` keeps a hard-coded iOS name, and `lockfile_path` returns
it:

```13:16:kivyforge/cli/_common.py
PYPROJECT_NAME = "pyproject.toml"
# iOS lockfile name, kept for the iOS verbs' backward-compatible call sites.
# New/platform-aware code uses ``lockfile_name``/``lockfile_path_for``.
LOCKFILE_NAME = "pylock.ios.toml"
```

The platform-aware helper `lockfile_path_for(platform)` exists alongside
(`_common.py:60-63`) and is used by macOS/Linux (`cli/lock.py:115`,
`platforms/linux/cli.py:16,116,170`) and now by `upgrade`
(`cli/upgrade.py:24` imports `lockfile_path_for`; `_load_ios_lock` uses
`lockfile_path_for('ios')` at `cli/upgrade.py:144`). The iOS backend still
imports and uses the hard-coded `LOCKFILE_NAME`/`lockfile_path`
(`platforms/ios/cli.py:20-24,307`),
so the constant persists only for the iOS build/run/status call sites.

---

## iOS divergence

This is the point of the document. iOS is the only backend that generates a native
IDE project instead of assembling a bundle directly, and the only mobile backend.

### What iOS does that has no desktop counterpart at all

- **Xcode project generation.** `materialize_project`
  (`platforms/ios/materialize.py:30-59`) emits `main.m`, `main_config.h`,
  `<app>-Info.plist`, `<app>.entitlements`, `PrivacyInfo.xcprivacy`,
  `Assets.xcassets`, `LaunchScreen.storyboard`, and a `.xcodeproj` via
  `XcodeProjectGenerator`. macOS/Linux assemble a bundle/AppDir directly
  (`platforms/macos/bundle.py`, `platforms/linux/bundle.py`) with no generated IDE
  project.
- **Info.plist / bundle-id / entitlements machinery.** `platforms/ios/plist.py`,
  `entitlements.py`, `privacy.py`, plus `MANAGED_INFO_PLIST_KEYS`
  (`config/model.py:74-92`) and `RESERVED_BUILD_SETTINGS`
  (`config/model.py:96-114`) — schema-reserved key sets that exist only for iOS.
- **Simulator vs device.** `BuildSlice` and `TARGET_SUFFIX`
  (`artifacts/wheels.py:14-33`), slice resolution
  (`platforms/ios/cli.py:237-271`), `simctl`/`devicectl` install+launch
  (`platforms/ios/cli.py:380-393`), device listing (`ios_list_devices` —
  `platforms/ios/cli.py:369-373`). Desktop `run` just execs the built artifact
  (`platforms/linux/cli.py:145-150`; `macos_run` — `platforms/macos/cli.py:87-91`).
- **SPM.** `platforms/ios/swift_packages.py`, `platforms/ios/lock/spm.py`,
  `LockedSwiftPackage` (`platforms/ios/lock/model.py:52-76`), `SwiftPackageDep`
  (`config/model.py:162-184`), and `VALID_SWIFT_REQUIREMENT_KINDS`
  (`config/model.py:157-159`). No desktop analog.
- **`exclude` list semantics.** All three overlays have `exclude`
  (`config/model.py:207,255,285`), but iOS's is consumed together with the
  per-slice wheel selection; macOS/Linux `exclude` is applied in the generic
  builder (`lock/wheelruntime/builder.py:84-85,106-107`).
- **Vendored-wheel path.** `examples/wheels/ios/` is the only populated example
  wheelhouse, and `scripts/build_ios_wheels.sh` is referenced by name in the
  shared `find_links` hint (`lock/find_links.py:141-143`).
- **Kivy version split.** Mobile examples pin `kivy>=3.0.0.dev0,<4`
  (`examples/mobile/hello-kivy/pyproject.toml:10`); desktop examples pin
  `kivy>=2.3.1` (`examples/desktop/dice-roller/pyproject.toml:8`). Mobile examples
  live under `examples/mobile/` with `[tool.kivy.ios]`; desktop under
  `examples/desktop/` with `[tool.kivy.macos]` + `[tool.kivy.linux]`.
- **The `open` verb** exists only because iOS produces something to open
  (`cli/open_cmd.py`, `platforms/ios/cli.py:436-453`).

### Divergences handled inside the iOS backend

- All of `platforms/ios/*` (assets, buildsettings, entitlements, generator, plist,
  privacy, skeleton, sources, staging, swift_packages, xcframeworks, xcode/) and
  `platforms/ios/lock/*` are self-contained under the backend.
- iOS's own lock engine (5.1) keeps the SPM/xcframework/xcframework-runtime shapes
  out of the generic wheel+runtime engine.
- `simctl`/`devicectl` command construction and running live in
  `platforms/ios/xcode/` (`commands.py`, `runner.py`).

### Divergences that forced a change to shared code (iOS-shaped concessions)

- `Platform.build`/`run`/`package` signatures carry iOS-only params (1.1, 1.2).
- `Platform.open_project` default and `reject_ios_only_target` (1.3, 1.4).
- The shared `run` verb's `--simulator/--device/--release` flags and
  `--list-devices` (1.5), and the shared `build` verb's iOS signing flags
  (`cli/build.py:26-61`).
- `upgrade` branches on the backend name in the shared verb body and carries an
  iOS-only `--xcframeworks` flag; `status`, since being promoted to a `Platform`
  method, is now dispatched like the other verbs (1.6).
- `require_ios=True` default, the iOS doctor fallback, and the "iOS bundler"
  program description (1.7).
- The shared `artifacts/` package is iOS-shaped and imports the iOS lock model
  (3.1).
- `find_links` defaults to `platform="ios"` and branches on it (3.3).
- `LOCKFILE_NAME = "pylock.ios.toml"` in shared CLI code (5.3).
- Config: `orientation` and the `<app>-ios/` hint in the neutral `[tool.kivy]`
  table (2.2); `app_slug` documented as the Xcode slug (2.3); the iOS-only
  `_parse_find_links`/`_parse_python_version`/`_check_requires_python` paths and
  inlined iOS schema check that predate the shared helpers (2.5, 2.6);
  `MANAGED_INFO_PLIST_KEYS` / `RESERVED_BUILD_SETTINGS` module-level constants in
  the shared model (`config/model.py:74-114`).
- The lock verb top-imports iOS ops and special-cases `"ios"` first (5.2).

---

## Interface census — `Platform` methods × backends

Legend: **impl** = implemented meaningfully; **partial** = implemented but ignores
part of the shared signature; **stub** = inherits a base raise / no-op; **n/a** =
not applicable.

| `Platform` member | source | ios | macos | linux |
|---|---|---|---|---|
| `name` / `aliases` / `host_system` / `package_formats` | class attrs | impl (`host_system=None`) | impl (`Darwin`) | impl (`Linux`) |
| `default_package_format` / `selectors` | `base.py:51-58` | identical (inherited) | identical | identical |
| `check_host_capability` | `base.py:60-67` | impl | impl | impl |
| `build` | `base.py:75-87` | impl (uses target/team_id/signing_identity/export_method/arch) | partial (uses arch; ignores target*/team_id/signing_identity/export_method; calls `reject_ios_only_target`) | partial (same as macos) |
| `run` | `base.py:89-98` | impl (uses target/destination/no_build) | partial (uses arch/no_build; ignores target/destination) | partial (uses arch/no_build; ignores target/destination) |
| `package` | `base.py:100-113` | partial (uses team_id/signing_identity/export_method; ignores fmt/arch/notarize/notary_profile) | partial (uses arch/signing_identity/notarize/notary_profile; ignores team_id/export_method/fmt) | partial (uses fmt/arch; ignores team_id/signing_identity/export_method/notarize/notary_profile) |
| `open_project` | `base.py:116-121` | impl | stub (base raise) | stub (base raise) |
| `status` | `base.py:123-124` | impl | impl | impl |
| `doctor` | `base.py:126-129` | impl | impl | impl |
| `reject_ios_only_target` | `base.py:131-144` | n/a (never called) | impl (called from `build`) | impl (called from `build`) |

\* macos `build` calls `reject_ios_only_target(target)` then discards `target`
(`platforms/macos/__init__.py:56-64`); linux likewise
(`platforms/linux/__init__.py:57-65`).

---

## Unverified claims

- **The "swappable Signer Protocol" (scope item 3) is not in the code.** No
  `Signer` protocol or ABC exists in `kivyforge/`. What exists is two config
  dataclasses (`SigningConfig`, `MacosSigningConfig`) and free functions
  (`platforms/macos/signing.py`). I searched for `Protocol` subclasses and
  `Signer`/`sign`/`codesign` symbols; if a signer abstraction is intended, it is
  either planned or lives outside the tree I read. Flagged rather than smoothed
  over.
- I did not execute any build, lock, run, or doctor. All behavior is read from
  source; runtime behavior (e.g. that macOS `run` actually ignores `destination`
  end-to-end, or that `install_python` behaves as the docstring in
  `artifacts/runtime.py:53-59` says) is inferred from the call sites, not observed.
- I read `platforms/macos/bundle.py`, `platforms/macos/cli.py`,
  `platforms/linux/bundle.py`, `platforms/linux/appimage.py`, and the iOS
  `generator.py`/`skeleton.py`/`xcode/*` only partially or by filename/size. The
  claim that these contain no further shared-code concessions is not exhaustive.
- `examples/wheels/ios/` was inspected and contains only `.gitkeep` +
  `.gitignore`; I did not verify that `scripts/build_ios_wheels.sh` exists or does
  what the hint text claims.
- The Kivy 3.0-vs-2.3.1 split is read from two example `pyproject.toml` files
  (`hello-kivy`, `dice-roller`); I did not confirm every example follows the same
  split.
- Platform facts relied on but not verified here: that python.org ships the iOS
  `Python.xcframework` only from 3.15+, that PBS `install_only` linux-gnu archives
  carry a glibc-2.17 baseline, and that the arm64 macOS kernel refuses unsigned
  Mach-O — these are taken from the code's own comments
  (`artifacts/runtime.py:3-6`, `platforms/linux/lock/runtime.py:32-45`,
  `platforms/macos/signing.py:8-9`), not independently checked.
- `LockedSwiftPackage`/`LockedXcframework` line counts and the ~1,800-line figure
  for `platforms/ios/lock/` are from `wc -l`, not a semantic measure.
