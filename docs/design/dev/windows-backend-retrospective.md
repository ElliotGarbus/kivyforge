# Windows backend retrospective + carry-forward for Android

**Scope.** A post-implementation retrospective on building the Windows backend
(the onedir bundle: vendored windowed launcher `.exe`, python-build-standalone
runtime, no-pip wheel-scheme installer, native-binaries channel, optional
Authenticode signing, `doctor`). The goal is to capture what surprised us, what
we would do differently, and — most usefully — to translate each lesson into a
**pre-flight checklist for the Android backend** so we pay the tuition once.

This is a developer note, not a spec. For *what* the Windows backend does, see
[windows-spec.md](../platforms/windows/windows-spec.md); for the clean-machine
DLL/runtime findings, see [windows-dll-findings.md](windows-dll-findings.md).
How the Android carry-forward below actually landed is scored in
[android-backend-retrospective.md](android-backend-retrospective.md).

---

## TL;DR

- The **design** was largely right the first time; almost every painful surprise
  was an **environmental / host-reality** issue (file locking, encoding, toolset
  drift, DLL discovery), not an architecture miss.
- The recurring theme: **"the host is not hermetic."** Windows leaks its
  encoding, its antivirus, its file-locking semantics, its system DLLs, and its
  CI toolset into the build. The fixes were all about *refusing to depend on the
  host* — vendor it, pin it, verify it, or make the operation atomic and
  retryable.
- The best late-stage catch was a **review-driven audit** that found the same
  class of bug (non-atomic write-in-place) lurking in the already-"done" macOS
  and Linux backends. Cross-platform invariants should be verified *across all
  platforms at once*, not per-platform.

---

## What went well (keep doing this)

- **Shared wheel+runtime lock core paid off.** Windows was "the simplest desktop
  family" at the lock layer — one wheel tag (`win_amd64`), one PBS triple, no fat
  binary, no tag ladder. The platform profile was a thin specialization. The
  investment in a platform-agnostic core is the single biggest reason the
  backend came together quickly.
- **`doctor` as a first-class surface.** Turning environment assumptions into
  explicit, testable checks (host reachability, build-output lock, filesystem
  type, signing cert/thumbprint, arch coverage) repeatedly converted "mysterious
  runtime failure" into "actionable message before you waste time."
- **Vendoring + SHA-256 pinning of prebuilt binaries** (launcher, rcedit) with a
  reproducibility gate in CI. When the environment drifted, the gate *told us*.
- **Design docs written before/with the code**, and kept honest (open items
  flipped to RESOLVED with evidence). This retrospective is cheap precisely
  because the decisions were already recorded.

---

## Biggest surprises

Each is written as: **what bit us → root cause → the fix → the transferable
lesson.**

### 1. Windows file locking broke "write-in-place" (the biggest one)

- **What bit us.** `PermissionError: [WinError 5] Access is denied` during
  `build` and `package`, intermittently. A freshly written `.exe` (just patched
  by rcedit) or a directory a user had open in Explorer/a terminal could not be
  renamed or deleted.
- **Root cause.** Unlike POSIX, Windows does not let you freely rename/replace a
  file or directory that another handle holds open, and **antivirus scans
  freshly written executables synchronously**, holding them open for a beat. Our
  build assumed POSIX rename semantics.
- **The fix.** `platforms/windows/fsswap.py`: rename-with-retry, reserve /
  restore / discard of the previous tree, and an actionable error when a lock
  persists. Plus a Dev Drive advisory in `doctor` and docs.
- **Lesson.** **Filesystem mutation is a platform contract, not a primitive.**
  Design every artifact write as *atomic + retryable* from day one, and never
  destroy the previous good artifact until the new one is fully staged.

### 2. The host's default text encoding is not UTF-8

- **What bit us.** `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f`
  when reading a subprocess/report during `lock`.
- **Root cause.** Windows Python defaults to the locale codepage (cp1252), not
  UTF-8, for `subprocess` text and `read_text()`.
- **The fix.** Explicit `encoding="utf-8"` on the affected reads and subprocess
  calls.
- **Lesson.** **Never rely on the platform default encoding.** Pass
  `encoding="utf-8"` (and `errors=`) explicitly at every text boundary. Add this
  to the linter/review checklist rather than discovering it at runtime.

### 3. CI toolset drift silently broke reproducibility

- **What bit us.** The launcher reproducibility gate failed with `cl not found`
  because the pinned MSVC toolset (14.38) vanished from the `windows-latest`
  runner image.
- **Root cause.** Byte-identical PE output requires a **fixed** MSVC toolset (the
  PE "rich header" encodes the compiler build), but hosted CI images roll their
  toolchains forward and drop old ones. Pinning made us *depend on an artifact CI
  stopped providing*.
- **The fix.** A `workflow_dispatch` **`revendor_launcher`** job that recompiles
  against the runner's *current* toolset, updates `TOOLSET.txt` / `SHA256SUMS` /
  the vendored binary, and commits — a self-healing path — plus a clearer error
  pointing at it.
- **Lesson.** **Reproducibility pins age.** Any "byte-identical against a pinned
  toolchain" gate needs a **documented, automated re-vendor path from day one**,
  and the error must name it. This is doubly relevant for Android (Gradle / AGP /
  build-tools / NDK all drift).

### 3b. …and the toolset pin was chasing a version that does not exist

The follow-on to §3, worth its own entry because the first two fixes were both
*plausible and wrong* — a good example of a bug that punishes reasoning by
analogy and only yields to reading the bytes.

- **What bit us.** After the re-vendor path existed, `verify` still flipped
  between exactly two PE hashes on `windows-latest`. Pinning the full
  `VCTOOLSVERSION` (14.51 → 14.51.36231) did not fix it. Also pinning
  `WindowsSDKVersion` did not fix it. Both re-vendors just moved which hash was
  "the vendored one."
- **Root cause.** `VCTOOLSVERSION` names the **toolset directory**, not the
  compiler in it, and Microsoft services `cl.exe` in place: toolset
  `14.38.33130` ships `cl` **19.38.33133**; the CI images both reported
  `14.51.36231` while running `cl` builds **36248** and **36252**. That build
  number goes into the PE **rich header** — whose length shift moved every
  subsequent file offset and perturbed the `/Brepro` hash. 307 bytes of drift,
  and **not one byte of it was code**. The pin could never have worked: vcvars
  selects by the version that doesn't discriminate, and hosted runner image
  builds are not selectable at all.
- **The fix.** Link with **`/EMITTOOLVERSIONINFO:NO`** — omit the rich header
  entirely. Verified by patching the compiler stamp inside a `.obj` and
  relinking: 73 bytes of drift with the header, **byte-identical without it**
  (the `/Brepro` hash stops depending on tool identity once the stamp is gone).
  `has_tool_version_stamp` then asserts the flag took effect, so a toolchain
  that stops honoring it fails loudly instead of silently re-breaking. The
  toolset pin stays, demoted to what it can actually deliver: stable *code
  generation*.
- **Lesson.** **Diff the artifact before pinning anything.** Two rounds of
  plausible-sounding pins cost more than one structural diff would have — the
  rich-header offset shift was visible in the first 240 bytes. And more
  generally: **make the artifact not encode the environment**, rather than
  trying to freeze an environment you do not control. A version string is only a
  pin if it actually identifies the bits.

### 3c. The self-healing path healed itself out of its own gate

- **What bit us.** Every `revendor_launcher` run committed a new binary whose
  reproducibility gate then **never ran**. Three commits in the history exist
  only to poke CI awake afterwards.
- **Root cause.** GitHub does not start workflow runs from pushes made with the
  default `GITHUB_TOKEN` (a recursion guard). A job that commits on your behalf
  therefore lands its change *outside* CI — silently.
- **The fix.** A `revendor_verify` job that `needs: revendor_launcher` and checks
  out the SHA that job pushed. A separate job also means a separate runner VM,
  so it is a genuine cross-machine check — the same-job verify inside
  `revendor_launcher` never could be, which is why the drift in §3b survived a
  passing re-vendor twice.
- **Lesson.** **A bot commit is an untested commit.** Any job that writes to the
  repo needs its verification wired as an explicit dependent job; do not assume
  the normal push-triggered CI will pick it up. Applies to any future
  auto-update job (lockfile refreshes, vendored-asset bumps).

### 4. Runtime/DLL discovery is host-dependent and arch-sensitive

- **What bit us.** PBS ships `vcruntime140*.dll` but **not** `msvcp140.dll`; we
  sourced it from the host `C:\Windows\System32`. Under a 32-bit interpreter,
  WOW64 redirection could stage an **x86** DLL into an **amd64** bundle.
- **Root cause.** "Grab it from the system" is not reproducible and not
  arch-safe; `System32` is WOW64-redirected per process bitness.
- **The fix.** A pure-Python PE machine-type reader (`petools.py`), architecture
  validation before copying, and `Sysnative` handling. (The arm64 design later
  concluded the *real* fix is to pin `msvcp140.dll` as a per-arch artifact — see
  [arm64-windows.md](../platforms/windows/arm64-windows.md).)
- **Lesson.** **A bundle must carry its own runtime; borrowing from the host is a
  latent clean-machine failure.** Validate the architecture of every binary you
  stage. Prove host-independence on a **clean VM early** (we kept a clean-VM
  protocol in the DLL findings for exactly this).

### 5. The app launched but no window appeared

- **What bit us.** After `run`, the process started but the Kivy window never
  opened.
- **Root cause.** Importing the entry module ran top-level code but **not** the
  `if __name__ == "__main__": App().run()` guard.
- **The fix.** Run the entry point as `__main__` via
  `runpy.run_module(..., run_name="__main__", alter_sys=True)`, mirroring the
  macOS/Linux launchers.
- **Lesson.** **"It imports" ≠ "it runs."** The launch contract (how user code
  becomes `__main__`, CWD, `sys.path`, DLL dirs) must be explicit and identical
  across platforms.

### 6. Process-tree teardown needs OS help

- **What bit us.** Killing the launcher could orphan the child `python.exe`.
- **Root cause.** No parent/child lifetime link by default.
- **The fix.** A **Job object** with kill-on-close in `launcher.c`, assigned
  while the child is suspended, then resumed — **best-effort** for job setup,
  **mandatory** teardown on `ResumeThread` failure.
- **Lesson.** **Decide the degradation policy explicitly** (best-effort vs.
  mandatory) for every OS guarantee, and write it into the code comment and the
  spec so reviewers can check it.

### 7. Failure atomicity was missing — everywhere, not just Windows

- **What bit us.** A signing failure could leave the *new* incomplete package in
  place while the *previous* known-good one was already gone. A review then found
  the same shape on macOS (`.app` written in place) and Linux (AppImage deleted
  before the tool ran).
- **The fix.** Stage-then-swap with rollback on Windows; assemble-into-temp then
  atomic swap on macOS; emit-to-temp then `os.replace` on Linux. Plus
  failure-atomicity tests per platform and hermetic build→package pipeline tests.
- **Lesson.** **Invariants are cross-cutting; audit them across every platform at
  once.** "Done and green on platform X" does not mean the shared invariant holds
  on Y and Z. Bake failure-atomicity and integration tests in from the start.

### 8. Small platform papercuts that cost real time

- **Line endings.** CRLF snuck into `*.sh`, breaking `bash -n`. Fixed with
  `.gitattributes` (`*.sh eol=lf`, `*.ps1 eol=crlf`). *Lesson: set
  `.gitattributes` before writing cross-platform scripts.*
- **`doctor` false negative.** Hardcoded port 443 flagged the (port-80) RFC-3161
  timestamp server unreachable even though signing worked. *Lesson: derive probe
  parameters (port) from the actual URL scheme.*
- **CI symlink tests silently skipped.** `git config core.symlinks true` does not
  grant the OS privilege; tests self-skipped. Fixed with Developer-Mode reg key +
  a `KIVYFORGE_REQUIRE_SYMLINKS` assertion that **fails loudly** if they'd skip.
  *Lesson: a conditionally-skipped test that never runs in CI is not coverage —
  assert that it ran.*
- **Version metadata mapping.** PEP 440 → four 16-bit fields cannot represent an
  epoch. *Lesson: state lossy mappings' limits explicitly and test the boundary.*
- **Silent config defaults.** A hidden `or "3.15.0"` Python-version fallback
  could pin an unreleased Python. *Lesson: surface missing required config as an
  error; never silently substitute.*

### 9. The agent/dev shell itself was a source of friction

- PowerShell has no `&&` statement separator (old versions) and no heredoc;
  commands had to be adapted (`;`, here-strings). *Lesson: confirm the shell
  dialect and quoting rules up front for any Windows automation.*

---

## What we'd do differently next time

1. **Stand up a "host-reality" checklist before writing platform code** —
   encoding, filesystem-mutation semantics, path length/case, line endings,
   toolchain-drift policy, clean-machine dependency discovery. Most surprises
   above were knowable in advance.
2. **Design artifact writes as atomic + rollback from line one**, in the shared
   layer, so no platform can regress it.
3. **Write integration + failure-atomicity tests alongside the happy path**, not
   after a reviewer notices the gap. Make at least the orchestration hermetic
   (fake network/host-tool leaves) so it runs on any CI OS.
4. **Prove host-independence on a clean VM early**, and keep the protocol as a
   re-runnable recipe (we did this for DLLs — do it as a *phase gate*, not a
   late confirmation).
5. **For every pinned toolchain, ship the un-pin / re-vendor path in the same
   PR**, and reference it in the failure message.
6. **Design `doctor` checks together with each feature** — treat every "you must
   have X installed / configured" assumption as a check, immediately.
7. **Audit shared invariants across all platforms in one pass** whenever one is
   added or changed.

---

## Carry-forward for the Android backend

Android is a different OS family, but almost every Windows surprise has a direct
Android analog. The point of this section is that we should **pre-empt** these,
not rediscover them.

| Windows learning | Android analog to pre-empt |
|---|---|
| MSVC toolset drift breaks reproducible launcher | **Gradle / AGP / build-tools / platform / NDK version drift.** Pin them, and have a re-pin/re-vendor path + clear errors from day one. |
| Bundle must carry its own runtime; don't borrow from host | **Bundle the Python + `.so` payload**; validate every native lib's ABI. p4a/`python-for-android` history is the reference here. |
| Arch validation via PE machine type (`petools`) | **ABI matrix** (`arm64-v8a`, `armeabi-v7a`, `x86_64`) — validate ELF `e_machine` per `.so`; the Windows arch work (and `arm64-windows.md`) is the template for a multi-arch story. |
| Authenticode signing (optional, thumbprint, timestamp) | **APK/AAB signing is mandatory**: keystore, `apksigner`, v1/v2/v3/v4 schemes, Play App Signing. Expect more required setup and more `doctor` checks; the signing-prerequisites doc is the model. |
| Windows file locking → atomic write-in-place | Less severe on a Linux build host, but **keep the atomic stage-then-swap invariant** for the output `.apk`/`.aab`. |
| Encoding not UTF-8 | Build host is usually UTF-8, but **subprocess output from Gradle/aapt/adb** still needs explicit decoding; keep the habit. |
| DLL discovery / load order | **`.so` load order, `System.loadLibrary`, `android:extractNativeLibs`, page-alignment (16 KB)**; the "discovery invariant" mindset transfers directly. |
| `runpy` `__main__` launch contract | Android entry is via a **Java/Kotlin activity → Python bootstrap** (SDL activity / p4a bootstrap); make the "how user code becomes `__main__`" contract explicit and identical in spirit. |
| Job object process-tree teardown | Android **process/service lifecycle** (the OS may kill/restart); decide degradation policy explicitly. |
| Clean-VM host-independence gate | **Clean emulator / physical device matrix** as a phase gate (install → cold start → open window offline). |
| CI symlink tests silently skipping | Android CI needs **emulator/AVD or device**; assert the on-device smoke test actually ran rather than skipping when no device is attached. |
| PowerShell dialect friction | Android tooling shells out heavily (Gradle wrapper, `sdkmanager`, `adb`); pin tool locations and resolve them explicitly. |

**Android-specific things to design up front (no Windows analog):**

- **Two shippable formats** (`.apk` for sideload/CI, `.aab` for Play) vs.
  Windows/Desktop's single folder artifact — decide the scope boundary early
  (mirror the "installers are external" scope decision).
- **Manifest + permissions + resource merging** is a large declarative surface;
  budget for it like we budgeted for `Info.plist`/`.desktop`/version resources
  combined.
- **Licensing / SDK acceptance** (`sdkmanager --licenses`) is a `doctor`/first-run
  concern.
- **Emulator vs. device** testing cost is real; plan the hermetic-vs-live test
  split (as we did with the launcher: hermetic orchestration tests + a small
  live smoke gate).

---

## Pointers (where the lessons live in code)

- Atomic write-in-place: `platforms/windows/fsswap.py`, and the mirrored
  macOS/Linux fixes in `platforms/macos/bundle.py`, `platforms/linux/appimage.py`.
- Arch validation: `platforms/windows/petools.py`,
  `platforms/windows/runtime_stage.py`.
- Reproducibility + re-vendor: `platforms/windows/launcher/build_launcher.py`,
  the `windows_launcher` / `revendor_launcher` jobs in
  `.github/workflows/kivyforge.yml`.
- Process-tree teardown: `platforms/windows/launcher/launcher.c`.
- `doctor` environment probes: `doctor/probe.py`,
  `platforms/windows/doctor.py`.
- Clean-machine findings: [windows-dll-findings.md](windows-dll-findings.md).
- Forward-looking multi-arch template:
  [arm64-windows.md](../platforms/windows/arm64-windows.md).
