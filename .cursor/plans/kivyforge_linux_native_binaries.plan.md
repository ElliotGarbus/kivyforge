---
name: Kivyforge Linux native-binaries channel
overview: Add the [tool.kivy.linux.native.binaries] channel — the Linux sibling of the shipped macOS native-binaries channel — so Linux apps can ship non-wheel .so libraries and helper executables. Fetched + SHA-256-pinned at lock (shared engine, already done for macOS), staged into the AppDir's usr/bin at build (single files, .zip, and .tar.gz/.tgz) with a collision guard, made available to the app via AppRun (PATH-prepend for helpers; LD_LIBRARY_PATH-append for by-name .so loads, Option B), checked by doctor (ELF class/machine matches the target arch), seeded (commented) by init, and demonstrated by extending examples/desktop/hello-native with a Linux overlay. This pass also extracts the pure staging mechanics into a shared kivyforge/artifacts/native_stage_util.py (rule of three: macOS + Linux + the imminent Windows channel).
todos:
  - id: step1-config
    content: "Step 1: [tool.kivy.linux.native.binaries] parsing — add `binaries` to LinuxConfig, call the shared `_parse_native_binaries(linux, \"linux\", finder)` in `_parse_linux`; loader tests mirroring the macOS ones (happy path + source validation: URL/relative accepted, absolute/escaping rejected)."
    status: pending
  - id: step2-lock
    content: "Step 2: pin native binaries in pylock.linux.toml — thread `config.linux.binaries` through `build_linux_lockfile` into the shared `build_wheel_runtime_lock(native_binaries=...)` (LockedNativeBinary / resolve_native_binaries / serialize / diff_summary already exist from the macOS work); golden-lock + resolver tests for Linux."
    status: pending
  - id: step3-shared-util
    content: "Step 3: extract shared native-stage helpers — lift the pure mechanics (`_safe_extract`, `_claim`, `_make_executable`, `_fetch`, single-file-vs-archive dispatch) out of macOS `native_stage.py` into a new `kivyforge/artifacts/native_stage_util.py`, parameterized on the raised error type (or raising a neutral error each backend wraps); refactor macOS onto them in the SAME change so the existing macOS tests prove the extraction. Rule-of-three: Linux is the 2nd consumer, Windows the 3rd, and `_safe_extract` is security-sensitive so it must live in exactly one audited place."
    status: pending
  - id: step4-stage
    content: "Step 4: stage into the AppDir — `kivyforge/platforms/linux/native_stage.py` consuming the Step-3 shared helpers (single file under source basename + exec bit; `.zip` AND `.tar.gz`/`.tgz` extracted with path-traversal + collision guards; no empty bin/), staged into `usr/bin`; call it from `build_appdir` after `stage_wheels`; unit tests incl. tar.gz extraction + collision cases."
    status: pending
  - id: step5-launcher
    content: "Step 5: AppRun exposure — prepend `usr/bin` to child PATH (helpers by name); append `usr/bin` to LD_LIBRARY_PATH (by-name .so + transitive NEEDED), Option B; both conditional on the app declaring native binaries; launcher tests asserting PATH-first + LD_LIBRARY_PATH-last."
    status: pending
  - id: step6-doctor
    content: "Step 6: doctor — `check_linux_native_binaries` (SKIP when empty; FAIL missing vendored source; static single-file basename-collision; ELF class+machine matches each target arch in a built AppDir) via a hermetic ELF header reader (`elftools.py`) that reads EI_DATA (offset 5) and decodes e_class + e_machine with the matching endianness, and skips non-ELF files (a `#!/bin/sh` helper is legal); extend `check_linux_hosts_reachable` with native-binary URLs; register in `run_linux_checks`; tests."
    status: pending
  - id: step7-init
    content: "Step 7: init writer — add a commented, inert `[tool.kivy.linux.native.binaries]` stub to `render_linux_tables` (the macOS/iOS stub pattern); test that it renders but does not parse to active config."
    status: pending
  - id: step8-example
    content: "Step 8: extend `examples/desktop/hello-native` with a `[tool.kivy.linux]` overlay + Linux artifacts — make `build_native.sh` also build a Linux helper executable + `libgreet.so` (with a comment noting the build host's glibc floor is baked into the artifact), add the Linux native.binaries table, make `src/main.py` load per-platform; confirm `verify-desktop-examples.sh` exercises it on Linux."
    status: pending
  - id: step9-docs
    content: "Step 9: docs — reconcile linux-spec.md: flip the section status to implemented, narrow the archive promise to the formats actually built (`.zip` + `.tar.gz`/`.tgz`), and soften the glibc version-needs WARN to a deferred fast-follow; record the shared `native_stage_util` extraction; update the in-scope list; regression gate (pytest+ruff green on macOS AND Linux). Stop for review."
    status: pending
isProject: false
---

# Kivyforge Linux Native-Binaries Channel

Add `[tool.kivy.linux.native.binaries]`, the Linux sibling of the **shipped
macOS channel** (see `docs/design/platforms/macos/macos-spec.md` §"Native
binaries that are not wheels" and the reference implementation across
`kivyforge/config/`, `kivyforge/lock/wheelruntime/`, and
`kivyforge/platforms/macos/native_stage.py`). This is a **scoped feature
addition to the shipped Linux backend**, not new backend work — the same shape,
sequencing, and tests as the macOS effort, adapted to the AppDir substrate and
ELF.

## What already exists (do not rebuild)

The macOS work landed the **shared** half of this feature in the wheel+runtime
engine, so Linux inherits it for free:

- `NativeBinaryDep` (`config/model.py`) — the parsed `{ name, version, source }`
  entry; **platform-agnostic**, already used by macOS.
- `_parse_native_binaries(overlay, platform, finder)` + the shared
  `_validate_artifact_source("native binary", ...)` (`config/loader.py`) — the
  parser already takes a `platform` argument, so Linux reuses it verbatim.
- `LockedNativeBinary`, `resolve_native_binaries`, serialize/deserialize of
  `[[tool.kivyforge.native_binaries]]`, and `diff_summary` coverage
  (`lock/wheelruntime/`) — all platform-neutral; `build_wheel_runtime_lock`
  already accepts a `native_binaries=` argument.

So Steps 1–2 are almost entirely *wiring*, not new logic. The genuinely new
Linux code is the shared-helper extraction (Step 3), the AppDir staging
(Step 4), the AppRun exposure (Step 5), and the ELF-aware doctor check (Step 6).

## Decisions (settle in the linux-spec update, Step 9)

- **Stage location: `usr/bin` inside the AppDir.** macOS uses
  `Contents/Resources/bin`; the AppDir analog under the runtime prefix is
  `usr/bin`. This keeps the by-path loading contract identical to macOS: the
  app resolves its bin dir as `Path(sys.prefix).parent / "bin"` (on Linux
  `sys.prefix` is `.../usr/python`, so `.parent` is `usr`, giving `usr/bin`).
  Do **not** stage into `usr/python/bin` (PBS territory) or the AppDir root.
- **Helpers on PATH — always.** AppRun prepends `$HERE/usr/bin` to `PATH`
  (mirrors the macOS launcher's `Resources/bin` prepend), so
  `subprocess.run(["mytool"])` resolves. Only add the export when the lock
  actually pins binaries (no dead env var otherwise — matches the "absent when
  empty" `bin/` rule).
- **By-name `.so` loading via `LD_LIBRARY_PATH` append — DECIDED (Option B).**
  macOS could not offer by-name dylib loading (`DYLD_*` is stripped under SIP /
  Hardened Runtime), so the macOS spec documents *by-path* loads only. **Linux
  has no such restriction**, so AppRun **appends** `$HERE/usr/bin` to
  `LD_LIBRARY_PATH` (only when the app declares native binaries). Three loading
  models were evaluated — PATH-only/by-path (A), append (B), prepend (C); the
  full pros/cons live in linux-spec's "Library loading model" subsection (folded
  in during planning). Why **B (append)** wins:
  - **Transitive deps resolve.** By-path loading (A) only helps the *one* lib
    the app explicitly `dlopen`s; a declared `libA.so` with a `NEEDED libB.so`
    (both in `usr/bin`) fails under A — so A can't load a multi-`.so` SDK at
    all. Putting `usr/bin` on `LD_LIBRARY_PATH` resolves the whole declared set.
  - **By-name works** for the app *and* for third-party packages that `dlopen`
    their own vendored lib by soname (which can't be told to use an absolute
    path).
  - **Append, not prepend.** Appending = lowest priority, so the host's own
    libraries and the wheels' auditwheel-vendored `.so`s still win the search;
    the declared dir is a last resort. This *preserves* the linux-spec's
    "don't perturb host libGL/libEGL" intent (host entries searched first) —
    which prepend (C) would violate, shadowing host libs and polluting spawned
    subprocesses at high priority. The one thing append can't do — override a
    same-soname system lib — is exactly the safety property the spec wants, so
    it's a feature here, not a limitation.
  - The example (Step 8) demonstrates both `subprocess.run(["roll"])` (PATH) and
    `ctypes.CDLL("libgreet.so")` (by name), and comments the portable by-path
    form (`Path(sys.prefix).parent / "bin" / ...`) since macOS still needs it.
  - **The PATH-prepend / LD_LIBRARY_PATH-append asymmetry is deliberate** — say
    so in the spec so nobody "fixes" it into symmetry. Executables: the app
    bundling its own `ffmpeg` *wants* it to win, so prepend (high priority).
    Libraries: a bundled `libssl.so` must *not* shadow the host's, so append
    (low priority). One rule: *declared tools win; declared libs never shadow
    the host.*
- **`usr/bin` holds both helpers and libraries — mildly un-FHS, and correct.**
  Putting `.so`s in a dir named `bin` (and on `LD_LIBRARY_PATH`) is not strict
  FHS, but it (a) matches the macOS `Resources/bin` precedent, (b) gives the
  clean cross-platform recipe `Path(sys.prefix).parent / "bin"`, and (c) avoids
  polluting `usr/lib` (the wheel site-packages), where a stray `.so` could
  shadow a wheel's auditwheel-vendored lib. Acknowledge the naming in the spec
  so it is not "corrected" later.
- **Collision guard — same policy as macOS.** `usr/bin` is one flat namespace;
  two entries staging to the same path is a hard build error (`AppDirError`),
  not a silent overwrite. Reuse the shared `_claim` logic (two single files with
  the same basename, two archives sharing a member, single file vs. archive
  member).
- **Archive formats: `.zip` AND `.tar.gz`/`.tgz` — DECIDED.** macOS's
  `native_stage.py` only special-cases `.zip`; everything else falls to the
  "single file, copy as-is" branch. On Linux that is a silent-corruption trap:
  `.tar.gz`/`.tgz` is the *dominant* distribution format for Linux SDKs and
  helper bundles, and a tarball pointed at by `source` would be copied verbatim
  into `usr/bin`, given an exec bit, and SHA-pinned — the app then can't find
  the libraries, and nothing catches it (the tarball isn't an ELF, so the arch
  check skips it). So Linux staging **extracts `.tar.gz`/`.tgz` too**, using
  `tarfile.extractall(..., filter="data")` — the hardened extractor (strips
  symlinks/hardlinks/device nodes/absolute members), which is the tar analog of
  `_safe_extract` and more important for tar than zip (tarfile *restores*
  symlinks, zipfile largely does not). This satisfies the format promise already
  written into linux-spec (the macOS spec, which offers `.zip` only, is
  unchanged). `.tar.gz` is a Linux extension of the shared helper, not a change
  to macOS.
- **Shared native-stage helpers — extract now (rule of three).** The macOS
  `_safe_extract` / `_claim` / `_make_executable` / `_fetch` bodies are the
  same code Linux (and, imminently, Windows) needs; the only per-platform
  difference is the raised error type. Rather than a second (then third) copy,
  Step 3 lifts the pure mechanics into `kivyforge/artifacts/native_stage_util.py`
  and refactors macOS onto them in the same change. `_safe_extract` (path
  traversal) and the tar `filter="data"` hardening above are security-sensitive
  and must live in exactly one audited place — three copies guarantee drift. The
  per-platform `*_stage.py` modules keep only their *orchestration* (bundle
  layout: `Resources/bin` vs `usr/bin`, which error to raise).
- **ELF arch check replaces Mach-O arch coverage.** macOS checks universal2
  slice coverage via `machotools`. Linux ships **one arch per AppImage**, so
  the check is simpler: every staged ELF's class (ELFCLASS32/64) + machine
  (`e_machine`) must match the target arch (`x86_64` → ELF64 / `EM_X86_64`).
  A 32-bit or aarch64 `.so` in an x86_64 AppImage fails only at `dlopen` time
  with a cryptic message — catch it in `doctor`. **Read `e_machine` with the
  right endianness:** it is a 16-bit field whose byte order is given by
  `EI_DATA` (`e_ident[5]`: 1=LE, 2=BE), so hard-coding little-endian would
  misread a big-endian ELF's machine — exactly the mis-supplied-artifact case
  the check exists to catch. `elftools.py` reads `EI_DATA`, then decodes
  `e_class` (offset 4) and `e_machine` (offset 18) accordingly, and skips
  non-ELF files so a legitimate `#!/bin/sh` helper is not failed for "not being
  x86_64".
- **No signing.** Linux has no code-signing analog (linux-spec already says
  so), so — unlike macOS (deep-sign sweep) and Windows (payload sweep) — there
  is nothing to extend. Staged binaries just need their exec bit; nothing signs
  them.

## Step 1 — `[tool.kivy.linux.native.binaries]` parsing

- Add `binaries: tuple[NativeBinaryDep, ...] = ()` to `LinuxConfig`
  (`config/model.py`), mirroring `MacosConfig.binaries`.
- In `_parse_linux` (`config/loader.py`), call
  `binaries = _parse_native_binaries(linux, "linux", finder)` and pass
  `binaries=tuple(binaries)` to `LinuxConfig(...)` — the exact line the macOS
  parser already uses, with `"linux"` for the error-message key path.
- Tests (`tests/config/test_loader.py`, a `TestLinuxNativeBinaries` class
  paralleling `TestMacosNativeBinaries`): happy-path parse (`name`/`version`/
  `source`); URL source accepted; repo-relative source accepted; absolute path
  rejected; `../`-escaping path rejected; a non-table/malformed entry rejected
  with a line-numbered error.

**Gate:** a `pyproject.toml` with the Linux table parses to
`config.linux.binaries`; invalid sources fail at config time.

## Step 2 — pin in `pylock.linux.toml`

- In `build_linux_lockfile` (`platforms/linux/lock/__init__.py`), forward
  `native_binaries=config.linux.binaries` into `build_wheel_runtime_lock(...)`
  (the parameter already exists; macOS passes `config.macos.binaries` the same
  way). No serializer/model/diff changes — that machinery is shared and done.
- Because `config.linux` may be `None` on a non-Linux-required load, guard with
  `config.linux.binaries if config.linux else ()` (match how the macOS profile
  reads it).
- Tests:
  - a golden `pylock.linux.toml` fixture that includes a
    `[[tool.kivyforge.native_binaries]]` entry (extend the existing Linux
    golden-lock test);
  - a resolver test (local vendored source → SHA-256 pinned; URL source via the
    fake downloader; offline behavior) — can largely reuse
    `tests/lock/wheelruntime/test_native_binaries.py` patterns, or assert the
    Linux builder wires them through with a small fake.

**Gate:** `kivyforge lock -p linux` on a project with declared binaries pins
them (name/version/source/sha256), reproducibly.

## Step 3 — extract shared native-stage helpers

Before writing the Linux stager, lift the pure mechanics out of macOS's
`native_stage.py` into a new **`kivyforge/artifacts/native_stage_util.py`**, and
refactor macOS onto them in the **same change** so the existing macOS
`test_native_stage.py` proves the extraction (no behavior change on macOS).

- Move the platform-neutral helpers: `_safe_extract` (zip path-traversal
  guard), `_claim` (collision guard), `_make_executable` (exec-bit), and
  `_fetch` (wraps `fetch_artifact`, catching **both** `DownloadError` and
  `HashMismatch`). Also lift the single-file-vs-archive dispatch shape.
- **Parameterize on the error type.** Each backend raises its own bundle error
  (`AppBundleError` on macOS, `AppDirError` on Linux, the Windows analog next).
  Either (a) pass the error class in, or (b) have the util raise a neutral
  `NativeStageError` that each backend catches and re-raises as its own — pick
  whichever reads cleaner; both keep the per-platform error surface intact.
- **Why now, not per-platform copies.** `_safe_extract` (and the tar
  `filter="data"` hardening added in Step 4) is security-sensitive; three
  near-identical copies (macOS/Linux/Windows) guarantee a future fix drifts.
  One audited implementation is the point. The per-platform `*_stage.py` modules
  keep only their *orchestration* (bundle layout + which error to raise).
- Tests: the existing macOS `tests/platforms/macos/test_native_stage.py` must
  stay green unchanged; add focused unit tests for the extracted util
  (`tests/artifacts/test_native_stage_util.py`) covering `_safe_extract`
  traversal rejection and `_claim` collisions independent of any platform.

**Gate:** macOS native-binary staging is byte-for-byte unchanged; the shared
helpers exist and are unit-tested in isolation.

## Step 4 — stage into the AppDir (`usr/bin`)

New `kivyforge/platforms/linux/native_stage.py`, consuming the Step-3 shared
helpers (its own module holds only the Linux orchestration):

- `stage_native_binaries(lock, usr_dir, *, project_root, cache, no_cache)`:
  return early if `not lock.native_binaries`; else create `usr_dir / "bin"`,
  and for each entry `_stage_one` into it with a shared `claimed: dict` guard.
- `_stage_one`: single file → copy under its **source basename** (so
  `libgreet.so` keeps its extension for by-name/by-path loads — the same fix
  the macOS work needed) + set exec bit. Archive → extract, `_claim` each
  member, set the exec bit. Dispatch on the source extension:
  - `.zip` → `_safe_extract` (the shared zip guard).
  - **`.tar.gz` / `.tgz` → `tarfile.extractall(..., filter="data")`** — the
    hardened extractor (strips symlinks/hardlinks/device nodes/absolute and
    escaping members), the tar analog of `_safe_extract`. This is the Linux
    addition over macOS (see the "Archive formats" decision); without it a
    tarball `source` silently lands as a single opaque file in `usr/bin`.
- Errors surface as `AppDirError` (via the parameterized shared `_fetch` /
  extract helpers).
- Wire into `build_appdir` (`platforms/linux/bundle.py`): after `stage_wheels`,
  call `stage_native_binaries(lock, work / "usr", ...)` inside the try/temp-tree
  block so a fetch failure discards the half-built AppDir (the existing
  atomic-swap discipline covers it for free).
- Tests (`tests/platforms/linux/test_native_stage.py`): single-file staging
  keeps source basename + is executable; `.zip` extraction preserves structure;
  **`.tar.gz` extraction preserves structure and rejects a traversing/symlink
  member**; hash mismatch → `AppDirError`; missing vendored file → `AppDirError`;
  collision cases (two single files same basename, two archives sharing a
  member, single vs archive member). Plus a `build_appdir` ordering test (native
  staged after wheels; `usr/bin` absent when the table is empty).

**Gate:** `kivyforge build -p linux` stages declared binaries into
`<Name>.AppDir/usr/bin` (single files, `.zip`, and `.tar.gz`); collisions fail
loudly.

## Step 5 — AppRun exposure

Extend `render_apprun` (`platforms/linux/launcher.py`). The template currently
sets `PYTHONHOME`/`PYTHONPATH`/`PYTHONNOUSERSITE` + SDL WM_CLASS then `exec`s.
Add, **conditionally on the app declaring native binaries** (pass a
`has_native_binaries: bool` from the bundler, sourced from
`bool(lock.native_binaries)`):

```sh
# Declared native binaries (see linux-spec): helpers by name, libs by soname.
export PATH="$HERE/usr/bin:$PATH"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}$HERE/usr/bin"
```

- `PATH` is **prepended** (helpers shadow nothing important; the app's own
  tools win). `LD_LIBRARY_PATH` is **appended** (host + auditwheel libs win;
  the declared dir is the fallback) — per the decided Option B above.
- Keep the block out entirely when there are no native binaries (no dead env
  vars — symmetry with "no empty `bin/`").
- Tests (`tests/platforms/linux/` launcher tests): (a) rendered source contains
  the `usr/bin` PATH prepend + the `LD_LIBRARY_PATH` **append** when binaries
  are declared, and omits both otherwise; (b) an execution test (mirror the
  macOS `test_child_sees_bin_first_on_path`) writing a fake AppRun tree and
  asserting the child process sees `usr/bin` **first** on `PATH` and **last** on
  `LD_LIBRARY_PATH` (append order — a pre-existing `LD_LIBRARY_PATH` entry stays
  ahead of it).

**Gate:** an app with a declared helper runs it by name from inside the built
AppDir; a declared `.so` loads **by name** (`ctypes.CDLL("libgreet.so")`), and
a multi-`.so` set with inter-lib `NEEDED` deps resolves.

## Step 6 — `doctor` check (Linux)

Add `check_linux_native_binaries(config, project_root)` to
`platforms/linux/doctor.py`, following `check_macos_native_binaries`:

- **SKIP** when no binaries are declared.
- **FAIL** when a vendored (repo-relative) source is missing on disk; URL
  sources skip the local-existence check (reachability is the hosts check).
- **Static single-file basename-collision** detection (non-archive sources —
  `.zip`/`.tar.gz`/`.tgz` members need extraction and are caught at build time):
  two entries whose source basenames collide FAIL before a build (the cheap
  subset of the Step-4 build-time guard).
- **Built-AppDir ELF arch check:** when `<Name>.AppDir/usr/bin` exists (derive
  the name from `config.display_name`, matching `build_appdir`), every ELF under
  it must match each declared arch's class + machine; FAIL naming the file + the
  mismatch. Needs a tiny hermetic ELF reader: new
  `kivyforge/platforms/linux/elftools.py` with `is_elf(path)` and
  `elf_machine(path) -> (elf_class, e_machine)`:
  - `is_elf`: first 4 bytes are `\x7fELF` (and a regular, non-symlink file) —
    mirrors `is_macho`, and lets a `#!/bin/sh` helper be skipped (not failed).
  - `elf_machine`: read `EI_CLASS` (offset 4) and `EI_DATA` (offset 5), then
    decode the 16-bit `e_machine` (offset 18) with the endianness `EI_DATA`
    names (1=LE, 2=BE) — do **not** hard-code little-endian, or a big-endian
    (mis-supplied) artifact's machine is misread. Map
    `x86_64 → (ELFCLASS64=2, EM_X86_64=62)`.
  - Pure-Python, no `readelf` dependency (keeps the check working on any host
    and in unit tests) — the ELF analog of `machotools`.
- Extend `check_linux_hosts_reachable` to add each native-binary `source` that
  is a URL to the reachability set (macOS does the same).
- Register `check_linux_native_binaries` in `run_linux_checks` (both the
  config-present list and the config-absent SKIP list) — insert near the icon /
  find_links project checks.
- Tests (`tests/platforms/linux/test_doctor.py`, `TestNativeBinaries`): skip;
  vendored-missing FAIL; sources-present PASS; URL sources skip local check;
  built ELF arch PASS; built wrong-arch FAIL; a non-ELF script helper is skipped
  (not failed); single-file basename collision FAIL; archive sources don't
  false-positive the static collision check; plus a hosts-reachable test
  covering a native-binary URL.

**Gate:** `kivyforge doctor -p linux` reports native-binary problems (missing
source, arch mismatch, collision) with actionable hints.

## Step 7 — `init` writer

- Add a commented, inert `[tool.kivy.linux.native.binaries]` stub to
  `render_linux_tables` (`cli/init_writer.py`), copying the shape of the macOS
  stub (`_MACOS_NATIVE_BINARIES_STUB`): a short comment explaining the channel
  + two commented example lines (a URL `.zip` and a repo-relative helper). It
  must be **inert** — rendered text that does not parse to an active binaries
  table.
- Test (`tests/cli/test_init.py`): `render_linux_tables` output contains the
  commented stub, and a full parse of the rendered `pyproject.toml` yields
  `config.linux.binaries == ()`.

## Step 8 — extend `examples/desktop/hello-native`

The example is currently macOS-only; make it the **one-source, two-desktop**
demonstration (the same apps-gain-a-platform pattern used elsewhere):

- `build_native.sh`: detect the platform; on Linux compile `roll` (a helper
  executable) and `libgreet.so` (a shared lib) with `cc`/`gcc` into
  `binaries/linux/` (the macOS branch already emits universal2 into
  `binaries/macos/`). Add a comment noting the artifact inherits the **build
  host's** glibc floor — the consume-prebuilt caveat in action: rebuilding on a
  newer distro can silently raise the shipped artifact's host requirement above
  the runtime's 2.17 floor (the deferred glibc version-needs WARN would catch
  this; see out-of-scope).
- `pyproject.toml`: add `[tool.kivy.linux]` (app_id, python, icons) and
  `[tool.kivy.linux.native.binaries]` declaring `roll` + `libgreet` with
  repo-relative `binaries/linux/...` sources.
- `src/main.py`: choose the artifact per platform — `subprocess.run(["roll"])`
  works unchanged (PATH); for the lib, load `libgreet.so` **by name** on Linux
  (`ctypes.CDLL("libgreet.so")`, resolved via the `LD_LIBRARY_PATH` append) and
  by path on macOS (`Path(sys.prefix).parent / "bin" / "libgreet.dylib"`),
  guarded by `sys.platform` — so the example shows both idioms side by side.
- `.gitignore`: already ignores `binaries/` + `pylock.*.toml`; confirm it
  covers the Linux additions.
- `README.md`: add a short Linux section (build the natives, lock, build, run,
  package).
- `verify-desktop-examples.sh` already includes `hello-native` and runs
  `build_native.sh` as a pre-step for both platforms — confirm the Linux path
  produces a working AppImage that invokes the helper + loads the lib.

**Gate:** `hello-native` locks, builds, runs, and packages to a working
AppImage on the Linux host, exercising both a helper (by name) and a lib.

## Step 9 — docs + review stop

- **linux-spec.md:** the "Native binaries that are not wheels
  (`[tool.kivy.linux.native.binaries]`)" section already exists and — as of
  this planning pass — documents the decided **Option B** loading model
  (PATH-for-helpers + appended `LD_LIBRARY_PATH` for by-name `.so`) plus the
  "Library loading model" evaluation subsection, the ELF class+machine arch
  check, the collision-rejection rule, and the no-signing note. Step 9's
  remaining doc work is *maintenance + reconciliation*:
  - Flip the section's "designed, not yet implemented" status banner to
    "implemented" and fold in realized-vs-designed deltas as inline notes (the
    macos-spec precedent).
  - **Narrow the archive promise to match what ships.** The section currently
    says "`.zip`/`.tar.gz` sources extracted"; this is now accurate for Linux
    (Step 4 implements both) — confirm the wording lists exactly `.zip`,
    `.tar.gz`, and `.tgz`, and note that macOS remains `.zip`-only.
  - **Soften the glibc version-needs WARN to a deferred fast-follow.** The
    doctor bullet promises a "best-effort WARN comparing the binary's glibc
    version-needs against the effective floor"; the built check only covers ELF
    class+machine (Step 6), so reword this to a deferred fast-follow (parallel
    to the existing deferred "ELF-inspect the staged `python3` version-needs"
    note) so the spec doesn't advertise an unbuilt check.
  - Record the shared `kivyforge/artifacts/native_stage_util.py` extraction
    (Step 3) in the relevant module-layout notes (linux + macos), and cross-link
    the `hello-native` example once it lands.
- **Regression gate:** `pytest` (coverage ≥ 80%) + `ruff` green on **both**
  macOS and Linux hosts; iOS/macOS examples unaffected; the macOS
  native-binaries behavior unchanged (shared engine + the newly extracted
  `native_stage_util` verified by the untouched macOS `test_native_stage.py`).
- **Stop for review.**

## Explicitly out of scope / deferred

- **aarch64 native binaries** — follows the backend's own aarch64 deferral;
  the arch check is already list-shaped, so it is additive.
- **glibc version-needs WARN in `doctor`** — comparing a declared binary's
  `GLIBC_2.xx` symbol requirements (parsed from `.gnu.version_r`/verneed)
  against the effective floor is materially more work than the header-only
  class+machine check, so it is a **deferred fast-follow** (parallels the
  existing deferred `python3` version-needs safeguard in linux-spec). The
  builds it would flag are exactly the "build host's glibc floor is the user's
  own call" case (Step 8's example comment).
- **Automatic dependency repair of declared `.so`s** (patchelf/rpath surgery on
  vendored libs) — out of scope, same boundary as macOS/Windows: kivyforge
  fetches/verifies/stages/exposes; it does not fix a binary that needs libs it
  didn't ship (the consume-prebuilt-artifacts principle). Document the boundary.
- **`.deb`/`.rpm`/Flatpak interaction** — unchanged; native binaries ride
  inside the AppImage/AppDir like everything else.
