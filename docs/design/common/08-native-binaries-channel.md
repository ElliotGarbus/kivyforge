# 08 — The native-binaries channel (cross-platform)

The desktop backends share a declared channel for **native binaries that no
wheel delivers** — vendor SDK libraries (`.dylib` / `.so` / `.dll`), hardware
dongles, camera/scanner/payment-terminal SDKs, and helper executables (a bundled
`ffmpeg`). It is the desktop sibling of iOS's
[`[tool.kivy.ios.native.swift_packages]`](../platforms/ios/06-swift-packages.md) /
`xcframeworks` channels, with a uniform `name → { version, source }` shape and a
single shared lock representation.

> **Status: shipped on all three desktop backends (macOS, Linux, Windows).** The
> shared staging mechanics live in `kivyforge/artifacts/native_stage_util.py`
> (`stage_binaries()` — fetch/verify, `_safe_extract`, tar `filter="data"`, the
> `_claim` collision guard, plus the Windows-facing casefold /
> reserved-name / ADS guards and the exec-bit no-op), which all three backends
> call through thin per-backend wrappers. The per-platform divergences are
> captured in the table below; the platform specs keep only their divergent row.

## Why it exists

The core principle is **consume prebuilt artifacts**
([04 — artifact distribution](04-artifact-distribution.md)): kivyforge does not
build native code from source. Most native code arrives as platform-tagged
wheels and flows through the [lock engine](03-lockfile-concept.md) automatically.
The native-binaries channel covers the residue — native artifacts that are *not*
packaged as wheels — so an app can declare them once, get the same integrity
discipline as wheels (URL/path → SHA-256 pin), and have them staged and made
loadable at build time, instead of smuggling them under `app_dir` with no
pinning, no arch check, and manual path gymnastics.

## Shared design (stable across platforms)

- **Config surface:** `[tool.kivy.<platform>.native.binaries]`, each entry
  `name = { version = "...", source = "..." }`. `source` is always explicit — a
  direct `http(s)://` download URL or a repo-relative path to a vendored
  artifact; absolute paths and paths escaping the project are rejected at config
  time. Parsed by the shared `NativeBinaryDep` model + `_parse_native_binaries`
  (already platform-agnostic — it takes the platform name as an argument).
- **Lock representation:** a `[[tool.kivyforge.native_binaries]]` array in
  `pylock.<platform>.toml` pinning `name`/`version`/`source`/`sha256`, living in
  the **shared** wheel+runtime lock engine — so every desktop backend adopts it
  with no lock-format rework. Mirrors the iOS `[[tool.kivyforge.xcframeworks]]`
  pattern.
- **Build staging:** fetch through the shared download/cache/verify machinery,
  then stage into the bundle's `bin` directory — a single file copied under its
  **source basename** (not renamed to the config key), a `.zip` extracted
  preserving structure, with a **path-traversal guard** and a **collision
  guard** (two entries staging to the same path is a hard build error, never a
  silent overwrite).
- **The boundary (so the channel can't creep):** kivyforge fetches, verifies,
  stages, exposes, and (where applicable) signs declared binaries. It does
  **not** resolve their dependencies, fix their imports/rpaths, or otherwise
  repair a binary that expects libraries it didn't ship with — that is the
  vendor's job. A declared binary whose own dependencies are *also* declared
  works (everything in `bin` resolves against `bin`); one that needs something
  else is the user's diagnostic.
- **The escape hatch remains:** files dropped under `app_dir` are still copied
  wholesale into the bundle, but get none of the above — no pinning, no
  registration, no arch check. Fine for a quick experiment; declare it once it
  matters.

## Where the platforms genuinely diverge

The one substantive per-platform difference is **how a staged library becomes
loadable** — dictated by each OS's dynamic loader and security model. Helper
*executables* are uniform (staged into `bin`, put on `PATH`, run by name); the
divergence is entirely about shared libraries.

| Platform | Stage dir | Library loading model | Arch check | Signing interaction |
|----------|-----------|-----------------------|------------|---------------------|
| **macOS** (shipped) | `Contents/Resources/bin` | **By path only** — `DYLD_*` is stripped under SIP / Hardened Runtime, so no by-name option exists. `PATH` prepend for helpers. | Mach-O universal2 slice coverage (`machotools`) | Deep-sign sweep already walks every Mach-O; notarization *requires* it |
| **Linux** (shipped) | `usr/bin` | **By name via `LD_LIBRARY_PATH` append** (helpers on `PATH`) — append keeps host libGL/libEGL resolution first while enabling soname + transitive `NEEDED` loads. See [linux-spec §"Library loading model"](../platforms/linux/linux-spec.md#library-loading-model). | ELF class + `e_machine` (a small hermetic reader) | None — Linux has no signing analog |
| **Windows** (shipped) | `<bundle>\bin` | **By name via `os.add_dll_directory` + `PATH` prepend** in the generated bootstrap. | PE COFF machine type (`IMAGE_FILE_MACHINE_*`, a small hermetic reader) | v1 signs the launcher only; the onedir keeps every payload PE signable if ever needed (a full sweep is not planned) |

Everything *else* — the config shape, the source rules, the lock field, the
fetch/verify/stage/collision-guard pipeline — is common, which is exactly why the
three thin wrappers over `native_stage_util.stage_binaries()` carry no duplicated
staging logic.

## Current authoritative sources

Until this document is promoted, the platform specs remain authoritative:

- **macOS (shipped):**
  [macos-spec §"Native binaries that are not wheels"](../platforms/macos/macos-spec.md#native-binaries-that-are-not-wheels-toolkivymacosnativebinaries),
  with the runnable [`examples/desktop/hello-native`](../../../examples/desktop/hello-native).
- **Linux (shipped):**
  [linux-spec §"Native binaries that are not wheels"](../platforms/linux/linux-spec.md#native-binaries-that-are-not-wheels-toolkivylinuxnativebinaries)
  + [plan](../../../.cursor/plans/kivyforge_linux_native_binaries.plan.md).
- **Windows (shipped):**
  [windows-spec §"Native binaries that are not wheels"](../platforms/windows/windows-spec.md#native-binaries-that-are-not-wheels)
  + [plan](../../../.cursor/plans/kivyforge_windows_backend.plan.md), with the
  runnable [`examples/desktop/hello-native`](../../../examples/desktop/hello-native)
  Windows overlay (`greet.dll` loaded by name, `roll.exe` run by name).

## Follow-ups

- [x] **Extract shared staging helpers.** Done — the `_claim` / `_safe_extract` /
      tar `filter="data"` / `_make_executable` / `_fetch` bodies live in
      `kivyforge/artifacts/native_stage_util.py` (`stage_binaries()`), raising the
      neutral `NativeStageError`; macOS, Linux, and Windows all call it through
      thin per-backend wrappers. The Windows guards (case-insensitive collision
      keys so `SDK.dll`/`sdk.dll` collide, reserved-name / alternate-data-stream
      rejection, exec-bit no-op) extend the *shared* helper behind opt-in flags,
      so macOS/Linux behavior is unchanged.
- [ ] **Unify the arch-check seam.** `machotools` (Mach-O), the Linux ELF reader,
      and the Windows PE reader (`petools`) are three small header parsers with
      one job — "does this binary match the target arch?" A common
      `arch-of-binary` interface behind them would let `doctor` share one code
      path. Deferred (each is tiny and already tested independently).
- [ ] **Decide the doc's final shape.** Either keep this as the cross-platform
      reference under `common/`, or collapse it into a short principle in
      [04 — artifact distribution](04-artifact-distribution.md) and let the
      platform specs own the details.
- [ ] **Link it up.** Cross-link from the platform specs and from
      [00 — overview](00-overview.md) once promoted.
