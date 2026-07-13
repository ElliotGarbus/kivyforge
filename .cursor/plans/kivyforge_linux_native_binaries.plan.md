---
name: Kivyforge Linux native-binaries channel
overview: Add the [tool.kivy.linux.native.binaries] channel — the Linux sibling of the shipped macOS native-binaries channel — so Linux apps can ship non-wheel .so libraries and helper executables. Fetched + SHA-256-pinned at lock (shared engine, already done for macOS), staged into the AppDir's usr/bin at build with a collision guard, made available to the app via AppRun (PATH for helpers; LD_LIBRARY_PATH decision below for by-name .so loads), checked by doctor (ELF class/machine matches the target arch), seeded (commented) by init, and demonstrated by extending examples/desktop/hello-native with a Linux overlay.
todos:
  - id: step1-config
    content: "Step 1: [tool.kivy.linux.native.binaries] parsing — add `binaries` to LinuxConfig, call the shared `_parse_native_binaries(linux, \"linux\", finder)` in `_parse_linux`; loader tests mirroring the macOS ones (happy path + source validation: URL/relative accepted, absolute/escaping rejected)."
    status: pending
  - id: step2-lock
    content: "Step 2: pin native binaries in pylock.linux.toml — thread `config.linux.binaries` through `build_linux_lockfile` into the shared `build_wheel_runtime_lock(native_binaries=...)` (LockedNativeBinary / resolve_native_binaries / serialize / diff_summary already exist from the macOS work); golden-lock + resolver tests for Linux."
    status: pending
  - id: step3-stage
    content: "Step 3: stage into the AppDir — `kivyforge/platforms/linux/native_stage.py` mirroring the macOS `native_stage.py` (single file under source basename + exec bit, .zip extracted with path-traversal + collision guards, no empty bin/), staged into `usr/bin`; call it from `build_appdir` after `stage_wheels`; unit tests incl. collision cases."
    status: pending
  - id: step4-launcher
    content: "Step 4: AppRun exposure — prepend `usr/bin` to child PATH (helpers by name); settle + implement the LD_LIBRARY_PATH decision for by-name .so loads (see plan); launcher tests asserting the app sees bin on PATH."
    status: pending
  - id: step5-doctor
    content: "Step 5: doctor — `check_linux_native_binaries` (SKIP when empty; FAIL missing vendored source; static single-file basename-collision; ELF class+machine matches each target arch in a built AppDir) via a small hermetic ELF header reader (`elftools.py`); extend `check_linux_hosts_reachable` with native-binary URLs; register in `run_linux_checks`; tests."
    status: pending
  - id: step6-init
    content: "Step 6: init writer — add a commented, inert `[tool.kivy.linux.native.binaries]` stub to `render_linux_tables` (the macOS/iOS stub pattern); test that it renders but does not parse to active config."
    status: pending
  - id: step7-example
    content: "Step 7: extend `examples/desktop/hello-native` with a `[tool.kivy.linux]` overlay + Linux artifacts — make `build_native.sh` also build a Linux helper executable + `libgreet.so`, add the Linux native.binaries table, make `src/main.py` load per-platform; confirm `verify-desktop-examples.sh` exercises it on Linux."
    status: pending
  - id: step8-docs
    content: "Step 8: docs — add a 'Native binaries that are not wheels' section to linux-spec.md (mirror the macOS section, record the LD_LIBRARY_PATH decision + ELF arch check + no-signing note); update the in-scope list; regression gate (pytest+ruff green on macOS AND Linux). Stop for review."
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
Linux code is the AppDir staging (Step 3), the AppRun exposure (Step 4), and
the ELF-aware doctor check (Step 5).

## Decisions (settle in the linux-spec update, Step 8)

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
  - The example (Step 7) demonstrates both `subprocess.run(["roll"])` (PATH) and
    `ctypes.CDLL("libgreet.so")` (by name), and comments the portable by-path
    form (`Path(sys.prefix).parent / "bin" / ...`) since macOS still needs it.
- **Collision guard — same policy as macOS.** `usr/bin` is one flat namespace;
  two entries staging to the same path is a hard build error (`AppDirError`),
  not a silent overwrite. Reuse the macOS `_claim` logic (two single files with
  the same basename, two zips sharing a member, single file vs. zip member).
- **ELF arch check replaces Mach-O arch coverage.** macOS checks universal2
  slice coverage via `machotools`. Linux ships **one arch per AppImage**, so
  the check is simpler: every staged ELF's class (ELFCLASS32/64) + machine
  (`e_machine`) must match the target arch (`x86_64` → ELF64 / `EM_X86_64`).
  A 32-bit or aarch64 `.so` in an x86_64 AppImage fails only at `dlopen` time
  with a cryptic message — catch it in `doctor`.
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

## Step 3 — stage into the AppDir (`usr/bin`)

New `kivyforge/platforms/linux/native_stage.py`, a close mirror of
`kivyforge/platforms/macos/native_stage.py`:

- `stage_native_binaries(lock, usr_dir, *, project_root, cache, no_cache)`:
  return early if `not lock.native_binaries`; else create `usr_dir / "bin"`,
  and for each entry `_stage_one` into it with a shared `claimed: dict` guard.
- `_stage_one`: single file → copy under its **source basename** (so
  `libgreet.so` keeps its extension for by-name/by-path loads — the same fix
  the macOS work needed) + set exec bit; `.zip` → `_extract_zip` with the
  `_safe_extract` path-traversal guard, each member `_claim`ed and exec-bit set.
- `_fetch` wraps `fetch_artifact` catching **both** `DownloadError` and
  `HashMismatch` → `AppDirError` (the macOS bug fix — local checksum errors
  raise `HashMismatch`).
- **Reuse vs. duplicate:** the `_claim`, `_safe_extract`, `_make_executable`,
  and `_fetch` bodies are byte-identical to macOS's except the error type
  (`AppDirError` vs `AppBundleError`). Two options, decide at implementation:
  (a) copy them into the Linux module (matches the repo's per-platform `*_stage`
  convention, zero coupling — **lean**); (b) lift the pure helpers into a small
  shared `kivyforge/artifacts/native_stage_util.py` parameterized on the error
  type. Prefer (a) unless a third consumer (Windows, Step in the other plan)
  makes (b) clearly worth it — Windows will want the same helpers, so this is a
  good moment to note the extraction for the Windows plan to pick up.
- Wire into `build_appdir` (`platforms/linux/bundle.py`): after `stage_wheels`,
  call `stage_native_binaries(lock, work / "usr", ...)` inside the try/temp-tree
  block so a fetch failure discards the half-built AppDir (the existing
  atomic-swap discipline covers it for free).
- Tests (`tests/platforms/linux/test_native_stage.py`): single-file staging
  keeps source basename + is executable; `.zip` extraction preserves structure;
  hash mismatch → `AppDirError`; missing vendored file → `AppDirError`;
  collision cases (two single files same basename, two zips sharing a member,
  single vs zip member). Plus a `build_appdir` ordering test (native staged
  after wheels; `usr/bin` absent when the table is empty).

**Gate:** `kivyforge build -p linux` stages declared binaries into
`<Name>.AppDir/usr/bin`; collisions fail loudly.

## Step 4 — AppRun exposure

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

## Step 5 — `doctor` check (Linux)

Add `check_linux_native_binaries(config, project_root)` to
`platforms/linux/doctor.py`, following `check_macos_native_binaries`:

- **SKIP** when no binaries are declared.
- **FAIL** when a vendored (repo-relative) source is missing on disk; URL
  sources skip the local-existence check (reachability is the hosts check).
- **Static single-file basename-collision** detection (non-`.zip` sources):
  two entries whose source basenames collide FAIL before a build (the
  cheap subset of the Step-3 build-time guard).
- **Built-AppDir ELF arch check:** when `<Name>.AppDir/usr/bin` exists, every
  ELF under it must match each declared arch's class + machine; FAIL naming the
  file + the mismatch. Needs a tiny hermetic ELF reader:
  new `kivyforge/platforms/linux/elftools.py` with `is_elf(path)` and
  `elf_machine(path) -> (elf_class, e_machine)` reading the 20-ish header bytes
  (`\x7fELF`, `EI_CLASS`, little-endian `e_machine` at offset 18). Map
  `x86_64 → (ELFCLASS64, EM_X86_64=62)`. Pure-Python, no `readelf` dependency
  (keeps the check working on any host and in unit tests) — the ELF analog of
  `machotools`.
- Extend `check_linux_hosts_reachable` to add each native-binary `source` that
  is a URL to the reachability set (macOS does the same).
- Register `check_linux_native_binaries` in `run_linux_checks` (both the
  config-present list and the config-absent SKIP list) — insert near the icon /
  find_links project checks.
- Tests (`tests/platforms/linux/test_doctor.py`, `TestNativeBinaries`): skip;
  vendored-missing FAIL; sources-present PASS; URL sources skip local check;
  built ELF arch PASS; built wrong-arch FAIL; single-file basename collision
  FAIL; `.zip` sources don't false-positive the static collision check; plus a
  hosts-reachable test covering a native-binary URL.

**Gate:** `kivyforge doctor -p linux` reports native-binary problems (missing
source, arch mismatch, collision) with actionable hints.

## Step 6 — `init` writer

- Add a commented, inert `[tool.kivy.linux.native.binaries]` stub to
  `render_linux_tables` (`cli/init_writer.py`), copying the shape of the macOS
  stub (`_MACOS_NATIVE_BINARIES_STUB`): a short comment explaining the channel
  + two commented example lines (a URL `.zip` and a repo-relative helper). It
  must be **inert** — rendered text that does not parse to an active binaries
  table.
- Test (`tests/cli/test_init.py`): `render_linux_tables` output contains the
  commented stub, and a full parse of the rendered `pyproject.toml` yields
  `config.linux.binaries == ()`.

## Step 7 — extend `examples/desktop/hello-native`

The example is currently macOS-only; make it the **one-source, two-desktop**
demonstration (the same apps-gain-a-platform pattern used elsewhere):

- `build_native.sh`: detect the platform; on Linux compile `roll` (a helper
  executable) and `libgreet.so` (a shared lib) with `cc`/`gcc` into
  `binaries/linux/` (the macOS branch already emits universal2 into
  `binaries/macos/`).
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

## Step 8 — docs + review stop

- **linux-spec.md:** the "Native binaries that are not wheels
  (`[tool.kivy.linux.native.binaries]`)" section already exists and — as of
  this planning pass — documents the decided **Option B** loading model
  (PATH-for-helpers + appended `LD_LIBRARY_PATH` for by-name `.so`) plus the
  "Library loading model" evaluation subsection, the ELF class+machine arch
  check, the collision-rejection rule, and the no-signing note. Step 8's
  remaining doc work is therefore *maintenance, not authoring*: flip the
  section's "designed, not yet implemented" status banner to "implemented",
  fold in any realized-vs-designed deltas as inline notes (the macos-spec
  precedent), and cross-link the `hello-native` example once it lands.
- **Regression gate:** `pytest` (coverage ≥ 80%) + `ruff` green on **both**
  macOS and Linux hosts; iOS/macOS examples unaffected; the macOS
  native-binaries behavior unchanged (shared engine untouched except the
  already-generic parser/lock paths).
- **Stop for review.**

## Explicitly out of scope / deferred

- **aarch64 native binaries** — follows the backend's own aarch64 deferral;
  the arch check is already list-shaped, so it is additive.
- **Automatic dependency repair of declared `.so`s** (patchelf/rpath surgery on
  vendored libs) — out of scope, same boundary as macOS/Windows: kivyforge
  fetches/verifies/stages/exposes; it does not fix a binary that needs libs it
  didn't ship (the consume-prebuilt-artifacts principle). Document the boundary.
- **`.deb`/`.rpm`/Flatpak interaction** — unchanged; native binaries ride
  inside the AppImage/AppDir like everything else.
