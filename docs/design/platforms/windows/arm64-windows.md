# Windows on Arm64 (`win_arm64`) — what it takes

> **Status: not planned / not started.** This is a forward-looking map, written
> so the work is cheap to pick up when demand arrives. No code targets arm64
> today — `amd64` (x86-64) is the only supported Windows arch. Every in-code
> touchpoint carries an `# arm64:` comment that points back here; run
> `rg "# arm64:"` to list them all.

## Why this document exists

Windows on Arm (WoA) is gaining real momentum (Snapdragon X-class laptops, Arm64
Windows VMs). Over the next few years there will likely be demand to ship
**native** arm64 Kivy apps rather than relying on the (already-working) x64
emulation layer. The Windows backend was deliberately built "arch-shaped" — the
config field is a list, the dist folder name already embeds the target arch, the
PE machine-type reader already knows arm64 — so adding `win_arm64` is *additive*,
not a rewrite. This document inventories exactly what changes and in what order.

## What "arm64 support" means here

Produce a **native arm64 onedir bundle**: an arm64 python-build-standalone
CPython prefix + `win_arm64` wheels + an arm64-native launcher `.exe`, running
natively on Arm64 Windows. Running today's `amd64` bundle under WoA's x64
emulation already works and is explicitly **not** what this is about — the goal
is native arm64 for startup/throughput/battery.

## The gating prerequisite (outside kivyforge's control)

**The Kivy wheel ecosystem must publish `win_arm64` wheels.** As of this writing,
`kivy`, `kivy_deps.sdl2`, `kivy_deps.glew`, `kivy_deps.angle`, and
`kivy_deps.gstreamer` publish **`win_amd64` wheels only**. kivyforge locks
reproducibly from pinned wheels (URL + SHA-256), so without upstream `win_arm64`
wheels there is nothing to lock for an arm64 Kivy app — this is the real blocker,
and it is upstream, not here.

- Pure-Python dependencies already ship `py3-none-any` wheels — fine as-is.
- A compiled dependency with no `win_arm64` wheel cannot be locked (the same rule
  as amd64 today; see `coverage_error` in `lock/profile.py`).
- **Action before starting:** confirm the current Kivy release publishes
  `win_arm64` wheels for Kivy + all `kivy_deps.*` the target apps use. Everything
  below is gated on that.

## Change inventory (by area)

Each item corresponds to one or more `# arm64:` code comments.

### 1. Config surface — `kivyforge/config/model.py`, `kivyforge/config/loader.py`

- `VALID_WINDOWS_ARCHS`: add `"arm64"`.
- `DEFAULT_WINDOWS_ARCHS`: **stays `("amd64",)`** — arm64 is opt-in via
  `[tool.kivy.windows].archs`; the default target does not change.
- `loader._parse_windows_archs`: the "only amd64 this phase" / "win-arm64 is
  planned" hint strings are relaxed once the model set includes arm64. The
  list-shape, empty-check, and dedup logic already generalize.

### 2. Wheel platform tag — `kivyforge/platforms/windows/lock/profile.py`

- `_ARCH_TO_TAG`: add `"arm64": "win_arm64"` (`_TAG_TO_ARCH` derives
  automatically).
- `VALID_WHEEL_ARCHS`: add `"arm64"`.
- `wheel_arch` docstring and the `coverage_error` message hardcode `win_amd64`;
  generalize to the per-arch tag.
- `variants()` / `wheel_covers()` are already arch-generic.

### 3. Runtime provider — `kivyforge/platforms/windows/lock/runtime.py`

- `WINDOWS_TRIPLES`: add `"arm64": "aarch64-pc-windows-msvc"`.
- Confirm python-build-standalone publishes `aarch64-pc-windows-msvc`
  `install_only` archives for the pinned CPython (recent PBS releases do). The
  generic `PbsProvider` + asset-glob machinery need no other change; the arm64
  archive normalizes under the same top-level `python/` prefix.

### 4. PE machine-type checks — `kivyforge/platforms/windows/petools.py`

- **Already arm64-ready.** `IMAGE_FILE_MACHINE_ARM64` and
  `_ARCH_MACHINE["arm64"]` exist, so `verify_pe_arch` already validates arm64
  native binaries. No change needed — noted so the next engineer doesn't
  re-derive it.

### 5. The launcher (the largest lift)

Files: `kivyforge/platforms/windows/launcher/build_launcher.py`,
`kivyforge/platforms/windows/launcher/__init__.py`,
`kivyforge/platforms/windows/assets.py`, `kivyforge/platforms/windows/vendor/`.

The launcher is a **prebuilt, vendored, byte-reproducible binary** — one per
arch. `launcher.c` is portable (no arch-specific code), so the source is reused
as-is; the work is producing and wiring a second binary:

- **Vendor a second binary** `launcher-arm64.exe` beside `launcher-amd64.exe`,
  with its own `SHA256SUMS` entry and `pyproject` package-data glob.
- **Build it** with the MSVC **ARM64** toolset. Two routes:
  - *Cross-compile from an x64 host* (recommended for CI simplicity): invoke
    `vcvarsall x64_arm64`, and add
    `Microsoft.VisualStudio.Component.VC.Tools.ARM64` to the `vswhere -requires`
    list (currently only the x86/x64 tools component is required).
  - *Native build on an arm64 runner.*
- **`build_launcher.py`:** `LAUNCHER_NAME` / `VENDORED_LAUNCHER` become
  per-arch; thread arch through `compile_launcher` / `_vcvars_env`; `TOOLSET.txt`
  either per-arch or a shared pin; the `verify` reproducibility gate runs per
  arch. Determinism (`/Brepro` + `/RELEASE` + `/EMITTOOLVERSIONINFO:NO` +
  pinned toolset) is unchanged and arch-independent — the cross-compiled arm64
  output is byte-reproducible on the same terms as amd64.
- **`assets.py` / `launcher/__init__.py`:** `vendored_launcher()` must select
  `launcher-<arch>.exe` by **target** arch; `copy_launcher` / `place_launcher`
  thread the target arch through (today `vendored_launcher()` takes no arch).
- **rcedit:** `rcedit-x64.exe` runs on Arm64 Windows under x64 emulation and only
  edits PE **resources** (icon/version — architecture-agnostic), so **no arm64
  rcedit is needed**; it patches the arm64 launcher fine.

### 6. VC++ runtime staging — `kivyforge/platforms/windows/runtime_stage.py`

- `CORE_VC_RUNTIME` / `CXX_VC_RUNTIME` names are arch-neutral. The
  `System32` / `Sysnative` fallback, however, encodes **x86/x64 WOW64**
  semantics. On Arm64 Windows the redirection model differs (native arm64 DLLs
  in `System32`; the WOW layer is Arm32 `SysArm32`, plus an x64 emulation layer)
  — so `_default_system_dir`'s WOW64 logic does not generalize to arm64.
- The `_copy_from` PE-machine guard already refuses a wrong-arch host DLL (good —
  it prevents poisoning an arm64 bundle with an x64 `msvcp140.dll`).
- **Pinning `msvcp140.dll` is the enabler — do this, not the host fallback.**
  When cross-building an arm64 bundle on an x64 host, the host `System32` has no
  arm64 `msvcp140.dll`, so the host fallback is structurally unusable — it is not
  an edge case, it is the normal cross-build path. The `System32` fallback is a
  convenience that only ever works same-arch; **arm64 support should pin
  `msvcp140.dll` as a real, per-arch, SHA-256-verified artifact** (the same model
  as the PBS runtime and the vendored launcher) and retire reliance on the host
  entirely. This makes the build fully host-independent and reproducible, and it
  is the single change that unblocks cross-arch builds (see §7). Treat it as a
  hard prerequisite for arm64, not a "nice to have" — the previously-deferred
  pinning question is answered here: **pin it.**

### 7. Host / build model — `kivyforge/platforms/windows/__init__.py`

- `check_host_capability` requires a Windows host; the message/docstring say
  "MSVC amd64". Building an arm64 onedir needs **no compilation at build time**
  (runtime + wheels are downloaded per target arch, the launcher is
  prebuilt/vendored, rcedit runs emulated), so an **x64 Windows host can
  cross-build an arm64 bundle** and vice versa.
- **Cross-arch builds should be the supported model — adopt them, don't gate on
  host == target.** Every build-time input is already fetched per target arch or
  vendored; the *only* thing tying a build to the host CPU is the `msvcp140.dll`
  `System32` fallback, and §6 removes that by pinning it as an artifact. Once
  `msvcp140.dll` is pinned and `launcher-arm64.exe` is vendored, `arch` is purely
  a target selector with **no host-CPU dependency**, so `check_host_capability`
  should keep gating on the OS (Windows) only and explicitly *not* require the
  host CPU to match the target. This is the higher-value design: it lets the
  existing x64 CI fleet produce arm64 bundles with no arm64 hardware, and lets
  arm64 hosts produce amd64 bundles — the same "fetch everything per target"
  philosophy the rest of the backend already follows. Requiring host == target
  would be a strictly worse, artificial restriction; do not add it.

### 8. `doctor` — `kivyforge/platforms/windows/doctor.py`

- `check_windows_arch_coverage` and its messages hardcode `win_amd64`;
  generalize to the configured arch(es).
- `check_windows_native_arch` already loops `verify_pe_arch` per configured arch
  — works for arm64 unchanged.
- The host-capability hint text ("MSVC amd64 …") mirrors §7.

### 9. Wheel staging — `kivyforge/platforms/windows/wheels_stage.py`

- Logic is already arch-generic (routes by `wheel_arch(tag)`); only the module
  docstring ("ships one arch (`amd64`)") needs updating. No behavior change.

### 10. CI — `.github/workflows/kivyforge.yml`

- `windows_launcher` (build + reproducibility verify) and `revendor_launcher`
  currently produce only `launcher-amd64.exe`. Extend both to also build /
  verify / vendor `launcher-arm64.exe` — cross-compiling on the same
  `windows-latest` x64 runner via `x64_arm64` (add the ARM64 tools component),
  or add an arm64 runner. A build-arch matrix is the natural shape.

### 11. Tests & examples

- Windows tests pin `archs=("amd64",)` and assert `win_amd64` throughout; add
  arm64 parametrizations once the above lands (the lock/profile, doctor, and
  bundle tests are the main ones).
- Examples default to amd64 implicitly; an app opts into arm64 with
  `[tool.kivy.windows].archs = ["arm64"]` (or `["amd64", "arm64"]`).

## Cross-arch build feasibility

| Build-time step | Host-arch sensitive? |
|---|---|
| Resolve/lock (URL + SHA-256 pins) | No |
| Fetch + extract PBS runtime (per target triple) | No |
| Install `win_arm64` wheels | No |
| Place vendored `launcher-<arch>.exe` | No (just a file copy) |
| `rcedit` resource patch | No (x64 rcedit, emulated; resources only) |
| VC-runtime **host `System32` fallback** | **Yes** — wrong-arch on a cross host (see §6) |

**Conclusion: cross-arch builds are the right model, and they are one change
away.** Every step above is host-arch-independent *except* the `msvcp140.dll`
host fallback — and that step should not exist for arm64 at all. Pin
`msvcp140.dll` as a per-arch artifact (§6) and cross-building becomes fully
supported and reproducible: an x64 runner builds arm64 bundles (and vice versa)
with no arm64 hardware and no host-CPU coupling. Pinning `msvcp140.dll` is not a
mitigation for a caveat — it is **the enabler** that makes the cross-arch build
first-class. Ship arm64 with cross-builds enabled from day one; do not require
host == target.

## Multi-arch output

Windows ships **one arch per onedir** (there is no `universal2` equivalent).
Supporting `archs = ["amd64", "arm64"]` therefore means producing **two** onedir
trees and two `dist/windows/<name>-<version>-<arch>/` folders. The dist path
already embeds `-{target_arch}`, so naming is ready; the build/package verbs
would iterate the configured archs.

## Rollout / phasing

1. **Gate:** upstream Kivy + `kivy_deps.*` `win_arm64` wheels exist.
2. Land the small, pure-data changes: config arch set (§1), wheel tag (§2),
   runtime triple (§3). (petools §4 is already done.)
3. **Pin `msvcp140.dll` as a per-arch, SHA-256-verified artifact and retire the
   host `System32` fallback (§6).** This is a hard prerequisite, not an
   afterthought: it is what makes the build host-independent and unblocks
   cross-arch builds — do it before, not after, wiring the launcher.
4. **The real work:** vendor + reproducibly build `launcher-arm64.exe` and wire
   arch-aware selection (§5) + CI (§10) — with cross-compilation on the existing
   x64 fleet as the intended path (§7), no arm64 hardware required.
5. Generalize `doctor` (§8), add tests, add an example target (§11).

## Non-goals

- **Arm32** (`SysArm32` / `IMAGE_FILE_MACHINE_ARMNT`) and **x86** (`win32`).
- Treating x64-emulated execution of an `amd64` bundle on WoA as a feature — it
  already works; this document is about **native** arm64.
