# Agent prompt — Windows T3 artifact checks (roadmap item 5, test-matrix §5.1)

> **Run this on Windows** — it needs no device, no CI, no other host. Written
> 2026-09-18 to hand off a fresh context; the previous session had covered
> items 3, 4 and 9 and was too full to continue safely.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what exists, what's missing

[`test-matrix.md`](test-matrix.md) §5.1 tracks T3 (post-build artifact
inspection) per platform. Android, macOS and Linux are done — checker
functions in `tests/artifact_checks.py`, hermetic tests against synthetic
trees in `tests/test_artifact_checks.py`, and a real-artifact driver per
platform. **Windows is the one unchecked box**, and the gap list already names
the shape:

> "Windows check functions. Same split, not blocked on §5.3, and the option
> can sit ready behind `--windows-onedir` exactly as `--android-apk`,
> `--macos-app`, and `--linux-appimage` did."

Confirmed before writing this: `tests/conftest.py`'s `pytest_addoption`
(~line 65) does **not** yet have `--windows-onedir` / `--windows-arch` /
`--windows-stripped` — they need adding, mirroring the existing
`--linux-appimage` / `--linux-arch` / `--linux-stripped` trio exactly.

**The two functions to mirror**, both in `tests/artifact_checks.py`:

- `linux_appdir_problems(appdir, *, arch, stripped, expected_magic)` (~line
  536) — closest shape, since Windows is also a folder-form desktop bundle,
  not an archive to extract first.
- `macos_app_problems(...)` (~line 295) — worth reading for the
  `bundle_id`/`executable` optional-exact-match pattern, if you want parity
  with how it checks identity fields (Windows has no `Info.plist`, but
  `_kivyforge_bootstrap.py`'s `app_id` plays a similar role — your call
  whether that's in scope here or a follow-up, same as the still-open
  "merged manifest matches config" item for Android).

**Two things worth knowing before you start, both easy to get wrong:**

1. **The Windows onedir layout** (`kivyforge/platforms/windows/bundle.py`'s
   module docstring has the authoritative version):
   ```
   build/windows/<Name>/
   ├── <Name>.exe                ← prebuilt launcher, resource-patched per app
   ├── _kivyforge_bootstrap.py   ← generated (fixed name)
   ├── app/                      ← user code ([tool.kivy].app_dir)
   ├── bin/                      ← declared native binaries (absent when empty)
   └── python/                   ← whole PBS prefix
   ```
   `package -p windows` copies this into
   `dist/windows/<bundle_dir_name>-<version>-<arch>/` (`windows/cli.py`,
   `windows_package`) — point the driver at the **dist** copy, since that is
   the actual distributable, the same way the Linux driver takes an AppImage/
   AppDir rather than the `build/` tree.

2. **`_kivyforge_bootstrap.py` is never compiled, on purpose.** In
   `windows/bundle.py`, `byte_compile([bundle / "app", bundle / "python" /
   "Lib" / "site-packages"], ...)` and `compile_stdlib(bundle / "python",
   ...)` both run, and only *after* that does `write_bootstrap(bundle, ...)`
   generate the bootstrap file at the bundle root. So under
   `--windows-stripped`, `_kivyforge_bootstrap.py` **must not** be flagged as
   an unstripped-source violation — it was never a candidate for stripping in
   the first place, same as how the Linux/macOS checkers scope the stripped-
   payload sweep to `app`/`lib` and deliberately leave the embedded stdlib's
   `.py` files alone (item 9; `_linux_payload_problems`'s stdlib exclusion is
   the pattern to copy).

**Explicitly out of scope for this task**: wiring a Windows build into CI.
That's test-matrix.md §5.3 (a desktop build job), which is a separate,
larger item gated on an unresolved lock-policy decision — don't pull it in
here. This task validates against a **local** build on this dev box, the same
way §5.1's Linux/macOS work validated against local builds before any CI job
existed for them.

## Prompt

You are closing the Windows box of roadmap item 5 / test-matrix.md §5.1: T3
artifact checks for a built Windows onedir bundle, mirroring the Android/
macOS/Linux pattern exactly.

### Step 0 — baseline

```bash
git pull                      # modernization-rfc, latest
python -m pytest -q
ruff check kivyforge tests && ruff format --check kivyforge tests
pyright
```

All four green before you change anything.

### Step 1 — the checker function

Add `windows_onedir_problems(bundle, *, arch, stripped, expected_magic)` to
`tests/artifact_checks.py`, following `linux_appdir_problems`'s shape and
helper-function decomposition (`_windows_required_problems`,
`_windows_payload_problems`, `_windows_pe_problems`, `_windows_pyc_magic_problems`
— name them however reads best, but keep the same "list of problem strings,
never raises" contract every existing checker uses, so one run reports every
fault instead of stopping at the first).

At minimum, check:

- **Required entries exist**: `<Name>.exe`, `_kivyforge_bootstrap.py`,
  `app/`, `python/`. `bin/` only if native binaries were declared — do not
  fault on its absence (`windows/bundle.py` only creates it when
  `lock.native_binaries` is non-empty; check the Linux equivalent's handling
  of optional dirs for the pattern).
- **PE machine matches the target arch.** There's no existing
  `kivyforge/platforms/windows/*` PE-header reader the way
  `elftools.py`/`machotools.py` exist for Linux/macOS — check
  `kivyforge/platforms/windows/petools.py` first; if it already parses enough
  of the PE header (machine type), use it, matching how the other checkers
  import their arch constants from the build's own module rather than
  redefining them. If it does not, a minimal PE `IMAGE_FILE_HEADER.Machine`
  read (offset via the `e_lfanew` DOS-header pointer) is enough — do not add a
  dependency for this.
- **Payload stripping, scoped correctly**: `app/` and `python/Lib/
  site-packages` are the strip-source candidates (mirrors the Linux/macOS
  scoping); `python/`'s stdlib keeps sources always (item 9); and per the
  Background note above, `_kivyforge_bootstrap.py` is excluded from the sweep
  entirely, not just from the "must be stripped" check but from being walked
  at all — it lives at the bundle root, not under `app/`, so a `rglob` scoped
  correctly should not even reach it. Verify that scoping in the tests you
  write next, not by inspection.
- **`.pyc` magic matches the shipped runtime**, same approach as
  `linux_appdir_problems`'s `expected_magic` parameter — the caller (the
  driver, Step 4) is responsible for asking the bundle's own
  `python/python.exe` what magic it expects, not the test runner's.

### Step 2 — hermetic tests

In `tests/test_artifact_checks.py`, add a test class for
`windows_onedir_problems` against synthetic onedir trees built with `tmp_path`
— no real build, no Windows-specific behaviour needed to run these (they
should pass on any host, same as the existing Linux/macOS hermetic tests do
today). Cover at minimum: a well-formed bundle (no problems), a missing
`<Name>.exe`, a missing `python/`, an unstripped `app/*.py` when `stripped=True`
is asserted, a correctly-stripped bundle, and — the one worth being deliberate
about — **a synthetic bundle where `_kivyforge_bootstrap.py` is source-only
under `stripped=True`, asserting this produces *zero* problems.** That's the
regression test for the Background note above; without it, a future change to
the sweep's scoping could silently start flagging the bootstrap file and
nobody would notice until a real build failed the check.

### Step 3 — wire the CLI option

In `tests/conftest.py`, add `--windows-onedir`, `--windows-arch` (default
`"amd64"`, matching `VALID_WINDOWS_ARCHS`'s default), and `--windows-stripped`,
in the same `addoption` group and in the same shape as the `--linux-*` trio.

### Step 4 — the driver

New file `tests/platforms/windows/test_onedir_artifact.py`, mirroring
`tests/platforms/macos/test_app_artifact.py` structure exactly: module-scoped
fixture reading `--windows-onedir` (skip with a clear message if absent, so a
plain local `pytest` run stays green), an `_expected_magic()` helper that runs
the bundle's own `python/python.exe -c "import importlib.util;
print(importlib.util.MAGIC_NUMBER.hex())"` (same pattern as the macOS driver's
`_expected_magic()`, just a different relative path to the interpreter), then
one test per check group calling `windows_onedir_problems`.

### Step 5 — validate against a real bundle

```bash
cd examples/desktop/dice-roller
kivyforge package -p windows
$dist = Get-ChildItem dist\windows -Directory | Select-Object -First 1
pytest tests/platforms/windows/test_onedir_artifact.py -q `
  --windows-onedir $dist.FullName --windows-stripped
```

This must pass against a real bundle on the first try if Steps 1-4 are
correct — if it doesn't, that's either a real defect (report it) or a checker
bug (fix it), not something to work around in the test.

### Step 6 — full suite, then report

```bash
python -m pytest -q
ruff check kivyforge tests && ruff format --check kivyforge tests
pyright
```

Update `test-matrix.md` §5.1: check off "Windows check functions", and add a
§7 results-log row (local, dated, Host `Windows`) naming what you validated it
against. Do **not** touch §5.3 or the Windows CI job — out of scope, per
Background.

### Rules of engagement

- Record what you observed. If Step 5's real-bundle check fails, say so and
  show the actual problem list rather than silently adjusting the checker to
  pass.
- Do not commit generated example locks or anything under `dist/`/`build/`.
- Commit on `modernization-rfc`. **Do not push without asking.**
