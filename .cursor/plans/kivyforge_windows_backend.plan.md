---
name: Kivyforge Windows backend
overview: Implement the Windows backend from the already-settled design (docs/design/platforms/windows/{windows-spec,bootloader-windows,signing-windows}.md). A run-from-folder onedir bundle — prebuilt windowed-subsystem launcher .exe + a WHOLE PBS python prefix (prefix-installed wheels, so kivy_deps.sdl3's share\sdl3\bin DLLs survive) + app source + generated bootstrap module + declared native-binaries channel — riding the shared wheel+runtime lock engine and RuntimeProvider pattern. Sequenced per the spec: prove DLL discovery on a clean VM FIRST, then the bootloader, then signing. Ends with a first-class optional Authenticode signing hook (thumbprint-from-cert-store), Windows doctor checks, example overlays, and docs.
todos:
  - id: step0-host-and-spike
    content: "Step 0: Windows host bring-up + DLL-discovery spike (PROVE FIRST). Dev env on Windows amd64, full pytest+ruff green on a Windows host (flush out POSIX assumptions: cache dir %LOCALAPPDATA%, path separators, exec-bit no-ops). Then the clean-VM spike: relocate a PBS prefix, prefix-install Kivy, and prove `import kivy` + `from kivy.core.window import Window` on a VM with no Python/VCRedist. Record docs/design/dev/windows-dll-findings.md (VC-runtime bundling, GL backend, layout surprises). Add a windows-latest CI job."
    status: pending
  - id: step1-config
    content: "Step 1: [tool.kivy.windows] overlay + WindowsConfig — schema_version, app_id (AppUserModelID validation, hard ConfigError), archs=[amd64], python.version, icons, signing.thumbprint (+timestamp_url), native.binaries; extend Config with windows/windows_required; loader tests (incl. app_id validity + native-binary source rules via the shared parser)."
    status: pending
  - id: step2-lock
    content: "Step 2: pylock.windows.toml — WindowsProfile (win_amd64 single-tag coverage; kivy_deps.* are ordinary wheels) + WindowsPbsProvider (x86_64-pc-windows-msvc triple map) on the shared engine; wire native_binaries through build_windows_lockfile; golden-lock + profile/provider tests + one live PBS resolution at the step boundary."
    status: pending
  - id: step3-bootloader
    content: "Step 3: the prebuilt launcher .exe — C source (wmain, wide-char argv, GetModuleFileNameW self-location, CreateProcessW + Job object kill-on-close + WaitForSingleObject + exit-code propagation, PYTHONHOME/PYTHONPATH/PYTHONNOUSERSITE env, /SUBSYSTEM:WINDOWS) + CI build workflow (per-arch). Decide binary distribution (pinned release asset vs vendored) and the resource-patcher (rcedit vs pefile). Launcher test matrix on a real Windows host (spaces/unicode/deep paths/shortcut CWD/exit code/process-tree)."
    status: pending
  - id: step4-bundle
    content: "Step 4: onedir bundler + build/run — runtime_stage (WHOLE prefix), wheels_stage (pip install --prefix <bundle>\\python — the load-bearing divergence), app copy, generated _kivyforge_bootstrap.py (AppUserModelID, add_dll_directory for share\\sdl3\\bin + bin\\, sys.path/app cwd, import entry_point), launcher placement + per-app resource patch. `build`; `run` (launch MyApp.exe foreground, child inherits console). Bundler assembly unit tests (host-agnostic) + interactive smoke on Windows."
    status: pending
  - id: step5-native-binaries
    content: "Step 5: [tool.kivy.windows.native.binaries] channel — native_stage into <bundle>\\bin (single file as-is / .zip extracted, path-traversal + collision guards); bootstrap registers bin\\ via os.add_dll_directory + PATH prepend; doctor PE machine-type check (x86 DLL in amd64 app). Reuse shared staging helpers; PE-header reader (petools). Tests incl. collision + arch cases."
    status: pending
  - id: step6-doctor
    content: "Step 6: Windows doctor — host is Windows, long-path WARN, kivyforge version, signtool available (SKIP unless signing configured), app source dir, app_id valid, win_amd64 arch coverage, app icon, native-binaries sources + PE arch, signing thumbprint match, find_links, required hosts reachable (PBS+indexes+native URLs+timestamp). Register WindowsPlatform + cli/lock.py windows branch; tests."
    status: pending
  - id: step7-signing
    content: "Step 7: Authenticode signing hook — Signer protocol (NEW, windows-only) + SigntoolSigner (/sha1 thumbprint /fd SHA256 /tr <ts> /td SHA256) + NullSigner default; patch-before-sign ordering; package -f folder signs launcher (payload DLLs deferred v2). Self-signed dev/CI flow (New-SelfSignedCertificate, import to Root for verify /pa), no secrets. Tests against a self-signed cert."
    status: pending
  - id: step8-examples-docs
    content: "Step 8: examples + docs + review stop — add [tool.kivy.windows] overlays + committed pylock.windows.toml to the desktop examples (and a windows overlay on hello-native); verify-desktop-examples.sh handles Windows (or a verify-windows path); README/FAQ/packaging-scope/CHANGELOG; fold the spike findings + realized-vs-designed deltas back into the specs as inline notes; regression gate on Windows AND macOS/Linux. Stop for review."
    status: pending
isProject: false
---

# Kivyforge Windows Backend

Implementation plan for the Windows backend. **The design is already settled**
in three companion specs — this plan sequences the build against them and does
not re-litigate decisions:

- [windows-spec.md](../../docs/design/platforms/windows/windows-spec.md) —
  scope, overlay, runtime, lockfile, onedir layout + the DLL-discovery
  invariant, bootstrap module, native-binaries channel, doctor table, module
  layout, open items.
- [bootloader-windows.md](../../docs/design/platforms/windows/bootloader-windows.md)
  — the prebuilt launcher `.exe`.
- [signing-windows.md](../../docs/design/platforms/windows/signing-windows.md)
  — the optional Authenticode hook.

This is **Phase 5**, structurally the sibling of the
[Linux Phase 4 plan](kivyforge_linux_phase4.plan.md): a full backend on the
shared `lock/wheelruntime/` engine + `RuntimeProvider`, consolidated under
`kivyforge/platforms/windows/`, ending at a review stop. Reuse the shipped
macOS/Linux backends as the template for every seam (config overlay, profile +
provider, bundler stage decomposition, doctor, `init` renderer, examples,
`Platform` registration).

## Non-negotiable sequencing (from the spec)

The spec is emphatic that these happen **in this order**, because each step's
failure mode is indistinguishable from the next step's bugs:

1. **Prove DLL discovery on a clean VM (Step 0).** A perfect bootloader that
   starts an interpreter which can't `import kivy` looks *exactly* like a
   bootloader bug. Command 3 of the verification chain passing on a clean VM is
   the green light for everything else.
2. **Build the bootloader (Step 3).**
3. **Wire signing (Step 7)** — buildable/testable against a self-signed cert at
   any point, zero cost, so it lands last without blocking anything.

Config + lock (Steps 1–2) are independent of the VM spike and can proceed in
parallel with Step 0's host bring-up, but **no bundler/launcher code starts
until the spike passes.**

## Step 0 — Windows host bring-up + the DLL-discovery spike (PROVE FIRST)

Two parts. First, the first time the core runs on a Windows host — flush latent
POSIX assumptions:

- Dev env on Windows amd64: clone, venv, editable install. **Full `pytest` +
  `ruff` green on Windows.** Expected friction:
  - **Artifacts cache path:** the per-OS cache-dir selection
    (`kivyforge/artifacts/cache.py`) must resolve `%LOCALAPPDATA%\kivyforge`
    on Windows (it already handles macOS `~/Library/Caches` and Linux
    `$XDG_CACHE_HOME`); add the Windows arm.
  - **Path handling / separators**, `PurePosixPath` vs `Path` where lock URLs
    and staged relpaths are compared; **exec-bit chmods** are no-ops on Windows
    (the native-stage exec-bit logic must not fail there).
  - Any test assuming POSIX host tools must skip cleanly on Windows.
- **CI:** add a `windows-latest` job (headless `pytest` — unit tests need no
  GL). Permanent cross-platform regression coverage.

Then the **spike that gates the whole backend** — run on a **clean VM (no
Python, no VCRedist)**, per windows-spec §"DLL discovery — prove this first":

```
python\python.exe -c "import sys; print(sys.prefix)"
python\python.exe -c "import kivy_deps.sdl3 as d; print(d.dep_bins)"
python\python.exe -c "import kivy; from kivy.core.window import Window; print(Window)"
```

Manually assemble the minimal tree (relocate a PBS `x86_64-pc-windows-msvc`
`install_only` prefix; `pip install --prefix <prefix> kivy` so `share\sdl3\bin`
is populated), set `PYTHONHOME`, and run the chain. **Command 3 passing is the
green light.** On failure use `Dependencies.exe` / `dumpbin /dependents` on the
failing `.pyd` / `SDL3.dll` — do not guess.

Record findings in **`docs/design/dev/windows-dll-findings.md`** (the
`resolver-findings.md` pattern), resolving the spec's open items:

- Does PBS bundle `vcruntime140.dll` / `vcruntime140_1.dll` / `msvcp140.dll`
  next to `python.exe`? If not, the bundler must place them app-local.
- What GL backend does Kivy 3.0 actually use on Windows/SDL3 (ANGLE vs desktop
  GL) and which dep packages it pulls? **Verify — do not assume the SDL2-era
  `kivy_deps.angle` path.**
- Are PBS's `python.exe`/`python3xx.dll` Authenticode-signed? (Only matters for
  the v2 payload sweep / Smart App Control.)

**Gate:** `pytest`+`ruff` green on Windows; `windows-latest` in CI; the clean-VM
command-3 passes; findings doc written. **Nothing below starts before this
gate.**

## Step 1 — `[tool.kivy.windows]` overlay + `WindowsConfig`

Additive overlay on the shared `[project]` + `[tool.kivy]`, mirroring
`MacosConfig`/`LinuxConfig`. Field set from windows-spec:

- `schema_version` (int, required); `app_id` (AppUserModelID: dot-separated,
  alphanumeric/period/underscore, ≤128 chars, no spaces — **invalid is a hard
  `ConfigError`**, mirroring the macOS `bundle_id` / Linux `app_id` fail-fast);
  `archs` (default `["amd64"]`, only `amd64` allowed this phase, list-shaped);
  `extra_index_urls` / `find_links` / `exclude` (same semantics as the others);
  `python_version`.
- `[tool.kivy.windows.icons].source` (1024×1024 PNG → multi-size `.ico`;
  Pillow, the same opt-in extra as Linux icons).
- `[tool.kivy.windows.signing]` — optional; `thumbprint` (+ `timestamp_url`
  default `http://timestamp.digicert.com`). A `WindowsSigningConfig` dataclass
  with a `configured` property (`bool(thumbprint)`), paralleling
  `MacosSigningConfig`.
- `[tool.kivy.windows.native.binaries]` — reuse the shared
  `_parse_native_binaries(windows, "windows", finder)` + `NativeBinaryDep`
  (already platform-agnostic from the macOS work).
- Extend `Config` with `windows: WindowsConfig | None` + a `windows_required`
  accessor + `require_windows` in `load_config`; add
  `SUPPORTED_WINDOWS_SCHEMA_VERSION`, `VALID_WINDOWS_ARCHS = {"amd64"}`,
  `DEFAULT_WINDOWS_ARCHS = ("amd64",)` to `config/model.py`.
- Tests (`tests/config/test_loader.py`): overlay parse; `app_id` valid/invalid
  matrix; `archs` validation; signing table parse (configured/unconfigured);
  native-binaries source rules (URL/relative accepted, absolute/escaping
  rejected) — largely paralleling `TestMacosNativeBinaries`.

## Step 2 — `pylock.windows.toml`

Simplest of the desktop family — a single stable `win_amd64` tag, no
macOS-version or manylinux ladder. Two small modules under
`kivyforge/platforms/windows/lock/` on the shared engine:

- **`WindowsProfile(PlatformLockProfile)`** (`profile.py`):
  - `variants`: one `Variant(arch="amd64", platform_tag="win_amd64")`.
  - `wheel_covers`: `win_amd64` → `amd64`; `py3-none-any` handled by the shared
    core. **`kivy_deps.*` are ordinary wheels** — Kivy's `win_amd64` wheel
    declares them as conditional deps, so they flow through `[[packages]]` with
    URL+SHA-256 pins; the profile needs no special-casing.
  - `coverage_error`: names the package + suggests `extra_index_urls` /
    `find_links` (no universal2/manylinux escape hatch to mention).
- **`WindowsPbsProvider(PbsProvider)`** (`runtime.py`): triple map
  `{"amd64": "x86_64-pc-windows-msvc"}` — a one-line specialization of the
  triple-agnostic PBS fetcher, exactly as Linux was. Confirm the shared runtime
  normalization applies to the Windows `install_only` archive (normal prefix
  layout — **must not** flatten/prune/`._pth`-isolate it, per the spec: the
  layout is load-bearing).
- Wire `native_binaries=config.windows.binaries` through
  `build_windows_lockfile` into `build_wheel_runtime_lock` (shared; done).
- `platforms/windows/lock/__init__.py` re-exports the engine under
  Windows-friendly names (`WindowsLockfile = WheelRuntimeLock`, etc.), mirroring
  the Linux `lock/__init__.py`.
- Tests: hermetic profile/provider tests with the fake `MetadataFetcher`; a
  golden `pylock.windows.toml` fixture (incl. a `kivy_deps.sdl3` package and a
  `[[tool.kivyforge.native_binaries]]` entry); one live PBS resolution at the
  step boundary (established convention).

**Gate:** `kivyforge lock -p windows` produces a correct, reproducible
`pylock.windows.toml` for a Kivy app.

## Step 3 — the prebuilt launcher `.exe` (bootloader)

Per [bootloader-windows.md](../../docs/design/platforms/windows/bootloader-windows.md).
**Compiled once in CI, never on user machines** (no MSVC requirement — a design
constraint). C source + CI workflow live in-repo regardless of how the binary
is distributed.

- **Source (`platforms/windows/launcher/` C):** `wmain` / `GetCommandLineW` +
  `CommandLineToArgvW` (wide-char argv throughout); `GetModuleFileNameW`
  self-location looping on `ERROR_INSUFFICIENT_BUFFER` (no fixed `MAX_PATH`);
  derive the bundle layout from the launcher's own location (never trust CWD);
  set child env `PYTHONHOME=<bundle>\python`, `PYTHONPATH=<bundle>\app`,
  `PYTHONNOUSERSITE=1`; `CreateProcessW` the child
  (`python\python.exe <bundle>\_kivyforge_bootstrap.py <argv...>`) with every
  path double-quoted; assign to a **Job object** (kill-on-job-close);
  `WaitForSingleObject` → `GetExitCodeProcess` → **exit with the child's code**.
  Link **`/SUBSYSTEM:WINDOWS`** (windowed-only; fixed at link time). This is
  **spawn-and-wait, not `exec`** — the one macOS-stub line that is actively
  wrong ported as-is.
- **CI build workflow:** compile per-arch (amd64 only this phase); publish the
  binary. **Open item to decide here:** distribute as a pinned-SHA-256 release
  asset (fetched via the existing `Downloader`/cache/verify machinery, the PBS
  pattern) **vs.** vendored inside the package. Either way source + CI are
  in-repo.
- **Resource patcher (open item to decide here):** `rcedit` (another vendored
  prebuilt `.exe`) vs. a `pefile`-family Python-native PE resource editor, for
  patching the per-app icon + version resource. Patching happens **before**
  signing (a resource edit invalidates a signature — the Step 7 ordering
  guarantees it). Also confirm distlib/`simple_launcher` **license terms**
  before borrowing any code/binaries (open item — do not take "MIT" on faith;
  kivyforge's bootloader appends nothing to the binary, so its non-reproducible
  appended-zip scheme is avoided, not inherited).
- **Test matrix (real Windows host):** install paths with **spaces**
  (`C:\Program Files\...`); **non-ASCII** paths; **deep trees** near/over the
  260-char limit (with/without `LongPathsEnabled`); launch from a **shortcut
  with blank/arbitrary CWD**; **exit-code propagation**; **process-tree
  teardown** (killing the launcher kills the child via the Job object; no
  orphaned `python.exe`).

**Gate:** the launcher spawns a bundled interpreter, propagates exit codes, and
tears down cleanly across the full path/edge matrix.

## Step 4 — onedir bundler + `build` / `run`

New bundler modules under `kivyforge/platforms/windows/`, mirroring the
macOS/Linux stage decomposition but with the **prefix-install divergence** that
is load-bearing for DLL discovery. Layout (windows-spec):

```
build/windows/MyApp/
├── MyApp.exe                 ← prebuilt launcher, resource-patched per app
├── _kivyforge_bootstrap.py   ← generated (fixed name)
├── app/                      ← user code ([tool.kivy].app_dir)
├── bin/                      ← declared native binaries (Step 5); absent when empty
└── python/                   ← WHOLE PBS prefix (python.exe, DLLs\, Lib\, Lib\site-packages\, share\sdl3\bin\, ...)
```

- **`runtime_stage.py`:** stage the PBS prefix **whole** into `python\` — do not
  flatten/prune. If the spike found PBS omits the VC runtime, place
  `vcruntime140*.dll` / `msvcp140.dll` app-local next to `python.exe`.
- **`wheels_stage.py` — the deliberate divergence:** install wheels with
  **`pip install --prefix <bundle>\python`** (not into a separate `lib\` on
  `PYTHONPATH` as macOS/Linux do), because Kivy's Windows DLLs land under the
  **pip data scheme** at `<prefix>\share\sdl3\bin` keyed off `sys.prefix`. A
  site-packages-only copy **silently drops every SDL3 DLL** and Kivy dies
  importing the window provider (looks like a bootloader bug). Carry the whole
  prefix; no cherry-picking. (This makes Windows the one backend that shells to
  `pip` at build; document why. Confirm against the spike whether an offline /
  no-pip unpack is feasible, else require pip in the build env — a build-host
  requirement, not an end-user one.)
- **`launcher.py`:** generate `_kivyforge_bootstrap.py` (fixed name — per-app
  variability lives in this file, not the binary) that:
  1. sets the explicit AppUserModelID (`app_id`) via
     `SetCurrentProcessExplicitAppUserModelID` (ctypes) **before** any window;
  2. registers `share\sdl3\bin` with `os.add_dll_directory` **before**
     `import kivy` (defense-in-depth; layout is the real fix);
  3. when `<bundle>\bin` exists: registers it with `os.add_dll_directory` +
     PATH-prepends it (Step 5);
  4. puts `<bundle>\app` on `sys.path`, sets CWD to it, imports
     `[tool.kivy].entry_point` (import-not-run-as-`__main__`, like every
     platform).
  Then place the prebuilt launcher as `<display_name>.exe` and **resource-patch**
  it (icon + version resource from `[project]`/`[tool.kivy]`).
- **`icons.py`:** 1024×1024 PNG → multi-size `.ico` (256/48/32/16) via Pillow.
- **Verbs (`cli.py`):** `build` (resolve if needed → runtime stage →
  prefix-install wheels → app copy → native-binaries stage → bootstrap gen →
  launcher place + patch); `run` (build unless `--no-build`, then launch
  `MyApp.exe` in the **foreground** so the dev sees stdout/stderr + tracebacks —
  the windowed child inherits the dev's console handles).
- Tests: bundler assembly unit tests (host-agnostic — assert tree shape,
  bootstrap contents, launcher placement; can run on macOS/Linux CI with a fake
  runtime/wheel); an interactive smoke test on Windows for `run`.

**Gate:** `kivyforge run -p windows` opens the app on a Windows host from the
onedir tree; the assembly tests pass on any host.

## Step 5 — `[tool.kivy.windows.native.binaries]` channel

Reuses the shared config/lock machinery (Steps 1–2 already pin it). New:
staging + bootstrap registration + a PE arch check.

- **`native_stage.py`:** stage each pinned entry into **`<bundle>\bin`** — a
  single file copied as-is; a `.zip` extracted preserving structure — with the
  **path-traversal guard** and the **collision guard** (`_claim`) from the macOS
  implementation. **Reuse opportunity:** the Linux plan (Step 3) flags lifting
  the macOS `_claim` / `_safe_extract` / `_fetch` helpers into a shared
  `kivyforge/artifacts/native_stage_util.py`; Windows is the **third consumer**,
  which makes that extraction clearly worthwhile — do it here (or in whichever
  of the two plans lands first) and have all three backends' `native_stage.py`
  call the shared helpers, each supplying its own error type. Windows staging
  does **not** set an exec bit (meaningless on NTFS) and does **not** rename to
  the config key (source basename preserved — the macOS fix).
- **Bootstrap:** already covered in Step 4's item 3 — when `bin\` exists,
  `os.add_dll_directory(bin)` + PATH-prepend before the app imports, so user
  code loads by name: `ctypes.WinDLL("sdk.dll")`, `subprocess.run(["ffmpeg"])`.
- **doctor PE arch check (with Step 6):** each staged PE in `<bundle>\bin` must
  have a **machine type matching the target arch** (an x86 DLL in an amd64 app
  fails only at load time, cryptically). Needs a tiny hermetic PE reader —
  `platforms/windows/petools.py` reading the COFF header `Machine` field
  (`IMAGE_FILE_MACHINE_AMD64 = 0x8664`) via the PE signature offset at `0x3C`.
  Pure-Python (the PE analog of `machotools` / the Linux `elftools`), so the
  check works on any host and in unit tests.
- Tests: single-file staging (basename preserved); `.zip` extraction; hash
  mismatch; missing vendored source; collision cases; PE machine-type PASS /
  wrong-arch FAIL; bootstrap contains the `bin\` registration only when the
  table is non-empty.

**Gate:** an app with a declared DLL loads it by name from the built bundle; an
arch-mismatched DLL is caught by `doctor` before shipping.

## Step 6 — `doctor` checks (Windows)

`platforms/windows/doctor.py`, reusing `doctor/checks_common.py`, per the
windows-spec doctor table (PASS/WARN/FAIL + remediation, exit non-zero only on
FAIL):

- **Host is Windows** (host-capability); **Long-path support** (WARN if
  `LongPathsEnabled` off — deep trees exceed `MAX_PATH`; registry-fix hint);
  **kivyforge version**; **signtool available** (SKIP unless
  `[tool.kivy.windows.signing]` configured; FAIL when configured but missing);
  **App source directory**; **`app_id` valid** (also a config-time hard error,
  surfaced here with remediation); **Architecture coverage** (every compiled
  dep resolves a `win_amd64` wheel; FAIL names the package); **App icon**
  (valid 1024×1024 PNG when set, else SKIP); **Native binaries: sources**
  (each `source` exists / host reachable; SKIP when empty); **Native binaries:
  arch** (Step 5 PE check; SKIP when empty or unbuilt); **Signing thumbprint**
  (when configured, matches exactly one code-signing cert in the store; SKIP
  unconfigured); **find_links directories**; **Required hosts reachable**
  (PBS + wheel indexes + native-binary URLs + the timestamp server when signing
  is configured).
- **Register the backend:** `WindowsPlatform` in `platforms/windows/__init__.py`
  (`host_system = "Windows"`, `package_formats = ("folder",)`, the
  `reject_ios_only_target` guard, lazy verb imports) added to
  `platforms/__init__.py`; add the `windows` `_LockOps` branch in
  `cli/lock.py`. `status` = the standard read-only snapshot located under
  `build/windows/` by `display_name`.
- Tests: each check's PASS/WARN/FAIL/SKIP paths (probe-faked for host/registry/
  signtool/reachability), paralleling `tests/platforms/linux/test_doctor.py`.

## Step 7 — Authenticode signing hook

Per [signing-windows.md](../../docs/design/platforms/windows/signing-windows.md).
**Policy: v1 ships kivyforge's own binaries + the default artifact UNSIGNED,
but the hook is first-class + optional from day one.**

- **`platforms/windows/signing.py`:** introduce the **`Signer` protocol**
  (`sign(paths) -> None`) — **new to the codebase, Windows-only**, not
  retrofitted onto macOS/iOS (per the abstraction-leak retro). Backends:
  `SigntoolSigner` (default when configured — `signtool sign /sha1 <thumbprint>
  /fd SHA256 /tr <timestamp_url> /td SHA256`, always timestamped) and
  `NullSigner` (unconfigured default → unsigned artifact). A future
  `ArtifactSigningSigner` slots behind the same protocol (deferred).
- **Identity = thumbprint-from-cert-store**, never a `.pfx` path/password in
  config — the same config works for imported pfx, hardware token, or cloud
  signer.
- **What/when signed:** `package -f folder` with signing configured →
  **resource-patch the launcher first** (invalidates any signature), then
  **sign the launcher `.exe`** (the file SmartScreen/users judge). **Payload
  DLLs/`.pyd`s deferred to v2** (a Smart App Control concern; onedir keeps it
  possible). Windows signing is flat (independent per-PE blob) — no macOS-style
  inside-out ordering; the only constraints are patch-before-sign and
  sign-before-any-external-installer.
- **`package -f folder`:** finished onedir under
  `dist/windows/<Name>-<version>-amd64/`, optionally signed. `-f folder` is the
  **only** format — installers are permanently external (document the Inno
  composition seam as user-facing guidance: sign the tree first, Inno signs
  `setup.exe` + uninstaller, one credential path, each file signed once).
- **Dev/CI:** develop + test against a **self-signed cert**
  (`New-SelfSignedCertificate -Type CodeSigningCert`); `signtool`'s surface is
  identical regardless of cert origin, so the whole orchestration (config →
  thumbprint lookup → sign → timestamp → verify) is exercised with **no
  secrets**. `signtool verify /pa` needs the public `.cer` imported to
  `Cert:\LocalMachine\Root` on the test box (CI does this). Self-signed is a
  dev/CI fixture only — document it is **not** for distribution (no SmartScreen
  reputation).
- Tests: config-parse → signer selection; `SigntoolSigner` command assembly
  (assert the exact `signtool` args); the self-signed sign→verify loop on
  Windows CI; `NullSigner` leaves the artifact unsigned; the patch-before-sign
  ordering.

**Gate:** `package -f windows` with a configured (self-signed) thumbprint
produces a signed, timestamped launcher that passes `signtool verify /pa` in CI.

## Step 8 — examples + docs + review stop

- **Examples:** add `[tool.kivy.windows]` overlays + committed
  `pylock.windows.toml` to the desktop examples (`desktop-viewer`,
  `dice-roller`, `notes`) — one `pyproject.toml`, now three desktop lockfiles;
  and a `[tool.kivy.windows]` + `native.binaries` overlay on
  `examples/desktop/hello-native` (a `.dll` loaded by name + a helper `.exe`
  run by name), completing its three-desktop story. Extend
  `hello-native/build_native.sh` with a Windows branch (MSVC/clang-cl or
  mingw), or document producing the Windows artifacts.
- **Verification runner:** extend the full-loop verifier for Windows —
  `verify-desktop-examples.sh` is bash (macOS/Linux); Windows needs either a
  PowerShell sibling (`verify-windows-examples.ps1`) or a documented manual
  loop (`doctor → clean → lock → build → run → package`). Decide during
  implementation; a PowerShell script matching the desktop verifier's 7-step
  lifecycle is the lean choice.
- **Docs:** README (platform table → Windows implemented), FAQ (Windows
  entries: SmartScreen wall, long paths, VC runtime, GL backend), 
  `docs/design/common/06-packaging-scope.md` (Windows row: folder artifact,
  installers external), CHANGELOG. **Fold the spike findings + realized-vs-
  designed deltas back into the three Windows specs as inline implementation
  notes** (flip their "implementation not started" status banners, the
  macos-spec precedent), and finalize `windows-dll-findings.md`.
- **Regression gate:** `pytest` (coverage ≥ 80%) + `ruff` green on **Windows,
  macOS, and Linux** hosts; iOS/macOS/Linux examples unaffected.
- **Stop for review.**

## Explicitly out of scope / deferred (from the spec)

- **Console-subsystem apps** — windowed-only, fixed at link time; revisit on
  demand.
- **onefile** — rejected permanently (extract-to-`%TEMP%`, unsignable embedded
  payload); onedir keeps every file real + signable.
- **Installers** (Inno/NSIS/WiX/MSI/MSIX) — permanently external; kivyforge
  stops at the signed onedir. No in-scope single-file distributable on Windows
  (unlike Linux's AppImage). Store commerce needs MSIX package identity →
  structurally downstream, no hook.
- **Auto-update frameworks** (Squirrel/Velopack, WinSparkle) — external;
  WinSparkle-as-a-DLL can ride the native-binaries channel.
- **win-arm64** — deferred pending demand + Kivy/SDL3 arm64 wheels + PBS arm64
  Windows builds; config stays list-shaped (additive).
- **Payload-DLL signing / PBS-binary re-signing** — v2, Smart App Control only;
  kept possible by onedir.
- **Azure Artifact Signing** — the path if/when kivyforge signs its *own*
  releases; deferred (needs .NET 8 exactly; identity validation is slow).
