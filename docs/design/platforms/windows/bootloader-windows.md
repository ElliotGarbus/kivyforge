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

- **Compiled once in CI** (per arch — amd64 only this phase) and **vendored
  inside the kivyforge package** (settled — with a license/notice, a pinned
  SHA-256, and explicit package-data entries). The C source and a
  **deterministic CI rebuild** live in the repo; the rebuild byte-compares its
  output against the vendored binary, so the shipped asset is always
  reproducible from source. (kivyforge's launcher appends nothing to the
  binary, so the non-reproducibility that dogs distlib's appended-zip scheme
  does not arise — see [Prior art](#prior-art).)
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
patch does not require a toolchain.

**Settled: `rcedit`** (the Electron project's tool) — proven and
single-purpose. It is a second prebuilt `.exe`, so it is vendored alongside the
launcher with its license/notice and a pinned SHA-256, and the resource-patch
step is exercised on `windows-latest` (`rcedit` runs only on Windows). A
Python-native PE resource editor (the `pefile` family) was weighed — it would
avoid the second vendored binary and be host-agnostic — but robust icon-group +
`RT_VERSION` *writing* is significant PE-format surface to own, so the proven
tool wins for v1.

The version resource's numeric `FILEVERSION`/`PRODUCTVERSION` are four 16-bit
integers, but `[project].version` is a PEP 440 string; the packaging step maps
the PEP 440 version to a **deterministic four-part numeric** for those fields
(the human-readable string goes in `ProductVersion` / `FileDescription`). The
exact mapping is defined in [signing-windows.md](signing-windows.md).

Patching happens **before** signing (a resource edit invalidates any existing
signature), which the signing pipeline's ordering already guarantees — see
[signing-windows.md](signing-windows.md).

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
- **The dev loop keeps its output — but the console handoff is explicit, not
  assumed.** A windowed-subsystem process does not reliably inherit a parent
  console's standard handles just because it was launched from one, so the
  launcher makes the handoff deliberate:
  - It calls **`AttachConsole(ATTACH_PARENT_PROCESS)`**. When a parent console
    exists (the `kivyforge run` path from a terminal), the launcher then
    **explicitly passes the attached stdin/stdout/stderr handles to the
    child** (via `STARTUPINFO`/handle inheritance) so the child (a
    console-subsystem `python.exe`) writes straight to the terminal — tracebacks
    and prints land where the developer is looking.
  - When there is **no** parent console (an Explorer double-click), attaching
    fails; the launcher then creates the console-subsystem child with
    **`CREATE_NO_WINDOW`** so no console window flashes.
  - `python.exe` (console subsystem) is used rather than `pythonw.exe` on both
    paths precisely so the attach-for-diagnostics story works under `run`;
    `CREATE_NO_WINDOW` handles the double-click no-flash requirement without
    giving that up.

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
   (`<bundle>\python\python.exe <bundle>\_kivyforge_bootstrap.py <argv...>`)
   with **`CREATE_SUSPENDED`**, so it exists but has not run any code yet.
2. Assign the suspended child to a **Job object** configured with
   kill-on-job-close, **then resume the child's main thread** (`ResumeThread`).
   Creating-suspended-then-assigning closes the race where a child spawns
   grandchildren *before* it is in the job — with the resume ordering, every
   descendant is captured, so Ctrl-C, task kill, and process-tree teardown
   behave correctly and a `python.exe` is never orphaned when the launcher
   dies.
3. **`WaitForSingleObject`** on the child, then **`GetExitCodeProcess`**, and
   **exit with the child's exit code** — scripts and CI wrapping the app see
   the real result. Close every handle (process, thread, job) on exit.

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
[Windows spec](windows-spec.md#what-the-binary-deps-do-not-cover)). An
in-process host would have lost that.

## Implementation details

Every one of these corresponds to a bug distlib actually shipped and fixed;
they are requirements, not suggestions.

- **Wide-char argv throughout.** `wmain` (or `GetCommandLineW` +
  `CommandLineToArgvW`); build the child command line and environment as
  UTF-16. Narrow `main(argc, argv)` yields mbcs-decoded arguments and mangles
  non-ASCII paths.
- **Argv quoting — use the correct algorithm, not naive double-quoting.**
  `CreateProcessW`'s single-string command line is unforgiving: a path like
  `C:\Program Files\...` must be quoted, and any argument containing a `"` or
  trailing backslashes must be escaped by the exact **inverse of
  `CommandLineToArgvW`** (double internal quotes, and double the run of
  backslashes that immediately precedes a quote or the closing quote).
  Wrapping arguments in quotes without that backslash/quote handling corrupts
  paths ending in `\` and any argument with an embedded quote. (The array-based
  `_wspawnv` family quotes per-argument, but it gives up the Job-object attach
  point, so quoted `CreateProcessW` with the correct algorithm is the primary
  path.)
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
- **forwarded quoted arguments** round-trip intact (an argument with spaces,
  embedded quotes, and trailing backslashes reaches `sys.argv` unchanged);
- **visible output under `kivyforge run`** (stdout/stderr and tracebacks land
  in the terminal) and **no console flash** on an Explorer double-click;
- **Ctrl-C** delivered from the console terminates the child;
- **exit-code propagation** (child exits nonzero → launcher exits nonzero);
- **process-tree teardown** (killing the launcher kills the child via the Job
  object; no orphaned `python.exe`).

## Prior art

- **distlib launchers** (`simple_launcher`, Vinay Sajip) — the source of the
  spawn-and-wait + Job object model, the link-time subsystem split, wide-char
  argv, and the precompiled-not-recompiled distribution model. Every pip
  console script on Windows rides these stubs. kivyforge takes the **design**
  only and ships its **own** launcher C source, so distlib's license terms do
  not gate anything (nothing of its code or binaries is vendored). Worth noting
  the reason to write our own rather than copy: distlib's appended-zip scheme
  embeds a build timestamp and does not honor `SOURCE_DATE_EPOCH`, so it is not
  byte-reproducible — at odds with kivyforge's PEP 751 lockfile discipline.
  kivyforge's launcher **appends nothing** to the binary, and the deterministic
  CI rebuild keeps it reproducible.
- **BeeWare Briefcase** — not a bootloader reference (it delegates to a
  packaged support build), but the source of the signing identity model — see
  [signing-windows.md](signing-windows.md#identity-thumbprint-from-cert-store-not-pfx-path).
- **PyInstaller** — a *cautionary* example: its bootloader exists largely to
  service onefile (extract-to-`%TEMP%`, mutate embedded binaries, re-sign at
  build time). The PBS-prefix + onedir approach never mutates binaries, so
  the signature-invalidation cascade PyInstaller engineers around simply
  never arises here.
