# 08 — The native-binaries channel (cross-platform)

The desktop backends share a declared channel for **native binaries that no
wheel delivers** — vendor SDK libraries (`.dylib` / `.so` / `.dll`), hardware
dongles, camera/scanner/payment-terminal SDKs, and helper executables (a bundled
`ffmpeg`). It is the desktop sibling of iOS's
[`[tool.kivy.ios.native.swift_packages]`](../platforms/ios/swift-packages.md) /
`xcframeworks` channels, with a uniform `name → { version, source }` shape and a
single shared lock representation.

> **Status: PLACEHOLDER — revisit after Windows is implemented.** This document
> is intentionally a stub. The channel is **shipped on macOS and Linux**,
> **designed on Windows**, and the three platform specs currently each carry
> their own full description. The shared staging mechanics have **already been
> extracted** into `kivyforge/artifacts/native_stage_util.py` (`stage_binaries()`
> — fetch/verify, `_safe_extract`, tar `filter="data"`, the `_claim` collision
> guard), which both the macOS and Linux backends now call through thin
> wrappers. Once the Windows backend lands (the third and final desktop
> implementation, its `native_stage.py` a third thin wrapper), promote this from
> a pointer into the authoritative cross-platform reference: consolidate the
> shared design here, keep only the genuinely platform-specific divergences in
> the platform specs, and act on the
> ["Revisit after Windows"](#revisit-after-windows) checklist below. Do **not**
> expand it into that reference before then — the Windows implementation will
> surface deltas (as macOS's did), and consolidating against three *implemented*
> backends is cheaper and more accurate than against two-shipped-one-designed.

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
| **Windows** (designed) | `<bundle>\bin` | **By name via `os.add_dll_directory` + `PATH` prepend** in the generated bootstrap. | PE COFF machine type (`IMAGE_FILE_MACHINE_*`) | v2 payload sweep signs every PE, so `bin\` is covered |

Everything *else* — the config shape, the source rules, the lock field, the
fetch/verify/stage/collision-guard pipeline — is common, which is exactly why
consolidating it here (post-Windows) will remove real duplication.

## Current authoritative sources

Until this document is promoted, the platform specs remain authoritative:

- **macOS (shipped):**
  [macos-spec §"Native binaries that are not wheels"](../platforms/macos/macos-spec.md#native-binaries-that-are-not-wheels-toolkivymacosnativebinaries),
  with the runnable [`examples/desktop/hello-native`](../../../examples/desktop/hello-native).
- **Linux (shipped):**
  [linux-spec §"Native binaries that are not wheels"](../platforms/linux/linux-spec.md#native-binaries-that-are-not-wheels-toolkivylinuxnativebinaries)
  + [plan](../../../.cursor/plans/kivyforge_linux_native_binaries.plan.md).
- **Windows (designed):**
  [windows-spec §"Native binaries that are not wheels"](../platforms/windows/windows-spec.md#native-binaries-that-are-not-wheels)
  + [plan](../../../.cursor/plans/kivyforge_windows_backend.plan.md).

## Revisit after Windows

When the Windows backend is implemented, work through this checklist:

- [ ] **Consolidate.** Move the shared design (config surface, source rules,
      lock field, staging pipeline, collision guard, boundary, escape hatch)
      into this document as the single source of truth; reduce each platform
      spec's section to just its divergent row (stage dir, loading model, arch
      check, signing).
- [x] **Extract shared staging helpers.** *Done* — the `_claim` /
      `_safe_extract` / tar `filter="data"` / `_make_executable` / `_fetch`
      bodies live in `kivyforge/artifacts/native_stage_util.py`
      (`stage_binaries()`), raising the neutral `NativeStageError`; macOS and
      Linux call it through thin per-backend wrappers. **Remaining for
      Windows:** wrap it (a third thin wrapper) and extend the *shared* helper
      with the Windows-specific guards — **case-insensitive collision keys**
      (so `SDK.dll`/`sdk.dll` collide), **reserved-name / alternate-data-stream
      rejection**, path-separator normalization, and an explicit **exec-bit
      no-op** on Windows.
- [ ] **Unify the arch-check seam.** `machotools` (Mach-O), the Linux ELF
      reader, and the Windows PE reader are three small header parsers with one
      job — "does this binary match the target arch?" Consider a common
      `arch-of-binary` interface behind them so `doctor` shares one code path.
- [ ] **Record realized-vs-designed deltas.** Fold any Windows implementation
      surprises (and any Linux ones) back in as inline notes, the macos-spec
      precedent. Flip the Linux/Windows spec sections' status banners to
      "implemented".
- [ ] **Decide the doc's final shape.** Either keep this as the cross-platform
      reference under `common/`, or (if it stays thin) collapse it back into a
      short principle in [04 — artifact distribution](04-artifact-distribution.md)
      and let the platform specs own the details. Make the call with three
      shipped backends in hand.
- [ ] **Link it up.** Cross-link from the platform specs and from
      [00 — overview](00-overview.md) once promoted.
