# Windows — Bootloader Design

The onedir bundle's entry point is a **native compiled launcher `.exe`** (the
"bootloader") — like the macOS compiled Mach-O stub in form, but with three
deliberate departures from it: it is **prebuilt in CI** rather than compiled
at package time, it is **windowed-subsystem only**, and it
**spawns-and-waits** rather than `exec`ing. This document specifies the
bootloader; the bundle layout it depends on is defined in the
[Windows spec](windows-spec.md#onedir-bundle-layout--and-the-dll-discovery-invariant).

> **Status: design settled, implementation not started** (tracked with the
> [Windows spec](windows-spec.md)). Bootloader work starts only after the
> clean-VM DLL-discovery spike passes — a perfect bootloader that starts an
> interpreter which can't import Kivy looks exactly like a bootloader bug.

## Why a native binary at all

Windows needs a real PE executable as the thing the user double-clicks: it
owns the taskbar presence, the icon, the version resource ("Properties →
Details"), and the Authenticode signature. A `.bat`/`.cmd` script flashes a
console window and can't be signed as the app's face; a bare `python.exe`
shortcut misattributes the app to Python. This is the Windows analog of the
macOS rule that `CFBundleExecutable` must be a real Mach-O — same conclusion,
different enforcement mechanism.

## Prebuilt and vendored, not compiled on demand

The macOS stub compiles per-app with `clang` at package time. That is safe
*only* because the Xcode command-line tools are already required for
`codesign` — the compiler is a free rider on an existing requirement. **There
is no equivalent guarantee on Windows**: requiring MSVC Build Tools on every
user's machine would be a heavy, fragile dependency for ~a hundred lines of C.

So the Windows bootloader is:

- **Compiled once in CI** (per arch — amd64 only this phase) and shipped as a
  binary asset. Whether that asset is fetched as a pinned-SHA-256 release
  artifact (the PBS pattern, via the existing `Downloader`/cache/verify
  machinery) or vendored inside the kivyforge package is an
  [open item](windows-spec.md#open-items); the C source and the CI build
  workflow live in the repo either way.
- **Parameterized per app without recompilation.** The macOS stub bakes an
  `{entry}` compile-time constant into each app's binary; that is dropped.
  In its place: the **fixed bundle layout convention** plus the **generated
  bootstrap module** — the binary always runs
  `python\python.exe <bundle>\_kivyforge_bootstrap.py`, and everything
  app-specific (entry point, AppUserModelID, DLL-directory registration)
  lives in that generated file. One binary, every app.

### Per-app parameterization: resource patching

The only per-app changes to the binary itself are **resources**, not code:
the icon (from `[tool.kivy.windows.icons]`) and the version resource (product
name / file version / copyright from `[project]` + `[tool.kivy]`). A resource
patch does not require a toolchain — but the patching tool is an **open
item**:

- **`rcedit`** (the Electron project's tool) is the draft choice — proven,
  single-purpose — but it is *another* prebuilt `.exe` to vendor and
  version.
- A **Python-native PE resource editor** (the `pefile` family) would avoid a
  second vendored binary at the cost of owning more PE format surface.

Either way, patching happens **before** signing (a resource edit invalidates
any existing signature), which the signing pipeline's ordering already
guarantees — see [signing-windows.md](signing-windows.md).

## Windowed subsystem only

- **Console-only apps are explicitly out of scope.** kivyforge is a Kivy/GUI
  tool; revisit only if users ask. (Mirrors the macOS `.app` vs.
  console-binary distinction.)
- The console/GUI subsystem is **fixed at link time**
  (`/SUBSYSTEM:WINDOWS` / `-mwindows`), not selectable at runtime — this is
  why distlib ships separate `t*` (console) and `w*` (windowed) stubs.
  Dropping console collapses the build matrix to windowed-only per arch: one
  binary this phase.
- Getting this right at link time is what prevents the console window
  flashing on every launch — the classic tell of a mispackaged Python GUI
  app.
- The dev loop keeps its output: a windowed-subsystem process launched *from*
  a console (`kivyforge run`) has no console of its own, but the spawned
  `python.exe` child inherits the developer's standard handles, so
  stdout/stderr and tracebacks still land in the terminal.

## spawn-and-wait, not `exec`

**This is the one line of the macOS stub that is actively wrong if ported
as-is.** The macOS launcher ends in `execv`, replacing itself with the
interpreter. Windows has no true `execv`: the CRT's `_wexecv` does not
replace the process image — it spawns a new process and kills the caller. A
naive port means `MyApp.exe` exits immediately, the shell prompt returns
while the app is still running, and the taskbar button / AppUserModelID
attach to `python.exe` rather than the launcher the user clicked.

Instead, the bootloader does what distlib's launchers do:

1. **`CreateProcessW`** the child interpreter
   (`<bundle>\python\python.exe <bundle>\_kivyforge_bootstrap.py <argv...>`).
2. Assign the child to a **Job object** configured with
   kill-on-job-close — so Ctrl-C, task kill, and process-tree teardown behave
   correctly and a `python.exe` is never orphaned when the launcher dies.
3. **`WaitForSingleObject`** on the child, then **`GetExitCodeProcess`**, and
   **exit with the child's exit code** — scripts and CI wrapping the app see
   the real result.

The bootloader stays alive as the visible process for its lifetime.

**Rejected: hosting the interpreter in-process** via `python3.dll` +
`Py_InitializeFromConfig`. One process instead of two, but it is a
mini-bootloader's worth of C (config structs, path initialization, error
surfaces), and it would make Windows the architectural odd-one-out against
the exec-based POSIX launchers. Spawn-and-wait keeps the same mental model —
"the launcher hands off to the bundled interpreter" — and has a concrete side
benefit: because the child process *is* `python.exe`, **`python.exe`'s own
directory is on the default DLL search path** during transitive DLL
resolution (relevant to the VC++ runtime question — see the
[Windows spec](windows-spec.md#what-the-sdl3-dep-does-not-cover)). An
in-process host would have lost that.

## Implementation details

Every one of these corresponds to a bug distlib actually shipped and fixed;
they are requirements, not suggestions.

- **Wide-char argv throughout.** `wmain` (or `GetCommandLineW` +
  `CommandLineToArgvW`); build the child command line and environment as
  UTF-16. Narrow `main(argc, argv)` yields mbcs-decoded arguments and mangles
  non-ASCII paths.
- **Path quoting.** `CreateProcessW`'s single-string command line is
  unforgiving with paths like `C:\Program Files\...`. Explicitly double-quote
  every path assembled into the command line (or use the array-based
  `_wspawnv` family, which quotes per-argument — but note `_wspawnv` gives up
  the Job-object attach point, so quoted `CreateProcessW` is the primary
  path).
- **Self-location.** `GetModuleFileNameW` with a generously-sized buffer,
  looping on `ERROR_INSUFFICIENT_BUFFER`. A fixed `MAX_PATH` buffer truncates
  on deep install paths. Everything — the python dir, the bootstrap path, the
  env values — derives from the launcher's own resolved location.
- **Don't trust the CWD.** Shortcuts launch with arbitrary working
  directories ("Start in" is user-editable and often blank). Resolve every
  path relative to the launcher; the *bootstrap* sets the working directory
  to `<bundle>\app` for the app's own relative asset loads.
- **Environment setup ports cleanly from the macOS stub.** Set
  `PYTHONHOME=<bundle>\python`, `PYTHONPATH=<bundle>\app`, and
  `PYTHONNOUSERSITE=1` (isolate from the user's `%APPDATA%` site-packages) in
  the child environment. This and the self-location → derive-bundle-layout
  skeleton are the parts of the macOS C that survive the port; the `execv`
  tail and the `{entry}` constant are the parts that don't.

### Test matrix

The launcher test suite must cover, on a real Windows host:

- install paths containing **spaces** (`C:\Program Files\My App\...`);
- **non-ASCII** paths (`C:\Users\Ünïcödé\...`);
- **deep trees** near/over the 260-char `MAX_PATH` limit (with and without
  the `LongPathsEnabled` registry opt-in — also a `doctor` WARN, see the
  [spec's doctor table](windows-spec.md#doctor-checks-windows));
- launch from a **shortcut with an arbitrary/blank working directory**;
- **exit-code propagation** (child exits nonzero → launcher exits nonzero);
- **process-tree teardown** (killing the launcher kills the child via the Job
  object; no orphaned `python.exe`).

## Prior art

- **distlib launchers** (`simple_launcher`, Vinay Sajip) — the source of the
  spawn-and-wait + Job object model, the link-time subsystem split, wide-char
  argv, and the precompiled-not-recompiled distribution model. Every pip
  console script on Windows rides these stubs. Two caveats before borrowing
  more than the design: **confirm the exact license terms** before vendoring
  binaries or code (an [open item](windows-spec.md#open-items) — do not take
  "MIT" on faith), and note that its appended-zip scheme embeds a build
  timestamp and does not honor `SOURCE_DATE_EPOCH`, so a naive copy of that
  scheme is not byte-reproducible — relevant given kivyforge's PEP 751
  lockfile discipline. (kivyforge's bootloader appends nothing to the binary,
  so the issue is avoided rather than solved.)
- **BeeWare Briefcase** — not a bootloader reference (it delegates to a
  packaged support build), but the source of the signing identity model — see
  [signing-windows.md](signing-windows.md#identity-thumbprint-from-cert-store-not-pfx-path).
- **PyInstaller** — a *cautionary* example: its bootloader exists largely to
  service onefile (extract-to-`%TEMP%`, mutate embedded binaries, re-sign at
  build time). The PBS-prefix + onedir approach never mutates binaries, so
  the signature-invalidation cascade PyInstaller engineers around simply
  never arises here.
