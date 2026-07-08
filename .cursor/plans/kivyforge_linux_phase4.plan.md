---
name: Kivyforge Linux backend (Phase 4)
overview: Detailed, step-by-step plan for the Linux backend - [tool.kivy.linux] overlay, pylock.linux.toml (PBS linux-gnu runtime + manylinux wheels), an AppDir-shaped folder bundle as the substrate, AppImage as the primary artifact via a pinned appimagetool + static-FUSE runtime, .desktop/icon/StartupWMClass generation, doctor checks, and Linux overlays on the three desktop examples. Developed on WSL2 Ubuntu (x86_64) on the Windows machine.
todos:
  - id: step0-host-bringup
    content: "Step 0: WSL2 host bring-up - dev env on WSL2 Ubuntu, full test suite green on a Linux host (fix any macOS-host assumptions, XDG cache path ~/.cache/kivyforge), verify WSLg GL, add an ubuntu-latest job to CI (headless pytest)."
    status: pending
  - id: step1-linux-spec
    content: "Step 1: Write docs/design/platforms/linux/linux-spec.md (mirror macos-spec.md structure) encoding all decisions below; validate the pip manylinux --platform expansion behavior with a small spike before freezing the lock design."
    status: pending
  - id: step2-config-overlay
    content: "Step 2: [tool.kivy.linux] overlay parsing + LinuxConfig dataclass (schema_version, app_id, archs=[x86_64], glibc_floor, python.version, icons, desktop.categories, extra_index_urls/find_links/exclude) + loader tests."
    status: pending
  - id: step3-lock
    content: "Step 3: pylock.linux.toml - LinuxProfile (manylinux platform tags, wheel_covers, floor validation) + LinuxPbsProvider (x86_64-unknown-linux-gnu) + golden-lock fixture tests + one live PBS resolution check at the step boundary."
    status: pending
  - id: step4-bundle-build-run
    content: "Step 4: kivyforge/linux/ AppDir bundler (runtime stage, wheels stage, app source, AppRun shell launcher, generated .desktop + icons, SDL WM_CLASS env) + build/run verbs; interactive smoke test on WSLg."
    status: pending
  - id: step5-package
    content: "Step 5: package -f appimage (default) / -f folder - pinned appimagetool + type2 static-FUSE runtime acquisition via the artifacts cache, APPIMAGE_EXTRACT_AND_RUN=1 invocation, output naming; verify the AppImage on WSLg and (recommended) one clean distro VM."
    status: pending
  - id: step6-doctor
    content: "Step 6: doctor/checks_linux.py - host/GL/session checks, glibc floor validation, arch coverage, icon, desktop-file-validate, required hosts reachable (incl. appimagetool assets)."
    status: pending
  - id: step7-examples
    content: "Step 7: add [tool.kivy.linux] overlays + pylock.linux.toml to examples/desktop/{desktop-viewer,dice-roller,notes}; make run-examples.sh handle --platform linux; verify all three on WSLg."
    status: pending
  - id: step8-docs-review
    content: "Step 8: docs sweep (README, FAQ, packaging-scope doc, guides placeholder), CHANGELOG, final regression gate (pytest+ruff green on macOS AND Linux hosts, iOS/macOS examples unaffected). Stop for review."
    status: pending
isProject: false
---

# Kivyforge Linux Backend — Phase 4 Plan

Detailed plan for Phase 4 of the [multi-platform plan](kivyforge_multi-platform_plan_f4e13ebc.plan.md).
Supersedes that document's Phase 4 sketch; the master plan now points here.

## Decisions (locked)

- **AppImage is the primary artifact and the `package` default** (`package -f appimage`).
  The **run-from-folder AppDir** (`package -f folder`) is the **required substrate and
  fallback**: it is the tree the AppImage stage wraps, the no-FUSE/CI/container-safe
  path, and the debugging substrate when an AppImage misbehaves. Native packages
  (`.deb`/`.rpm`) and Flatpak stay **external/deferred** — not built now, revisited only
  on a specific user-demand signal (Flathub/sandboxing/immutable-distro → Flatpak;
  "package for my repo" → native).
- **x86_64 only this phase.** `archs` defaults to `["x86_64"]` and only `x86_64` is an
  allowed value for now. The config field stays list-shaped so `aarch64` is purely
  additive later (PBS ships `aarch64-unknown-linux-gnu`; Kivy has manylinux aarch64
  wheels), but there is no ARM verification host in this phase. Unlike macOS there is
  no fat binary — each arch would be a separate AppImage. Steam Deck/SteamOS is
  x86_64, so it is covered for free.
- **Runtime:** python-build-standalone `x86_64-unknown-linux-gnu` `install_only`
  builds via the existing `RuntimeProvider`/`PbsProvider` machinery (the PBS fetcher
  is already triple-agnostic). This inherits a **glibc ≥ 2.17 floor**
  (manylinux2014-class) with no old-distro build host. **musl is out of scope**
  (static PBS musl builds can't `dlopen()` extensions; moot anyway — Kivy publishes no
  musllinux wheels).
- **No compiled launcher.** The AppDir entry point (`AppRun`) is a POSIX shell script —
  AppImage does not require an ELF `AppRun`, and Linux has no analog of the
  Finder/LaunchServices problem that forced the compiled Mach-O stub on macOS.
  Consequence: **kivyforge builds no native code at package time, so no
  manylinux/low-glibc build container is needed.** (If a compiled shim ever becomes
  necessary, it must be built in a manylinux2014-class container so it doesn't raise
  the bundle's glibc floor above the runtime's — recorded in the spec as a
  conditional, not a task.)
- **AppImage runtime:** embed a **pinned static-FUSE (type2) runtime** via
  `appimagetool --runtime-file`, so users aren't hit by the libfuse2-vs-libfuse3
  packaging mess on current distros (Ubuntu 24.04's `libfuse2t64` rename etc.).
  Document `--appimage-extract-and-run` / `APPIMAGE_EXTRACT_AND_RUN=1` as the no-FUSE
  fallback regardless.
- **Desktop integration is generated, not hand-written:** `.desktop` file + icons come
  from `pyproject.toml` at package time (the Linux analog of Info.plist/.icns), with
  `StartupWMClass` wired so the Kivy/SDL window groups under its own icon.
  **Opt-in first-run self-integration** (copying the `.desktop`/icon into
  `~/.local/share/applications/` after a user prompt, using `$APPIMAGE`/`$APPDIR`) is
  **deferred as a fast-follow** — noted in the spec, not built this phase.
- **Host contract (documented, never vendored):** libGL/libEGL and an X11 or Wayland
  session come from the host — nobody vendors these. The spec and docs state this as
  an explicit requirement so it never surfaces as an opaque runtime crash; it also
  bounds what `kivyfn-3d`'s GL-instancing ctypes loader may assume about the host.
- **Module layout follows the realized repo conventions** (not the master plan's
  aspirational `platforms/linux/` split): `kivyforge/linux/` (bundler),
  `kivyforge/lock/linux/` (profile + runtime provider), `kivyforge/cli/_linux.py`,
  `kivyforge/doctor/checks_linux.py`, plus a small `LinuxPlatform` in
  `kivyforge/platforms/` mirroring how ios/macos register.

## Step 0 — WSL2 host bring-up

First time the project runs on a non-macOS host; flush out latent macOS assumptions
before writing any Linux backend code.

- Set up WSL2 Ubuntu on the Windows machine: clone, venv, editable install.
- **Full `pytest` + `ruff` green on Linux.** Expected friction to fix as part of this
  step:
  - **Artifacts cache path:** `~/Library/Caches/kivyforge` is macOS-only; on Linux use
    `$XDG_CACHE_HOME/kivyforge` (default `~/.cache/kivyforge`). Centralize the
    per-OS cache-dir selection in `kivyforge/artifacts/cache.py` if it isn't already.
  - Any tests that assume macOS host tools (`sips`, `codesign`, `xcrun`) must
    skip-or-fake cleanly on Linux (they may already — verify).
- Verify WSLg OpenGL: `glxinfo -B` shows a renderer (D3D12/Mesa); confirm a trivial
  Kivy app opens a window. Record `LIBGL_ALWAYS_SOFTWARE=1` as the fallback and
  `xvfb-run` + software GL as the headless path.
- **CI:** add an `ubuntu-latest` job to the test workflow (headless pytest; no GL
  needed for unit tests). Cheap and permanent regression coverage for the
  cross-platform core.

**Gate:** test suite green on both macOS and Linux hosts; CI matrix includes Linux.

## Step 1 — Linux design spec

Write `docs/design/platforms/linux/linux-spec.md`, mirroring the section structure of
`docs/design/platforms/macos/macos-spec.md` (scope; overlay + field table; runtime
acquisition; lockfile; artifact layouts; launcher; desktop integration; doctor table;
host requirements), encoding every decision in this plan.

Spec-time spike (small, do before freezing the lock section): **verify pip's
`--platform` manylinux downward expansion** — that requesting e.g.
`manylinux_2_17_x86_64` matches wheels tagged `manylinux2014_x86_64`,
`manylinux2010_*`, `manylinux1_*`, and lower `manylinux_2_y`, and how Kivy 2.3.x's
actual published tags resolve. The lock design below assumes pip expands the manylinux
hierarchy from a single requested tag; if it doesn't in the pip version we pin, the
`Variant`/resolver seam needs a multi-tag request instead — better to know before the
spec ships.

Decision points to settle **in the spec** (small, flagged here so they aren't invented
silently during implementation):

1. **Icon resizing dependency.** macOS used host tools (`sips`/`iconutil`); Linux has
   no equivalent guaranteed present. Options: require the source PNG be usable as-is
   (copy + rename only), or add Pillow as a kivyforge dependency for resize.
   Leaning: Pillow (small, pure-manylinux, already ubiquitous), generating the
   hicolor size set.
2. **Plain `linux_x86_64` vendored wheels** (non-manylinux tags from `find_links`):
   accept-with-warning (they're the user's own wheels, portability is their call) or
   reject. Leaning: accept for `find_links` only, warn that the tag makes no glibc
   promise.
3. **Whether `-f folder` also emits a `.tar.gz`** beside the directory (the "tarball"
   half of dir/tarball). Leaning: directory only, matching `-f app` on macOS; users
   tar it themselves. Revisit on demand.

**Gate:** spec reviewed/approved (same treatment as the macOS spec) before backend code.

## Step 2 — `[tool.kivy.linux]` overlay + `LinuxConfig`

Additive overlay on shared `[project]` + `[tool.kivy]`, mirroring `MacosConfig`:

```toml
[tool.kivy.linux]
schema_version = 1
app_id = "org.example.myapp"     # reverse-DNS; .desktop basename, Icon=, StartupWMClass
glibc_floor = "2.17"             # optional; drives the manylinux resolve tag (see Step 3)
archs = ["x86_64"]               # only x86_64 allowed this phase

[tool.kivy.linux.python]
version = "3.15.0"

[tool.kivy.linux.icons]
source = "assets/icon.png"       # 1024x1024 PNG -> root icon + hicolor sizes

[tool.kivy.linux.desktop]
categories = ["Utility"]         # freedesktop main categories for the .desktop entry

# extra_index_urls / find_links / exclude: same semantics as iOS/macOS.
```

- `app_id` is the Linux analog of `bundle_id`: it names the `.desktop` file
  (`<app_id>.desktop`), the icon, and the WM_CLASS/wayland app-id.
- `glibc_floor` is the Linux analog of `minimum_system_version`: `None` means the
  runtime's floor (2.17) applies; setting it *higher* (e.g. `"2.28"`) admits
  newer-manylinux-only wheels at the cost of raising the artifact's host floor. Values
  below the runtime floor are the same config-time error macOS raises via
  `floor_error`.
- Extend `Config` with `linux: LinuxConfig | None` + `linux_required`, loader
  validation + tests (mirror the macOS loader tests).

## Step 3 — `pylock.linux.toml`

All shared machinery exists (`lock/wheelruntime/` builder/resolver/serializer + the
triple-agnostic PBS GitHub fetcher). New code is two small modules under
`kivyforge/lock/linux/`:

- **`LinuxProfile(PlatformLockProfile)`** (`profile.py`):
  - `variants`: one `Variant(arch="x86_64", platform_tag=f"manylinux_{floor}_x86_64")`
    where `floor` is `glibc_floor` or `"2_17"` — pip expands the manylinux hierarchy
    downward from it (validated by the Step 1 spike).
  - `wheel_covers`: parse manylinux tag families (`manylinux1/2010/2014`,
    `manylinux_2_y`) → `x86_64` when the arch matches; `musllinux_*` never covers;
    plain `linux_x86_64` per the Step 1 decision. `py3-none-any` handled by the shared
    core as on macOS.
  - `declared_floor`/`floor_error`: glibc-floor wording; `coverage_error` names the
    package and suggests `extra_index_urls`/`find_links` (there is no universal2-style
    escape hatch to suggest on Linux).
- **`LinuxPbsProvider(PbsProvider)`** (`runtime.py`): triples map
  `{"x86_64": "x86_64-unknown-linux-gnu"}` (baseline microarchitecture — not the
  `_v2`/`_v3` variants). Runtime normalization: PBS linux `install_only` archives are
  the same unix-prefix layout as the darwin ones and use `$ORIGIN`-relative rpaths, so
  they are relocatable as-shipped — no patchelf pass; confirm the shared normalization
  applies unchanged. The lock's `[tool.kivyforge]` records provider/version/url/sha256
  exactly as on macOS, and additionally the **effective glibc floor** =
  max(runtime floor, highest locked wheel manylinux level) so `doctor` and docs can
  state the artifact's true host requirement.
- Tests: hermetic profile/provider tests with the fake `MetadataFetcher`; a golden
  `pylock.linux.toml` fixture mirroring the iOS/macOS golden-lock pattern; one live
  PBS resolution exercised at the step boundary (per the established convention).

**Gate:** `kivyforge lock -p linux` produces a correct, reproducible
`pylock.linux.toml` for a Kivy app on the WSL2 host.

## Step 4 — AppDir bundler + `build` / `run`

New `kivyforge/linux/` mirroring `kivyforge/macos/`'s stage decomposition
(`bundle.py`, `runtime_stage.py`, `wheels_stage.py`, `launcher.py`, `desktop.py`,
`icons.py`). **The folder artifact IS an AppDir** — one tree serves `-f folder`,
`-f appimage`, and the dev loop:

```
build/linux/MyApp.AppDir/
├── AppRun                          <- POSIX sh launcher (generated)
├── <app_id>.desktop                <- generated from [project]+[tool.kivy.linux]
├── <app_id>.png                    <- root icon (appimagetool requirement)
└── usr/
    ├── app/                        <- user code ([tool.kivy].app_dir)
    ├── lib/                        <- installed wheels (site-packages)
    ├── python/                     <- PBS runtime (bin/, lib/python3.x/)
    └── share/icons/hicolor/<N>x<N>/apps/<app_id>.png
```

- **`AppRun`** (shell): resolve its own directory via `readlink -f`; export
  `PYTHONHOME=$HERE/usr/python`, `PYTHONPATH=$HERE/usr/app:$HERE/usr/lib`,
  `PYTHONNOUSERSITE=1`, and `SDL_VIDEO_X11_WMCLASS=<app_id>` (plus its Wayland
  analog) so the window's WM_CLASS matches the `.desktop`'s `StartupWMClass`; then
  `exec "$HERE/usr/python/bin/python3" "$HERE/usr/app/<entry_point>.py" "$@"`.
  No `LD_LIBRARY_PATH`: PBS rpaths are `$ORIGIN`-relative and manylinux wheels vendor
  their native libs (auditwheel) — the environment stays clean for the host's own
  libGL.
- **`.desktop` generation:** `Name` from `display_name`, `Exec=AppRun %f`,
  `Icon=<app_id>`, `Categories` from config (default `Utility;`),
  `StartupWMClass=<app_id>`, `Terminal=false`, `Type=Application`. Must pass
  `desktop-file-validate` (also a doctor check, Step 6).
- **Icons:** root `<app_id>.png` + hicolor sizes per the Step 1 decision.
- **Verbs:** `build` assembles the AppDir; `run` executes `./AppRun` directly — the
  fast dev loop needs no AppImage and no FUSE. CLI wiring in `cli/_linux.py`
  following `_macos.py`'s shape; register `LinuxPlatform`
  (`host_system = "Linux"`, `package_formats = ("appimage", "folder")`).
- No signing on Linux — nothing analogous to the macOS ad-hoc floor exists; omit, and
  say so in the spec.

**Gate:** `kivyforge run -p linux` opens the app under WSLg; the AppDir tree passes
unit tests (bundler assembly tests should run on any host — only `run` needs Linux).

## Step 5 — `package -f appimage` / `-f folder`

- **Tool acquisition:** pinned **`appimagetool`** (static build from the maintained
  AppImage/appimagetool releases) + pinned **type2 static-FUSE runtime** file
  (AppImage/type2-runtime releases), both fetched through the existing
  `kivyforge/artifacts` download/cache/sha256-verify machinery. Pins live as
  constants in kivyforge (versioned with kivyforge releases) — they are build tools,
  not app dependencies, so they don't belong in the app's lockfile.
- **Invocation:** `ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 appimagetool
  --runtime-file <type2-runtime> MyApp.AppDir <output>` — `EXTRACT_AND_RUN` so the
  *build host* needs no FUSE either (WSL2/containers/CI just work).
- **Output:** `dist/linux/<Name>-<version>-x86_64.AppImage`, `chmod +x`. `-f folder`
  emits the AppDir itself. Update-embedding/zsync: out of scope.
- Docs: user-facing note on the FUSE story (static runtime = no libfuse2 needed;
  `--appimage-extract-and-run` as the universal fallback) and the host contract
  (glibc ≥ effective floor, libGL/libEGL, X11/Wayland session).

**Gate:** the AppImage runs from a double-click/`./MyApp.AppImage` on WSLg **and**
(recommended, not blocking) on one clean stock-distro VM (e.g. Ubuntu 24.04 or Fedora
under Hyper-V on the same machine) to prove it outside WSL's peculiarities; and via
`--appimage-extract-and-run` to prove the fallback.

## Step 6 — `doctor` checks (Linux)

`kivyforge/doctor/checks_linux.py`, same PASS/WARN/FAIL + remediation-hint framework:

| Check | Scope | Validates |
|-------|-------|-----------|
| Host is Linux (glibc) | environment | Linux host; WARN on a musl host (PBS gnu runtime won't run there). |
| GL libraries present | environment | `libGL.so.1`/`libEGL.so.1` findable (`ldconfig -p`); WARN with the host-contract message + distro package hints. |
| Display session | environment | `DISPLAY`/`WAYLAND_DISPLAY` set; WARN if headless with the `xvfb-run` hint. |
| kivyforge version | environment | (shared check.) |
| App source directory | project | (shared check.) |
| glibc floor vs. runtime | project | `glibc_floor` ≥ the runtime's 2.17 floor; reports the artifact's effective floor from the lock. |
| Architecture coverage | project | Every compiled dep resolves a manylinux x86_64 wheel; FAIL names package. |
| App icon | project | Valid 1024×1024 PNG when set; SKIP if unset. |
| Desktop entry valid | project | Generated `.desktop` passes `desktop-file-validate`; SKIP if the tool isn't installed (it's optional), FAIL on actual validation errors. |
| find_links directories | project | (shared check.) |
| Required hosts reachable | project | Lockfile hosts + the pinned appimagetool/runtime asset hosts. |

Config-time (not doctor): invalid `app_id` (not reverse-DNS-ish / bad chars for a
`.desktop` basename) is a hard `ConfigError`, mirroring the macOS entitlements
fail-fast.

## Step 7 — Examples

- Add `[tool.kivy.linux]` overlays + committed `pylock.linux.toml` to
  `examples/desktop/desktop-viewer`, `dice-roller`, and `notes` — the same apps that
  gained macOS in Phase 3, now demonstrating one `pyproject.toml` → two desktop
  lockfiles. No new example apps this phase; no `examples/wheels/linux/` unless a
  vendored wheel actually becomes necessary.
- `examples/run-examples.sh --platform linux` builds + runs them (WSLg interactively;
  `xvfb-run` path documented for headless).
- Example READMEs get a short Linux section (run, package, host contract).

**Gate:** all three examples lock, build, run, and package to working AppImages on
the WSL2 host.

## Step 8 — Docs sweep + review stop

- README (platform table/status), FAQ (Linux entries: FUSE, WSLg, headless, glibc
  floor), `docs/design/common/06-packaging-scope.md` (Linux row: AppImage primary,
  folder substrate/fallback, `.deb`/`.rpm`/Flatpak external with recommended tools),
  CHANGELOG.
- Master plan: mark Phase 4 complete; carry any realized-vs-designed deltas back into
  `linux-spec.md` as inline implementation notes (the macos-spec precedent).
- **Regression gate:** `pytest` (coverage ≥ 80%) + `ruff` green on **both** macOS and
  Linux hosts; iOS + macOS examples unaffected.
- **Stop for review.**

## Explicitly out of scope / deferred

- **`.deb` / `.rpm` / Flatpak** — external (docs recommend `fpm` /
  `flatpak-builder`); revisit only on a concrete demand signal.
- **Opt-in self-integration** (first-run prompt to install the `.desktop`/icon into
  `~/.local/share/applications/`) — designed in the spec as a fast-follow, not built.
- **aarch64** — config stays list-shaped; needs an ARM verification host first.
- **musl / Alpine** — no dynamic PBS musl runtime, no Kivy musllinux wheels.
- **AppImage update metadata / zsync, signing** — no Linux signing analog in scope.
- **Compiled launcher shim** — not needed; if ever added, build it manylinux2014-class
  so it can't raise the glibc floor.
