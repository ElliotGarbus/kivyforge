# Windows host + DLL-discovery spike findings (Phase 0)

**Questions:**

1. Does the shared core run correctly on a native Windows host (cache path,
   NTFS exec-bit no-ops, path handling, full `pytest` + `ruff`)?
2. On a **clean VM** (no Python, no VC++ runtime), can a manually assembled
   run-from-folder tree — a relocated PBS `install_only` prefix plus the exact
   **Kivy 2.3.1 / SDL2** wheel set installed by the no-pip wheel-scheme
   installer — import Kivy and open its window provider offline?

Part 1 is the CI gate and is **done** (see below). Part 2 is the manual
clean-VM gate; the protocol and open questions are recorded here and must be
run on real hardware/VM before any bundler or launcher code (Phases 3–5) is
trusted end to end.

## Part 1 — Windows host bring-up (DONE)

Environment: Windows 10.0.26200, Python 3.13.1, dev venv (`pip install -e
".[dev]"`). `pytest` (81.7% coverage, ≥ 80% gate) and `ruff check` /
`ruff format --check` are **green on Windows**. A permanent `windows-latest`
matrix job (`3.13`, `3.14`) is wired into `.github/workflows/kivyforge.yml`.

### Verified (do not reimplement)

- **Artifacts cache path.** `artifacts/cache.py` resolves
  `%LOCALAPPDATA%\kivyforge\Cache\artifacts`
  (observed: `C:\Users\<user>\AppData\Local\kivyforge\Cache\artifacts`).
  Correct as shipped.
- **NTFS exec bit is a harmless no-op.** `os.chmod(path, 0o755)` succeeds and
  reads back `0o666` — NTFS has no POSIX exec bit, and the shared
  `_make_executable` neither fails nor has any effect. Windows native staging
  (Phase 6) documents this as an explicit no-op rather than forking it out.
- **File locking on `build`/`package` (rename access-denied).** A `PermissionError`
  / `WinError 5` when replacing the onedir is the write-in-place vs. antivirus /
  running-exe / Explorer-lock interaction, not a bug. Root cause, the
  transient-vs-persistent failure taxonomy, and the **Dev Drive + Defender
  performance mode** mitigation are documented in
  [windows-spec.md → Windows file locking](../platforms/windows/windows-spec.md#windows-file-locking-write-in-place--dev-drive)
  (implementation: `platforms/windows/fsswap.py`).

### Latent POSIX assumptions flushed (fixed this phase)

These were real cross-platform defects, not Windows-only test noise, and each
also protects the Windows backend:

- **`os.path.isabs` / `normpath` are host-dependent.** Python 3.13 stopped
  treating a single leading `/` as absolute on Windows, so
  `source = "/abs/x"` slipped past the loader's source/`app_dir`/`find_links`
  validation on Windows only; and `os.path.normpath` emits backslashes that
  `PurePosixPath` will not split, so `"../../x"` evaded the escape check.
  `config/loader.py` now validates with host-independent helpers
  (`_is_absolute_source`, `_posix_normpath`) that reject a path absolute under
  *either* POSIX or Windows rules and normalize `\` before the parts check.
- **`file:` URL → path conversion.** `urlparse(url).path` yields `/C:/…` on
  Windows; `Path(unquote(...))` mangled it. The iOS lock builder now uses
  `urllib.request.url2pathname`, which is correct on every host.
- **User-facing paths must be forward-slashed.** `kivyforge clean` and the
  Xcode `relativePath` for local Swift packages now emit `as_posix()` output so
  messages and generated project files are stable across hosts.
- **Symlink privilege.** A stock Windows host cannot create symlinks without
  Developer Mode/admin. Tests that create symlinks (or exercise the iOS
  `<app>-ios/app` staging symlink) are gated behind a `requires_symlinks`
  marker; POSIX-shell tests behind `requires_posix` (see `tests/conftest.py`).
  CI enables `git config core.symlinks true` so the Windows runner still
  exercises those paths. iOS never actually builds off macOS, so no iOS staging
  code changed.
- **pyproject I/O is UTF-8.** `init` and the loader already read/write with
  `encoding="utf-8"`; a test that used `Path.read_text()` (locale cp1252 on
  Windows) against a UTF-8 stub containing an em dash was corrected.

## Part 2 — Clean-VM DLL-discovery spike (PENDING: needs a clean VM)

> This gate requires a Windows VM with **no Python and no VC++ runtime**
> installed. It cannot be satisfied on a dev box that already has them. Nothing
> in Phases 3–5 (launcher, runtime/wheel staging, onedir build) is trusted
> end to end until command 3 below passes on that clean VM.

### Protocol

1. Relocate a PBS `x86_64-pc-windows-msvc` **`install_only`** prefix to
   `python\` in an empty tree (no flatten/prune/`._pth` isolation — the normal
   prefix layout is load-bearing).
2. Stage the exact **Kivy 2.3.1** wheel set (`kivy`, `kivy_deps.sdl2`,
   `kivy_deps.glew`, and whatever GL deps 2.3.1 actually pulls on Windows) with
   the no-pip wheel-scheme installer so `share/sdl2/bin` is populated at
   `<prefix>\share\sdl2\bin`.
3. Set `PYTHONHOME=<tree>\python` and run:

   ```
   python\python.exe -c "import sys; print(sys.prefix)"
   python\python.exe -c "import kivy_deps.sdl2 as d; print(d.dep_bins)"
   python\python.exe -c "import kivy; from kivy.core.window import Window; print(Window)"
   ```

   **Command 3 passing (a window provider imports) is the green light.** On
   failure, run `Dependencies.exe` / `dumpbin /dependents` on the failing
   `.pyd` / `SDL2.dll` — do not guess.
4. Repeat against Kivy 3 / SDL3 when a public Windows wheel exists (SDL3 is
   forward-compat only; there are no public Kivy 3 desktop wheels today).

### Open questions the spike must answer (drive later phases)

- **VC runtime — RESOLVED (Phase 4).** Inspected the PBS `install_only` Windows
  archive `cpython-3.13.14+20260623-x86_64-pc-windows-msvc-install_only.tar.gz`:
  its prefix root ships `vcruntime140.dll` and `vcruntime140_1.dll` next to
  `python.exe`, but **not** `msvcp140.dll` (the C++ runtime). Accordingly
  `runtime_stage.ensure_vc_runtime` verifies the two core CPython DLLs (a no-op
  for stock PBS, with an app-local fallback from the host VC++ redistributable
  should a future PBS build drop them) and places `msvcp140.dll` app-local
  best-effort when the runtime omits it (a dep wheel may also ship it into
  site-packages). The clean-VM gate below still confirms whether the shipped
  SDL/codecs actually need `msvcp140.dll` at runtime.
- **GL backend.** Which GL backend Kivy 2.3.1 uses on Windows (ANGLE vs desktop
  GL) and its dep packages — verify, do not assume; feeds the doctor coverage
  check and the FAQ.
- **PBS `.data` layout** and runtime symlink/extraction behavior.
- **Authenticode state of PBS binaries** (`python.exe` / `python3xx.dll`) — a
  v2 payload-signing sweep input only.

_Status: Part 1 complete; the VC-runtime open question is RESOLVED (Phase 4,
above). The Windows backend is implemented and covered by the full test suite
plus the CI `windows_launcher` reproducibility/asset gate; the GL-backend and
`.data`-layout questions were answered incrementally by the wheel-staging work.
The one item that genuinely needs a pristine box — command 3 (a window provider
imports) on a VM with **no** system Python/VC++ — remains the manual "verify on a
clean VM" step in the Phase 10 final gate and is the last sign-off before
release._
