---
name: Kivyforge Windows backend
overview: Implement the Windows backend from the settled design (docs/design/platforms/windows/{windows-spec,bootloader-windows,signing-windows}.md), updated for the shipped platform-first / native-binary architecture. A run-from-folder onedir bundle — prebuilt windowed-subsystem launcher .exe + a WHOLE PBS python prefix (wheels installed into the prefix by a no-pip wheel-scheme installer, so kivy_deps' share/<dep>/bin DLLs survive) + app source + generated bootstrap + declared native-binaries channel (reusing the shared stage_binaries helper) — riding the shared wheel+runtime lock engine and RuntimeProvider pattern. Sequenced so each testable gate precedes its dependents — prove DLL discovery on a clean VM FIRST, register the platform + lock dispatch before `lock -p windows`, native staging before the native-enabled bundle, unsigned `package -f folder` before signing. Baseline is public Kivy 2.3.1 / SDL2 with a forward-compatible SDL3 path. Ends with Windows doctor checks, an optional first-class Authenticode signing hook (thumbprint-from-cert-store, configurable store scope), example overlays, and docs.
todos:
  - id: phase0-host-runtime-proof
    content: "Phase 0 — Windows host + runtime proof (PROVE FIRST): permanent windows-latest CI, full pytest+ruff green on native Windows; verify (do not reimplement) the %LOCALAPPDATA% cache and NTFS chmod/path behavior; clean-VM spike staging PBS + exact Kivy 2.3.1/SDL2 wheels proving sys.prefix, dep-bin discovery, and window-provider import (SDL3 repeat when a wheel exists); record docs/design/dev/windows-dll-findings.md."
    status: completed
  - id: phase1-config-init-shell
    content: "Phase 1 — Config, init, platform shell: WindowsConfig (schema_version, app_id with Microsoft-only hard AppUserModelID constraints, archs=[amd64], python.version, icons, signing.{thumbprint,timestamp_url,store_scope}, native.binaries), Windows-safe exe/artifact naming, [windows] Pillow extra, render_windows_tables, WindowsPlatform (+status, reject_ios_only_target), registry + cli/lock.py dispatch, clean/upgrade integration, loader tests."
    status: completed
  - id: phase2-lock-profile-runtime
    content: "Phase 2 — Lock profile + runtime provider: WindowsProfile (single win_amd64 tag; kivy_deps.* are ordinary wheels), WindowsPbsProvider (x86_64-pc-windows-msvc), native-binary lock wiring, Windows _LockOps, golden pylock.windows.toml, drift/reproducibility checks, one live PBS resolution at the boundary. Gate: `kivyforge lock -p windows` reproducible."
    status: completed
  - id: phase3-launcher-resource
    content: "Phase 3 — Vendored launcher + resource pipeline: C launcher (wmain/wide-char argv, correct CreateProcessW quoting, GetModuleFileNameW self-location, PYTHONHOME/PYTHONPATH/PYTHONNOUSERSITE, Job object kill-on-close, CREATE_SUSPENDED->assign->resume, exit-code propagation, /SUBSYSTEM:WINDOWS) + deterministic CI rebuild; vendor launcher + rcedit binaries with licenses/SHA-256/package-data; console handoff via AttachConsole(ATTACH_PARENT_PROCESS) else CREATE_NO_WINDOW; real-Windows test matrix."
    status: completed
  - id: phase4-runtime-wheel-staging
    content: "Phase 4 — Runtime + exact-wheel staging: stage the whole PBS prefix; conditional app-local VC runtime per the Phase 0 finding; a Windows-only no-pip wheel-scheme installer routing root + .data/{purelib,platlib}->Lib/site-packages, .data/data->prefix root (so share/<dep>/bin survives), .data/scripts->Scripts, .data/headers->Include; fixtures proving kivy_deps payloads survive and nothing undeclared is installed."
    status: completed
  - id: phase5-onedir-build-run
    content: "Phase 5 — Onedir build + run: atomic assembly (runtime, wheels, app, generated bootstrap, resource-patched launcher) under build/windows/<display_name>; bootstrap sets AppUserModelID, discovers python/share/*/bin generically, registers them + optional bin, retains every add_dll_directory handle, configures PATH, imports entry_point; build + run from arbitrary CWD, no console flash on Explorer launch, diagnostics under `kivyforge run`."
    status: completed
  - id: phase6-native-binaries-pe
    content: "Phase 6 — Native-binary channel + PE checks: thin native_stage.py wrapping shared stage_binaries(); extend the shared helper with target-aware casefold collision keys, Windows reserved-name/ADS rejection, path-separator normalization, and an explicit no-op exec-bit policy on Windows; hermetic PE machine parsing (petools) + post-build amd64 check; validate hello-native DLL + helper exe."
    status: completed
  - id: phase7-unsigned-packaging
    content: "Phase 7 — Unsigned folder packaging: `package -f folder` copies/assembles the distributable under dist/windows/<safe-name>-<version>-amd64/ (build tree preserved, unsigned), with defined replacement/atomicity; the dist copy contains no build cache, VCS, or accidental host files and runs on the clean VM."
    status: completed
  - id: phase8-doctor
    content: "Phase 8 — Doctor: host, long-path, app source, app_id, wheel/runtime coverage, icon, native source/collision/PE-arch, lock hosts, resource assets, signtool, and signing-certificate checks with explicit PASS/WARN/FAIL/SKIP; certificate lookup and signing use the same configured user/machine store; complete fake-probe matrix + a passing native-Windows project check."
    status: completed
  - id: phase9-signing
    content: "Phase 9 — Authenticode signing: Signer protocol (new, windows-only) + SigntoolSigner (/sha1 thumbprint /fd SHA256 /tr <ts> /td SHA256, /sm for machine store) + NullSigner; sign the already resource-patched launcher in the dist copy only; PEP 440 string metadata + deterministic four-part numeric file-version mapping; self-signed sign/verify on Windows CI; payload PE signing deferred + documented."
    status: completed
  - id: phase10-examples-docs
    content: "Phase 10 — Examples, verification, docs: Windows overlays on the desktop examples (no committed lockfiles) + a PowerShell verifier (clean/lock/doctor/build/run/package/launch); Kivy 2.3.1 baseline with a conditional SDL3 smoke; promote 08-native-binaries-channel.md to the authoritative shared reference (strike completed items); update README/FAQ/CHANGELOG/packaging-scope/platform-architecture/Windows specs + realized-vs-designed notes. Final gate: tests+lint green on Windows/Linux/macOS; verifier passes on a clean VM. Stop for review."
    status: completed
isProject: false
---

# Kivyforge Windows Backend

Implementation plan for the Windows backend. The design is settled in three
companion specs; this plan sequences the build against them and against the
**shipped** platform-first / native-binary architecture (macOS *and* Linux are
now implemented, and the shared native-staging helper already exists), and it
records the decisions and gates that the earlier draft left open or stale.

- [windows-spec.md](../../docs/design/platforms/windows/windows-spec.md) —
  scope, overlay, runtime, lockfile, onedir layout + the DLL-discovery
  invariant, bootstrap module, native-binaries channel, doctor table, module
  layout, open items.
- [bootloader-windows.md](../../docs/design/platforms/windows/bootloader-windows.md)
  — the prebuilt launcher `.exe`.
- [signing-windows.md](../../docs/design/platforms/windows/signing-windows.md)
  — the optional Authenticode hook.

Windows is the **third and final desktop backend**, the sibling of the shipped
macOS and Linux backends on the shared `lock/wheelruntime/` engine +
`RuntimeProvider`, consolidated under `kivyforge/platforms/windows/`. Reuse the
shipped macOS/Linux backends as the template for every seam (config overlay,
profile + provider, bundler stage decomposition, doctor, `init` renderer,
examples, `Platform` registration, the shared
`artifacts/native_stage_util.stage_binaries()` helper).

## Settled decisions (previously open items)

These close the draft plan's open items and the specs' contradictions:

- **Kivy baseline:** support public **Kivy 2.3.1 / SDL2** now (`kivy_deps.sdl2`,
  `kivy_deps.glew`, and the GL story that 2.3.1 actually uses on Windows). Keep
  wheel staging and bootstrap **generic over `share/*/bin`** — never hard-code
  `share/sdl3/bin`. Add a Kivy 3 / SDL3 Windows smoke test when a public wheel
  exists. (Kivy 3.0 has no public desktop wheels today, so the clean-VM proof in
  Phase 0 is against 2.3.1/SDL2; SDL3 is forward-compat.)
- **Wheel staging:** a **Windows-only** deterministic wheel-scheme installer,
  **no `pip`, no dependency resolution, no host interpreter**. It routes every
  standard wheel scheme into the bundled prefix: package root + `.data/{purelib,
  platlib}` → `Lib/site-packages`, `.data/data` → the **prefix root** (so
  `share/<dep>/bin` survives — this, not "pip is load-bearing", is the real
  invariant), `.data/scripts` → `Scripts`, `.data/headers` → `Include`. The
  shipped macOS/Linux `_unpack` is left untouched (a generalized unpack was
  rejected: `.data/data`→prefix has no target in their `lib`-on-`PYTHONPATH`
  layout).
- **Launcher + resource editor:** **vendor** the audited amd64 launcher and the
  **`rcedit`** resource editor, each with its license/notice, a pinned SHA-256,
  and explicit package-data entries. The launcher C source lives in-repo and CI
  **rebuilds it deterministically** to verify the vendored binary. `rcedit` is
  Windows-only, so the resource-patch step is exercised on `windows-latest`.
- **Build vs package (build/dist split):** `build` creates the unsigned runnable
  tree under `build/windows/<display_name>` — the churny iterative `run`-in-place
  dev target, never mutated by signing. `package -f folder` copies/assembles the
  distributable under `dist/windows/<safe-name>-<version>-amd64/` and signs only
  that copy when configured. Rationale (sharper than "hygiene"): unlike macOS
  (atomic signed `.app` in `build/` is the terminal unit; `.dmg` external) and
  Linux (kivyforge internalizes the AppImage into `dist/`; the AppDir is an
  exposed build substrate), the Windows onedir tree is *both* the dev-run target
  and a first-class shipped deliverable — the raw folder is a mainstream end-user
  format (portable/zip, no installer) and the feedstock for the external Inno
  step. Installers stay permanently external, exactly like the macOS `.dmg`.
  Separating the two isolates two genuinely different artifacts.
- **`app_id` validation:** hard-fail only on Microsoft's **real** AppUserModelID
  constraints — **no spaces, ≤128 characters**. Pascal-case / period-delimited
  form is a **doctor WARNING**, not a config-time hard error; hyphens are
  allowed. This is a *different* identifier from the Linux reverse-DNS `app_id`
  and the macOS `bundle_id`, so the validation does not "mirror" theirs.
- **Signing store scope:** default `CurrentUser\My`; an explicit
  `store_scope` setting selects `LocalMachine\My` so `signtool` (`/sm`) and the
  doctor certificate check inspect the **same** store.

## Non-negotiable sequencing

Ordered so each testable gate precedes everything that depends on it — the
draft plan's biggest defect was gates that referenced not-yet-built pieces:

1. **Prove DLL discovery on a clean VM (Phase 0).** A perfect launcher that
   starts an interpreter which can't `import kivy` looks *exactly* like a
   launcher bug. The clean-VM window-provider import is the green light.
2. **Register the platform + lock dispatch (Phase 1) before `lock -p windows`
   (Phase 2).** `resolve_target` and `cli/lock.py` must know `windows` first.
3. **Native staging (Phase 6) before a native-enabled bundle gate.** The plain
   bundle (Phase 5) needs no native channel; the native gate does.
4. **Unsigned `package -f folder` (Phase 7) before signing (Phase 9).** Signing
   operates on the dist copy the packaging phase produces.

Config + lock (Phases 1–2) are independent of the VM spike and can proceed in
parallel with Phase 0's host bring-up, but **no bundler/launcher code starts
until the spike passes.**

## Phase 0 — Windows host + runtime proof (PROVE FIRST)

Two parts. First, make the core correct on a Windows host:

- Dev env on Windows amd64: clone, venv, editable install. **Full `pytest` +
  `ruff` green on Windows.** Expected friction:
  - **Artifacts cache path:** the per-OS cache-dir selection already resolves
    `%LOCALAPPDATA%\kivyforge\Cache\artifacts` (`artifacts/cache.py`) — **verify
    and test it on Windows, do not reimplement it.**
  - **NTFS `chmod` / exec-bit no-ops** (the shared `_make_executable` sets exec
    bits that are meaningless on NTFS — confirm it does not fail there), and
    **path handling** (`PurePosixPath` vs `Path` where lock URLs and staged
    relpaths are compared; target-Windows path assembly).
  - Any test assuming POSIX host tools must skip cleanly on Windows.
- **CI:** add a permanent `windows-latest` job (headless `pytest` — unit tests
  need no GL). Cross-platform regression coverage from here on.

Then the **spike that gates the whole backend** — on a **clean VM (no Python,
no VCRedist)**:

```
python\python.exe -c "import sys; print(sys.prefix)"
python\python.exe -c "import kivy_deps.sdl2 as d; print(d.dep_bins)"
python\python.exe -c "import kivy; from kivy.core.window import Window; print(Window)"
```

Manually assemble the minimal tree (relocate a PBS `x86_64-pc-windows-msvc`
`install_only` prefix; stage the exact **Kivy 2.3.1** wheel set so
`share/sdl2/bin` is populated), set `PYTHONHOME`, and run the chain. **Command 3
passing is the green light.** On failure use `Dependencies.exe` /
`dumpbin /dependents` on the failing `.pyd` / `SDL2.dll` — do not guess. Repeat
against Kivy 3 / SDL3 when a public Windows wheel exists.

Record findings in **`docs/design/dev/windows-dll-findings.md`** (the
`resolver-findings.md` pattern):

- Does PBS bundle `vcruntime140.dll` / `vcruntime140_1.dll` / `msvcp140.dll`
  next to `python.exe`? If not, Phase 4 places them app-local (a concrete
  bundler task, not a note).
- The GL backend Kivy 2.3.1 uses on Windows (ANGLE vs desktop GL) and its dep
  packages. Verify — do not assume.
- PBS wheel `.data` layout, runtime symlink/extraction behavior, and whether
  PBS's `python.exe` / `python3xx.dll` are Authenticode-signed (v2 payload
  sweep only).

**Gate (CI):** `pytest` + `ruff` green on `windows-latest`.
**Gate (manual clean VM):** command 3 passes with no Python/VCRedist present;
findings doc written. **Nothing below starts before this gate.**

## Phase 1 — Config, `init`, and the platform shell

Additive overlay on the shared `[project]` + `[tool.kivy]`, mirroring
`MacosConfig`/`LinuxConfig`:

- **`WindowsConfig`** (`config/model.py`): `schema_version` (int, required);
  `app_id` (**AppUserModelID; hard `ConfigError` only on no-spaces / ≤128-char
  violations** — style is a doctor warning, hyphens allowed); `archs` (default
  `["amd64"]`, only `amd64` this phase, list-shaped); `extra_index_urls` /
  `find_links` / `exclude`; `python_version`. Add
  `SUPPORTED_WINDOWS_SCHEMA_VERSION`, `VALID_WINDOWS_ARCHS = {"amd64"}`,
  `DEFAULT_WINDOWS_ARCHS = ("amd64",)`.
- **`[tool.kivy.windows.icons].source`** — 1024×1024 PNG → multi-size `.ico`
  (Pillow, the same opt-in `[windows]` extra as Linux icons; add it to
  `pyproject.toml`).
- **`[tool.kivy.windows.signing]`** — optional `WindowsSigningConfig`:
  `thumbprint` (+ `timestamp_url` default `http://timestamp.digicert.com`) and
  **`store_scope`** (`current_user` default | `machine`), with a `configured`
  property (`bool(thumbprint)`), paralleling `MacosSigningConfig`.
- **`[tool.kivy.windows.native.binaries]`** — reuse the shared
  `_parse_native_binaries(windows, "windows", finder)` + `NativeBinaryDep`
  (already platform-agnostic).
- **Windows-safe naming:** derive the launcher name and the packaged folder name
  from `display_name` through a sanitizer (strip/replace characters illegal in
  Windows filenames, reserved device names, trailing dots/spaces) — a pure
  helper with a test matrix.
- Extend `Config` with `windows: WindowsConfig | None` + a `windows_required`
  accessor + `require_windows` in `load_config`.
- **Platform shell:** `render_windows_tables` (in `cli/init_writer.py`),
  `WindowsPlatform` (`host_system = "Windows"`, `package_formats = ("folder",)`,
  the `reject_ios_only_target` guard, the `status` verb locating
  `build/windows/<display_name>` and reporting lock sync, lazy verb imports),
  registered in `platforms/__init__.py`; add the `windows` `_LockOps` branch in
  `cli/lock.py`; wire `clean`/`upgrade`; Windows-aware desktop error text.
- Tests (`tests/config/test_loader.py`): overlay parse; `app_id` valid/invalid
  matrix (spaces + length hard-fail; style variants accepted); `archs`
  validation; signing table parse incl. `store_scope`; native-binaries source
  rules; the name-sanitizer matrix.

**Gate:** `init -p windows`, host inference, and config/platform tests pass end
to end.

## Phase 2 — `pylock.windows.toml` (lock profile + runtime provider)

Simplest of the desktop family — a single stable `win_amd64` tag. Two small
modules under `kivyforge/platforms/windows/lock/` on the shared engine:

- **`WindowsProfile(PlatformLockProfile)`** (`profile.py`): one
  `Variant(arch="amd64", platform_tag="win_amd64")`; `wheel_covers` `win_amd64`
  → `amd64` (`py3-none-any` handled by the shared core). **`kivy_deps.*` are
  ordinary wheels** — Kivy's `win_amd64` wheel declares them as conditional
  deps, so they flow through `[[packages]]` with URL+SHA-256 pins; no
  special-casing. `coverage_error` names the missing package + suggests
  `extra_index_urls` / `find_links`.
- **`WindowsPbsProvider(PbsProvider)`** (`runtime.py`): triple map
  `{"amd64": "x86_64-pc-windows-msvc"}` — a one-line specialization, as Linux
  was. Confirm the shared runtime normalization applies to the Windows
  `install_only` archive **without** flattening/pruning/`._pth`-isolating it
  (the normal prefix layout is load-bearing).
- Wire `native_binaries=config.windows.binaries` through
  `build_windows_lockfile` into `build_wheel_runtime_lock` (shared; done).
- `platforms/windows/lock/__init__.py` re-exports the engine under
  Windows-friendly names, mirroring Linux.
- Tests: hermetic profile/provider tests with the fake `MetadataFetcher`; a
  golden `pylock.windows.toml` fixture (incl. a `kivy_deps.sdl2` package and a
  `[[tool.kivyforge.native_binaries]]` entry); drift/reproducibility check; one
  live PBS resolution at the boundary.

**Gate:** `kivyforge lock -p windows` is reproducible and pins the runtime,
wheels, and declared native artifacts.

## Phase 3 — the vendored launcher `.exe` + resource pipeline

Per [bootloader-windows.md](../../docs/design/platforms/windows/bootloader-windows.md).
**Compiled once in CI, never on user machines.** C source + CI workflow in-repo.

- **Source (`platforms/windows/launcher/` C):** `wmain` / `GetCommandLineW` +
  `CommandLineToArgvW` (wide-char argv throughout); a **correct Windows argv
  quoting algorithm** when reassembling the child command line (backslash /
  quote handling — the documented `CommandLineToArgvW`-inverse, not naive
  double-quoting); `GetModuleFileNameW` self-location looping on
  `ERROR_INSUFFICIENT_BUFFER` (no fixed `MAX_PATH`); derive the bundle layout
  from the launcher's own location (never trust CWD); a **Unicode environment
  block** with `PYTHONHOME=<bundle>\python`, `PYTHONPATH=<bundle>\app`,
  `PYTHONNOUSERSITE=1`; `CreateProcessW` the child
  (`python\python.exe <bundle>\_kivyforge_bootstrap.py <argv...>`) with
  **`CREATE_SUSPENDED`**, assign it to a **Job object** (kill-on-job-close),
  **then resume** (so no grandchild escapes the job); `WaitForSingleObject` →
  `GetExitCodeProcess` → **exit with the child's code**; reliable handle
  cleanup on every path. Link **`/SUBSYSTEM:WINDOWS`**. Spawn-and-wait, not
  `exec`.
- **Console handoff (the subsystem-boundary detail the spec under-specified):**
  attempt `AttachConsole(ATTACH_PARENT_PROCESS)`. When attached (the
  `kivyforge run` path from a terminal), explicitly **inherit stdin/stdout/
  stderr** so the child's output and tracebacks reach the terminal. When
  double-clicked (no parent console), launch the console-subsystem `python.exe`
  with **`CREATE_NO_WINDOW`** to prevent a console flash. (Record why
  `pythonw.exe` is not the double-click path: it forfeits the
  attach-for-diagnostics story on the `run` path.)
- **Deterministic CI rebuild + vendoring:** compile per-arch (amd64 only this
  phase); CI **rebuilds and byte-compares** to the vendored binary (no appended
  zip / timestamp — kivyforge's launcher appends nothing). Vendor the launcher
  and **`rcedit`**, each with license/notice, pinned SHA-256, and package-data
  entries.
- **Resource patching (`rcedit`):** patch the per-app icon (from
  `[tool.kivy.windows.icons]`) and the version resource (from `[project]` /
  `[tool.kivy]`) into a per-app copy of the launcher. Patching happens **before**
  signing (Phase 9 guarantees the order). Confirm distlib/`simple_launcher`
  license terms if any *design* is borrowed (no code/binary is vendored from it;
  the launcher is our own source).
- **Test matrix (real Windows host):** spaces, non-ASCII, deep trees near/over
  260 chars (with/without `LongPathsEnabled`), launch from a shortcut with
  blank/arbitrary CWD, **forwarded quoted arguments** round-trip, visible run
  output/tracebacks, exit-code propagation, Ctrl-C, process-tree teardown (no
  orphaned `python.exe`), and **no console flash on Explorer launch**.

**Gate (Windows host):** the launcher spawns the bundled interpreter, forwards
argv correctly, surfaces diagnostics under `run`, propagates exit codes, and
tears down cleanly across the full matrix with no console flash.

## Phase 4 — runtime + exact-wheel staging

New bundler modules under `kivyforge/platforms/windows/`, mirroring the
macOS/Linux stage decomposition:

- **`runtime_stage.py`:** stage the PBS prefix **whole** into `python\` — do not
  flatten/prune. **If the Phase 0 finding shows PBS omits the VC runtime, place
  `vcruntime140*.dll` / `msvcp140.dll` app-local next to `python.exe`** (an
  explicit conditional step driven by the recorded finding).
- **`wheels_stage.py` — the Windows-only no-pip installer:** fetch + hash-check
  each locked wheel and install its schemes into the bundled prefix: package
  root + `.data/{purelib,platlib}` → `Lib/site-packages`, `.data/data` → the
  **prefix root** (so `share/<dep>/bin` lands at `<prefix>/share/<dep>/bin` and
  survives — a site-packages-only copy silently drops every SDL DLL and Kivy
  dies importing the window provider), `.data/scripts` → `Scripts`,
  `.data/headers` → `Include`. **Never** resolve dependencies, use host `pip`,
  or apply the host interpreter's compatibility rules. Leave the shipped
  macOS/Linux `_unpack` untouched. Document that this is the real DLL-discovery
  invariant (not "pip is load-bearing").
- Tests: a fixture proving `kivy_deps` payloads survive under
  `python/share/<dep>/bin` (SDL2 today, SDL3 forward-compat) and that **no
  undeclared / network artifact** is installed; scheme-routing unit tests
  (host-agnostic, with a fake wheel).

**Gate (CI, host-agnostic):** the staged prefix has the expected
`share/<dep>/bin` tree from fixtures.
**Gate (manual clean VM):** a fully offline staged prefix imports Kivy and opens
its window provider.

## Phase 5 — onedir `build` + `run`

Layout (windows-spec), assembled atomically (stage into a temp tree, then
promote) so a partial build never leaves a half-written `build/windows`:

```
build/windows/MyApp/
├── MyApp.exe                 ← prebuilt launcher, resource-patched per app
├── _kivyforge_bootstrap.py   ← generated (fixed name)
├── app/                      ← user code ([tool.kivy].app_dir)
├── bin/                      ← declared native binaries (Phase 6); absent when empty
└── python/                   ← WHOLE PBS prefix (Lib/site-packages, share/<dep>/bin, ...)
```

- **`launcher.py`:** generate `_kivyforge_bootstrap.py` (fixed name) that:
  1. sets the explicit AppUserModelID (`app_id`) via
     `SetCurrentProcessExplicitAppUserModelID` (ctypes) **before** any window;
  2. **discovers `python/share/*/bin` generically** (not `sdl3`-hard-coded),
     registers each with `os.add_dll_directory` **before** `import kivy`
     (defense-in-depth; the prefix layout is the real fix);
  3. when `<bundle>\bin` exists: registers it with `os.add_dll_directory` +
     PATH-prepends it (Phase 6);
  4. **retains every `os.add_dll_directory()` handle for the process lifetime**
     (the handles remove the directory when closed/GC'd — keep references);
  5. puts `<bundle>\app` on `sys.path`, sets CWD to it, imports
     `[tool.kivy].entry_point` (import-not-run-as-`__main__`).
  Then place the launcher as `<safe-name>.exe` and resource-patch it via
  `rcedit`.
- **`icons.py`:** 1024×1024 PNG → multi-size `.ico` (256/48/32/16) via Pillow.
- **Verbs (`cli.py`):** `build` (resolve if needed → runtime stage → wheel-scheme
  install → app copy → native-binaries stage → bootstrap gen → launcher place +
  patch, all atomic); `run` (build unless `--no-build`, then launch the `.exe`
  so the dev sees stdout/stderr + tracebacks via the Phase 3 console handoff).
- Tests: host-agnostic assembly unit tests (tree shape, bootstrap contents,
  launcher placement, atomic-promote) with a fake runtime/wheel; an interactive
  smoke on Windows.

**Gate (manual Windows host):** `build` and `run` work for a simple Kivy app
from arbitrary CWD, no console flash on Explorer launch, full diagnostics under
`kivyforge run`.

## Phase 6 — the `[tool.kivy.windows.native.binaries]` channel + PE checks

Reuses the shared config/lock machinery (Phases 1–2 pin it) and the shipped
shared staging helper. New: a thin wrapper, Windows-specific guards, and a PE
arch check.

- **`native_stage.py`:** a thin wrapper over
  `artifacts/native_stage_util.stage_binaries()` (already used by macOS + Linux;
  Windows is the third consumer), supplying `bin_label = "bin"` and translating
  `NativeStageError` into the Windows bundle-error type. **Extend the shared
  helper** (not Windows-only forks) with:
  - **target-aware casefold collision keys** — on a case-insensitive target,
    `SDK.dll` and `sdk.dll` collide at the filesystem and must be caught by
    `_claim` (today `_claim` keys on the case-sensitive posix path);
  - **Windows reserved-name / ADS rejection** — reject members named `CON`,
    `PRN`, `AUX`, `NUL`, `COM1..9`, `LPT1..9`, and any path containing `:`
    (alternate data streams) or a trailing dot/space;
  - **path-separator normalization** for archive members;
  - an **explicit exec-bit policy** — `_make_executable` is a documented no-op
    on Windows (NTFS has no POSIX exec bit) and must not fail there.
  Reuse all the shared fetch/hash/`_safe_extract`/tar-`filter="data"` guards;
  support the archive formats the helper actually supports (`.zip`, `.tar.gz`,
  `.tgz`) and align the macOS/Linux/Windows docs to that set.
- **Bootstrap:** covered in Phase 5 item 3/4 — `bin\` registered + PATH-prepended
  before the app imports, so user code loads by name (`ctypes.WinDLL("sdk.dll")`,
  `subprocess.run(["ffmpeg"])`).
- **PE arch check (`petools.py`):** a tiny hermetic reader of the COFF header
  `Machine` field (`IMAGE_FILE_MACHINE_AMD64 = 0x8664`) via the PE signature
  offset at `0x3C` — pure-Python (the PE analog of Linux `elftools` / macOS
  `machotools`), so it works on any host and in unit tests. A post-build doctor
  check fails an x86 DLL in an amd64 app clearly.
- Tests: single-file staging (basename preserved); `.zip` / `.tar.gz`
  extraction; hash mismatch; missing vendored source; **case-only collision**;
  reserved-name / ADS rejection; PE machine-type PASS / wrong-arch FAIL;
  bootstrap contains the `bin\` registration only when the table is non-empty.

**Gate:** a declared DLL and helper `.exe` load and run by name from the built
bundle; case-only collisions and wrong-arch PE files fail clearly.

## Phase 7 — unsigned folder packaging

- **`package -f folder`:** copy/assemble the `build/windows/<display_name>` tree
  into `dist/windows/<safe-name>-<version>-amd64/`. Define replacement /
  atomicity (write to a temp sibling, then swap; a failed package never leaves a
  partial dist dir), and **preserve** the build tree (it stays the unsigned
  dev-run target). The copy excludes build cache, `.git`/VCS, editor droppings,
  and anything not part of the four canonical subtrees.
- Tests: the dist copy contains exactly the bundle tree (assert an allowlist);
  replacement over an existing dist dir; no build/VCS/host files leak.

**Gate (manual clean VM):** the dist copy runs on the clean VM and contains no
build cache, source-control, or accidental host files.

## Phase 8 — `doctor` checks (Windows)

`platforms/windows/doctor.py`, reusing `doctor/checks_common.py`, per the
windows-spec doctor table (explicit PASS/WARN/FAIL/SKIP; exit non-zero only on
FAIL):

- **Host is Windows**; **Long-path support** (WARN if `LongPathsEnabled` off);
  **kivyforge version**; **App source directory**; **`app_id`** (FAIL on the
  Microsoft hard constraints; **WARN** on style — pascal-case/period form);
  **Architecture coverage** (every compiled dep resolves a `win_amd64` wheel);
  **App icon** (valid 1024×1024 PNG when set, else SKIP); **Native binaries:
  sources** (each `source` exists / reachable; SKIP when empty); **Native
  binaries: collision** (casefold + reserved-name preflight); **Native binaries:
  arch** (Phase 6 PE check; SKIP when empty/unbuilt); **Lock hosts reachable**
  (PBS + wheel indexes + native-binary URLs + the timestamp server when signing
  is configured); **Resource assets** (icon/version inputs present for the
  patch); **signtool available** (SKIP unless signing configured; FAIL when
  configured but missing); **Signing certificate** (when configured, exactly one
  code-signing cert matches the thumbprint **in the configured `store_scope`
  store** — the same store `signtool` will use; SKIP unconfigured); **find_links
  directories**.
- Tests: each check's PASS/WARN/FAIL/SKIP paths, probe-faked for
  host/registry/signtool/store/reachability, paralleling
  `tests/platforms/linux/test_doctor.py`; plus a passing native-Windows project
  check.

**Gate:** complete fake-probe matrix passes; certificate lookup and signing
target the same configured store; a real Windows project passes `doctor`.

## Phase 9 — Authenticode signing hook

Per [signing-windows.md](../../docs/design/platforms/windows/signing-windows.md).
**v1 ships kivyforge's own binaries + the default artifact UNSIGNED, but the
hook is first-class + optional from day one.**

- **`platforms/windows/signing.py`:** introduce the **`Signer` protocol**
  (`sign(paths) -> None`) — **new to the codebase, Windows-only**, not
  retrofitted onto macOS/iOS. Backends: `SigntoolSigner` (default when
  configured — `signtool sign /sha1 <thumbprint> /fd SHA256 /tr <timestamp_url>
  /td SHA256`, adding **`/sm`** when `store_scope = machine`, always timestamped)
  and `NullSigner` (unconfigured default → unsigned artifact). A future
  `ArtifactSigningSigner` slots behind the same protocol.
- **Identity = thumbprint-from-cert-store** in the configured `store_scope`,
  never a `.pfx` path/password.
- **What/when signed:** `package -f folder` with signing configured →
  resource-patch the launcher (Phase 3) → sign the launcher `.exe` **in the
  `dist/windows` copy only** (the build tree stays unsigned). Payload DLLs/`.pyd`s
  **deferred to v2** and documented. Constraints: patch-before-sign,
  sign-before-any-external-installer.
- **Version metadata:** define the PEP 440 → version-resource mapping — the
  string fields (ProductVersion / ProductName / copyright) carry the PEP 440
  string; the numeric `FILEVERSION`/`PRODUCTVERSION` need a **deterministic
  four-part numeric** derivation (e.g. `epoch?.major.minor.micro` with
  pre/post/dev folded to the fourth field by a documented rule), since Windows
  version resources are four 16-bit integers.
- **Dev/CI:** self-signed cert (`New-SelfSignedCertificate -Type
  CodeSigningCert`); `signtool verify /pa` needs the public `.cer` imported to
  `Cert:\LocalMachine\Root` on the test box (CI does this). No secrets.
- Tests: config-parse → signer selection; exact `signtool` command + `/sm`
  selection per `store_scope`; patch-before-sign ordering; the self-signed
  sign→verify loop on Windows CI; `NullSigner` leaves the artifact unsigned.

**Gate:** a configured (self-signed) `package -f folder` produces a signed,
timestamped launcher in the dist copy that passes `signtool verify /pa` in CI;
unconfigured packaging remains unsigned.

## Phase 10 — examples, verification, and docs (review stop)

- **Examples:** add `[tool.kivy.windows]` overlays to the current desktop
  examples (`desktop-viewer`, `dice-roller`, `notes`) and a
  `[tool.kivy.windows]` + `native.binaries` overlay on
  `examples/desktop/hello-native` (a `.dll` loaded by name + a helper `.exe` run
  by name). **Do not commit generated lockfiles** (match current example
  guidance — examples no longer commit `pylock.*`). Extend
  `hello-native/build_native.sh` with a Windows branch (MSVC/clang-cl or mingw),
  or document producing the Windows artifacts — record the chosen toolchain.
- **Verifier:** a PowerShell sibling (`verify-windows-examples.ps1`) matching the
  desktop verifier's lifecycle: `clean → lock → doctor → build → run →
  package → launch`.
- **Kivy baseline in examples:** Kivy 2.3.1 as the available v1 baseline; retain
  a conditional Kivy 3 / SDL3 compatibility smoke.
- **Shared docs:** promote
  [`08-native-binaries-channel.md`](../../docs/design/common/08-native-binaries-channel.md)
  to the authoritative shared reference (strike the **already-completed**
  "extract shared staging helpers" item — `native_stage_util.py` exists — flip
  the Linux/Windows status banners, reduce platform specs to genuine
  divergences); update
  [`05-platform-architecture.md`](../../docs/design/common/05-platform-architecture.md)
  so Linux is no longer "later" (it is shipped) and Windows is the remaining one.
- **Docs:** README (platform table → Windows implemented), FAQ (SmartScreen wall,
  long paths, VC runtime, GL backend), `06-packaging-scope.md` (Windows row
  correct), CHANGELOG. **Fold the spike findings + realized-vs-designed deltas
  back into the three Windows specs** (flip their "implementation not started"
  banners) and finalize `windows-dll-findings.md`.
- **Regression gate:** `pytest` (coverage ≥ 80%) + `ruff` green on **Windows,
  macOS, and Linux**; iOS/macOS/Linux examples unaffected.

**Final gate:** tests + lint pass on Windows, Linux, and macOS; the Windows
verifier passes on a clean VM. **Stop for review.**

## Explicitly out of scope / deferred (from the spec)

- **Console-subsystem apps** — windowed-only, fixed at link time.
- **onefile** — rejected permanently (extract-to-`%TEMP%`, unsignable embedded
  payload); onedir keeps every file real + signable.
- **Installers** (Inno/NSIS/WiX/MSI/MSIX) — permanently external; kivyforge
  stops at the signed onedir. No in-scope single-file distributable on Windows
  (unlike Linux's AppImage). Store commerce needs MSIX package identity →
  structurally downstream, no hook.
- **Auto-update frameworks** (Squirrel/Velopack, WinSparkle) — external;
  WinSparkle-as-a-DLL can ride the native-binaries channel.
- **win-arm64** — deferred pending demand + Kivy/SDL arm64 wheels + PBS arm64
  Windows builds; config stays list-shaped (additive).
- **Payload-DLL signing / PBS-binary re-signing** — v2, Smart App Control only;
  kept possible by onedir.
- **Azure Artifact Signing** — the path if/when kivyforge signs its *own*
  releases; deferred.
