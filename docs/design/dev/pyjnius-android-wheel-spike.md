# Spike brief: publish pyjnius as a prebuilt Android wheel

> **Spike complete — findings committed (2026-07).** This is the *pre-spike*
> brief, kept for history. The executed spike's status and on-device evidence
> live in
> [pyjnius-android-wheel-spike-findings](pyjnius-android-wheel-spike-findings.md),
> and the upstream-facing proposal (updated with the post-spike direction) in
> [pyjnius-android-wheel-proposal](pyjnius-android-wheel-proposal.md). Where this
> brief and the findings disagree — notably `dlsym(RTLD_DEFAULT, …)` resolution
> (falsified on-device; each tier `dlopen`s the library by soname) and the
> `.java/` dot-directory glue delivery (dropped; the glue is a kivyforge
> bootstrap template) — **the findings supersede this brief.**

**Audience:** an engineer or coding agent working **inside the `kivy/pyjnius`
repository**. This brief is self-contained — you do not need any context about
the project that requested it. Everything you need to know is here.

**One-line objective:** produce a **first-party, reproducible, PEP 738 Android
wheel** for `pyjnius` (`android_*` tags) — ideally **one universal build that
works against SDL2 *and* SDL3** (SDL3-only is the acceptable fallback) for
**current CPython (3.14 + the 3.15 pre-release)**, hash-pinnable — that a
downstream tool can
`pip install` (never compiling pyjnius from source per app) and load at runtime
inside an Android app providing a **documented bootstrap contract** (a host with
an in-process JVM — a Kivy/SDL app — reachable at `import jnius`). Community
wheels already prove this is possible (see the Findings update); the goal is a
first-party, universal-SDL (SDL2+SDL3) / 3.15-capable version **published to
PyPI** that kivyforge (and any packager) consumes and pins by URL + SHA-256 — see
[Distribution model](#distribution-model-publish-upstream-to-pypi-recommended).

> **This brief was updated 2026-07 after verified downstream research** — see
> [Findings update](#findings-update-2026-07) immediately below. In short: the
> earlier "`-lmain`" description was **wrong**; the real coupling is **SDL**; the
> one symbol problem (SDL2→SDL3) already has a **known, verified two-line fix**;
> **working prebuilt pyjnius Android wheels already exist** (the `kivyschool`
> Anaconda channel, built by the `pyjnius-builder` PEP 517 backend and consumed
> by the `ksproject` toolchain); and the recommended scope is narrowed from a
> fully *app-agnostic* wheel to one that relies on a **kivyforge-defined
> bootstrap contract**. Read the update first — it supersedes the original §2
> where they conflict.

This is a **spike**: the primary deliverable is a *working proof + a findings
document*, not a finished, merged release pipeline. If it proves easy, produce
the wheels; if it proves hard, document exactly what blocks it.

---

## Findings update (2026-07)

Verified against `kivy/pyjnius` master, `kivy/python-for-android`, SDL docs, PyPI,
the Chaquopy index, the **`kivyschool` Anaconda channel**, `pyjnius-builder`, and
the kivy-school (`ksp`) ecosystem. This section **supersedes the original §2**
where they differ.

### The real Android coupling is SDL, not `libmain` (corrects §2)

The original brief claimed pyjnius links `-lmain` against the app's `libmain.so`
(citing p4a's `PYJNIUS_ANDROID_LIBMAIN`). **That is p4a's build layer, not
upstream pyjnius.** Direct inspection of `kivy/pyjnius` master shows the coupling
is **SDL**, in two parts:

1. An explicit **link-time dependency on `libSDL2.so`** — `jnius/env.py`:

   ```python
   class AndroidJavaLocation(UnixJavaLocation):
       def get_libraries(self):
           return ['SDL2', 'log']   # -> links -lSDL2 -llog
   ```

2. An **undefined symbol reference** to `SDL_AndroidGetJNIEnv`, resolved at load
   time from the SDL library the host has already loaded — `jnius/jnius_jvm_android.pxi`:

   ```cython
   # on android, rely on SDL to get the JNI env
   cdef extern JNIEnv *SDL_AndroidGetJNIEnv()
   cdef JNIEnv *get_platform_jnienv() except NULL:
       return <JNIEnv*>SDL_AndroidGetJNIEnv()
   ```

So the JVM `JNIEnv` is **not** an open research question (no `JNI_GetCreatedJavaVMs`
gymnastics needed): pyjnius gets it from SDL. The wheel must (a) link against SDL
as an **external, host-provided** library — not bundle it — and (b) rely on the
host bootstrap having loaded `libSDL*.so` (globally) before `import jnius`.

### SDL2→SDL3 is the one real breakage, and the fix already exists (verified)

SDL3 renamed the symbol: **`SDL_AndroidGetJNIEnv` (SDL2) → `SDL_GetAndroidJNIEnv`
(SDL3)** (`SDL3/SDL_system.h`, since 3.2.0, returns `void*`). p4a already ships a
working, verified patch — `pythonforandroid/recipes/pyjnius/sdl3_jnienv_getter.patch`
— two one-line edits:

```diff
--- a/jnius/env.py
+++ b/jnius/env.py
 class AndroidJavaLocation(UnixJavaLocation):
     def get_libraries(self):
-        return ['SDL2', 'log']
+        return ['SDL3', 'log']
--- a/jnius/jnius_jvm_android.pxi
+++ b/jnius/jnius_jvm_android.pxi
-cdef extern JNIEnv *SDL_AndroidGetJNIEnv()
+cdef extern JNIEnv *SDL_GetAndroidJNIEnv()
 cdef JNIEnv *get_platform_jnienv() except NULL:
-    return <JNIEnv*>SDL_AndroidGetJNIEnv()
+    return <JNIEnv*>SDL_GetAndroidJNIEnv()
```

**Reuse this patch; do not re-derive it.** p4a's current pyjnius recipe supports
both SDL2 and SDL3 (`depends = [('genericndkbuild', 'sdl2', 'sdl3'), 'six']`),
applying `sdl3_jnienv_getter.patch` conditionally via `will_build('sdl3')`.

### Prior art exists: prebuilt pyjnius Android wheels are already published

> **Correction.** An earlier version of this brief stated "no pyjnius Android
> wheel exists anywhere." **That was wrong** — it checked PyPI/Chaquopy/conda-forge
> but not Anaconda.org *channels*. Working wheels exist and there is a reusable
> build backend. This changes the spike from "prove it's possible" to "reproduce
> it as an SDL3 / 3.15 build that kivyforge controls and pins."

- **Prebuilt wheels — the `kivyschool` Anaconda channel**
  (`https://pypi.anaconda.org/kivyschool/simple/pyjnius/`) publishes, today:

  ```
  pyjnius-1.7.0-cp313-cp313-android_21_arm64_v8a.whl
  pyjnius-1.7.0-cp313-cp313-android_21_x86_64.whl
  pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl
  pyjnius-1.7.0-cp314-cp314-android_24_x86_64.whl
  ```

- **Build backend — `pyjnius-builder`**
  (`github.com/kivy-school/pyjnius-builder`): a **PEP 517 build backend** that
  compiles the per-ABI extension and **injects the Java glue into the wheel's
  `.java/`** from `[tool.pyjnius].java-paths`. This *is* the reference recipe —
  reuse or port it rather than starting from scratch. (Sibling: `ksp-builder`,
  which injects `.gradle/<pkg>.json`.)
- **Consumer — `ksproject`** resolves the wheel with a plain
  `uv pip install --python-platform <arch> --extra-index-url <pyswift + kivyschool
  channels>`, then extracts the wheel's dot-directories (`.java/`, `.libs/<abi>/`,
  `.gradle/*.json`) into a generated AGP project (Gradle tasks
  `copySitePackagesJava` / `copySitePackagesNativeLibs_<abi>` / …). **No
  pyjnius-specific handling** — it relies entirely on the wheel + the bootstrap
  load-order guarantee.

Still absent (so publishing an *official/first-party* wheel remains valuable):

- **PyPI / Chaquopy index / conda-forge:** no Android pyjnius wheel.
- The `kivyschool` wheels are **community-run**, cover only **cp313/`android_21`**
  and **cp314/`android_24`**, and are almost certainly **SDL2**-linked (ksproject
  ships SDL2 2.30.11). There is **no SDL3 build, no 3.15, and nothing published
  first-party to PyPI** — which is exactly what this spike should produce (see
  [Distribution model](#distribution-model-publish-upstream-to-pypi-recommended)).

### Kivy itself is already wheel-available: pyjnius is the sole keystone

The `kivyschool` channel also publishes **Kivy 2.3.1 Android wheels** for exactly
the interpreters that matter:

```
Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl
Kivy-2.3.1-cp314-cp314-android_24_x86_64.whl   (also cp313)
```

CPython 3.14 is stable and Tier 3 on Android, so the interpreter and the
framework gates are effectively cleared. That leaves **pyjnius as the single
remaining first-party keystone** for a wheel-only Android stack. Note that Kivy
2.3.1 is an **SDL2** framework, so a pyjnius wheel that works against SDL2 (or,
per the [universal-wheel decision](#design-decision-one-universal-wheel-for-sdl2-and-sdl3-resolve-the-jnienv-at-runtime),
SDL2 *and* SDL3) lets kivyforge target **Kivy 2.3.1 on SDL2 now** and carry the
*same* pyjnius artifact forward to **Kivy 3.0 on SDL3** later.

One packaging caveat independent of pyjnius: Kivy 2.3.1 on Android still needs
the **SDL2 runtime `.so`s** (`libSDL2.so`, `SDL2_image/mixer/ttf`) present in the
APK and loaded before import — that is the bootstrap's job (p4a bootstrap, or
`kivy_deps` libs + an ordered loader). pyjnius only *finds* the `JNIEnv` from a
loaded SDL; something else must *package and load* SDL.

### Three paths (the wheel is not the only option)

The SDL3/JNIEnv fix above is a **two-line patch that applies identically to all
three**, so it is independent of the packaging decision:

1. **Standalone, app-agnostic wheel** — the original framing. Hardest: would
   require solving library coupling + Java-glue delivery for *any* host. Matches
   no known precedent.
2. **Wheel scoped to a kivyforge bootstrap contract (recommended).** Build the
   SDL3-patched pyjnius as an ordinary prebuilt wheel via cibuildwheel, and let
   the **kivyforge Android bootstrap guarantee `libSDL3.so` is loaded before
   Python imports run**, so the undefined SDL symbol resolves. This is how the
   `ksproject` toolchain already resolves pyjnius today — its `PipInstaller`
   runs a plain `uv pip install --python-platform <arch>` with **zero
   pyjnius-specific handling**, relying entirely on the bootstrap load-order
   guarantee. Much smaller commitment; changes the acceptance criteria (below).
3. **Compile pyjnius in-build via Gradle/CMake, no wheel** — viable and cheap
   (pyjnius is one Cython-generated `.c` + one small Java class; negligible next
   to CPython/SDL). A deliberate, documented exception to the "consume prebuilt
   artifacts" principle (precedent: the iOS backend already defers real
   compilation to Xcode/SPM).

### Reusable prior art in the kivy-school ecosystem

Beyond the ready-made wheel + `pyjnius-builder` recipe above, the broader `ksp`
stack has directly reusable pieces:

- **`ksp-bootstraps`** (`github.com/kivy-school/ksp-bootstraps`): MIT, `Protocol`
  -based reusable Gradle/Xcode project generator. Early (`0.0.1.postN`), and its
  `main.c` currently targets **SDL2** — reusing it still needs the same SDL3 port.
- **Dot-directory wheel convention** (`.java/`, `.kotlin/`, `.libs/<abi>/`,
  `.gradle/*.json`, via `ksp-builder`/`pyjnius-builder` PEP 517 backends): a
  general mechanism for a pip package to inject Java/Kotlin sources, prebuilt
  native libs, and Gradle deps/permissions into a generated Android project.
  **This solves the Java-glue-delivery problem generically** and is worth
  adopting for kivyforge's native-binaries channel (common design doc 08).
- **p4a Java-namespace preservation** (`org.kivy.android.*`) in the bootstrap
  templates — so Plyer-style `autoclass('org.kivy.android.PythonActivity')` keeps
  working unmodified.

### Net effect on this spike

- **A working wheel + build recipe already exist** (kivyschool channel +
  `pyjnius-builder`), so the spike is no longer "prove a wheel is possible" — it
  is **"reproduce it as a first-party, SDL3, 3.15-capable build that kivyforge
  pins by URL + hash."**
- The single "hard" runtime problem (JNIEnv) is **already solved** by SDL + the
  known SDL3 patch.
- The Java-glue-delivery problem is **solved by convention** (dot-directory, via
  `pyjnius-builder`).
- The remaining work is mechanical: (re)build from the `pyjnius-builder` recipe
  for the target CPython/ABIs, **publish to PyPI** (see the next section), and
  confirm load under a conforming host on-device.
- **Scope is narrowed to path 2** (bootstrap-contract wheel); the app-agnostic
  ideal (path 1) is explicitly *not* required.

---

## Distribution model: publish upstream to PyPI (recommended)

**Recommendation:** publish official `android_*` pyjnius wheels **from
`kivy/pyjnius` to PyPI**, not to a private/community index. Build *toward* a PyPI
release — it is the target distribution model for this spike.

Why PyPI-from-source rather than a private index:

- It is exactly what **PEP 738** called for ("until prominent libraries routinely
  release their own Android wheels… adoption will be limited"). pyjnius is a
  keystone library; a first-party release is a lighthouse for the ecosystem.
- **First-party beats a community channel** for any consumer that pins by
  URL + SHA-256: no extra index, no single-maintainer supply-chain risk,
  canonical provenance. (The `kivyschool` channel is the proof of concept; PyPI
  is the production home.)
- It helps every packager (p4a, Briefcase, kivyforge), not just one.

### Design decision: one universal wheel for SDL2 *and* SDL3 (resolve the `JNIEnv` at runtime)

**Goal: a single `android_*` wheel that works with an SDL2 host *or* an SDL3 host
(and, ideally, any in-process-JVM host).** This is strategically important, not
just tidy: it decouples pyjnius from the SDL/Kivy *generation*, so **the same
wheel serves Kivy 2.3.1 (SDL2) today and Kivy 3.0 (SDL3) later** — no
per-generation rebuild, no forked wheels (see the [Kivy-wheel
note](#kivy-itself-is-already-wheel-available-pyjnius-is-the-sole-keystone)).

The only thing that pins a build to a single SDL generation is the *link-time*
symbol name (`SDL_AndroidGetJNIEnv` for SDL2 vs `SDL_GetAndroidJNIEnv` for SDL3)
plus a hard SDL `DT_NEEDED`. Remove both and one wheel spans both:

1. **Drop the hard SDL link.** Change `get_libraries()` from `['SDL2', 'log']`
   (or `['SDL3', 'log']`) to **`['log']`** so the `.so` carries **no
   `DT_NEEDED` on any `libSDL*.so`** — a specific SDL soname is exactly what
   would otherwise lock the wheel to one generation and make it fail to `dlopen`
   against the other.
2. **Resolve the `JNIEnv` at runtime**, taking whichever is present:
   - `dlsym(RTLD_DEFAULT, "SDL_GetAndroidJNIEnv")` (SDL3) → else
   - `dlsym(RTLD_DEFAULT, "SDL_AndroidGetJNIEnv")` (SDL2) → else
   - `JNI_GetCreatedJavaVMs` + `AttachCurrentThread` (SDL-independent; also
     covers non-SDL hosts).

   Because the host loads its SDL into the app's global linker namespace before
   Python imports pyjnius, `RTLD_DEFAULT` finds whichever getter exists. The
   dlsym-of-SDL path is the *sure* one — a Kivy host always has SDL loaded and
   exports the getter (this is proven; it is how p4a resolves it today). The
   `JNI_GetCreatedJavaVMs` fallback is a bonus whose dlsym-resolvability varies by
   API level/runtime, so treat it as best-effort, not the primary.

This turns the runtime contract from "you must be an SDL3 app" into the weaker,
honest **"an in-process JVM exists (+ the Java glue is on the classpath)"** — the
right promise for something on PyPI. It is a small, low-risk upstream change to
`jnius/env.py` (drop SDL from linked libs) plus a few lines of runtime resolution
in `jnius_jvm_android.pxi`. If the runtime lookup proves too fiddly, an
**SDL3-only** wheel (the two-line patch from the Findings update) is the
acceptable fallback — but the universal (SDL2-or-SDL3) build is preferred for
public distribution.

### Contract to standardize (co-design with p4a)

The wheel's residual runtime contract (§2) must be **documented in pyjnius** and
ideally **agreed with the p4a maintainers**, so there is *one* contract rather
than per-bootstrap variants:

- an in-process JVM discoverable at import (per the runtime lookup above);
- the wheel's `.java/` glue compiled/dexed into the app, with the
  **`org.kivy.android.*` namespace preserved** (so Plyer-style
  `autoclass('org.kivy.android.PythonActivity')` keeps working — this *is* "Kivy
  Android compatibility");
- **fail loudly** — a missing JVM/glue raises a clear `ImportError` ("pyjnius'
  Android wheel needs a host that provides an in-process JVM; see <link>"), not a
  cryptic dlopen/symbol failure, so e.g. a Termux user gets guidance.

### Ownership & consumption

- This is a **maintainer commitment** on `kivy/pyjnius` (CI, release cadence, the
  CPython × ABI × API matrix, NDK-drift re-pins). Do it **as an upstream PR**, not
  a fork — p4a already maintains the SDL3 patch and dual-SDL support, so upstream
  is receptive.
- **kivyforge then consumes the PyPI wheel pinned by URL + SHA-256** (no extra
  index), ships the **bootstrap that satisfies the contract**, and keeps the
  **Gradle-source compile as a fallback** for CPython/ABI combos not yet
  published.

---

## 1. Starting point — what exists and what's missing

pyjnius has **no Android wheel on PyPI** (so a default `pip install` still
fails), but **community prebuilt wheels exist on the `kivyschool` Anaconda
channel** (see the Findings update). Confirm both yourself:

```bash
# PyPI: still nothing
pip install --only-binary=:all: --platform android_24_arm64_v8a \
    --python-version 3.14 --target /tmp/x pyjnius
# -> "No matching distribution found for pyjnius"

# kivyschool channel: wheels are present
pip install --only-binary=:all: --platform android_24_arm64_v8a \
    --python-version 3.14 --target /tmp/y pyjnius \
    --extra-index-url https://pypi.anaconda.org/kivyschool/simple
# -> resolves pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl
```

The job is to turn that community proof into a **first-party, SDL3,
3.15-capable, hash-pinned** wheel. The context that makes this straightforward:

- Android is a **CPython Tier 3 platform** since 3.13 (PEP 738); wheel tags are
  `android_<apilevel>_<abi>` (ABIs: `arm64_v8a`, `armeabi_v7a`, `x86_64`, `x86`).
- **PyPI accepts** `android_*` wheels; **pip ≥ 25.1 installs** them.
- **cibuildwheel ≥ 3.1** can build Android wheels on a Linux `x86_64` / macOS
  host (it drives the NDK via `sdkmanager`), with auditwheel grafting external
  `.so`s. This is the intended build tool for this spike.

## 2. The core technical problem (corrected — see Findings update)

> The verified [Findings update](#findings-update-2026-07) supersedes an earlier
> version of this section that described a `-lmain`/`libmain.so` coupling. The
> real coupling is **SDL**, and the hard part is already solved. This section is
> the corrected, condensed statement.

pyjnius is **not fully self-contained** on Android, but its coupling is small,
well-understood, and satisfiable by a host **bootstrap contract**:

1. **SDL library + `JNIEnv` symbol.** pyjnius links `SDL2`/`log`
   (`jnius/env.py` → `['SDL2', 'log']`) and calls the **undefined** symbol
   `SDL_AndroidGetJNIEnv` (`jnius/jnius_jvm_android.pxi`) to obtain the JVM
   `JNIEnv` at runtime. The wheel must link SDL as an **external, host-provided**
   library (do **not** bundle/graft it) and rely on the host having loaded
   `libSDL*.so` globally before `import jnius`. **SDL3 rename:** apply p4a's
   verified `sdl3_jnienv_getter.patch` (`SDL_AndroidGetJNIEnv` →
   `SDL_GetAndroidJNIEnv`, `SDL2` → `SDL3`). This is the whole "JNIEnv problem" —
   no `JNI_GetCreatedJavaVMs` fallback is required for an SDL host.
2. **Java-side glue on the classpath.** pyjnius needs a small amount of **Java**
   (e.g. `org.jnius.NativeInvocationHandler`, used to implement Java interfaces
   from Python). A `.whl` carries no `.dex`, so the glue must reach the APK's
   dex — **solved by the dot-directory convention** (`.java/` in the wheel,
   compiled/dexed by the app project generator); see the Findings update.

**Residual runtime contract the host must satisfy** (document it precisely — it
is what the downstream packager guarantees, and it is the whole point of scoping
to path 2 rather than an app-agnostic wheel):

- `libSDL3.so` (or `libSDL2.so`, matching the build) is **loaded, with global
  symbol visibility, before the first `import jnius`**.
- The wheel's `.java/` glue is compiled and dexed into the APK.
- An in-process JVM (always true on Android) with the app's classpath.

## 3. Scope

**In scope**

- Build pyjnius wheels for **`arm64_v8a`** and **`x86_64`** (min two ABIs),
  targeting **`ANDROID_API_LEVEL=24`** (cibuildwheel default), for the target
  CPython versions: **3.14 (current stable)** and **3.15**. 3.15 is not final
  until **October 2026**, so target its **pre-release** (`3.15.0bN`/`rcN`), which
  cibuildwheel builds via its `cpython-prerelease` enable flag — 3.15 is a real
  target, not optional (the requesting project already ships on the 3.15
  pre-release for iOS, sourcing it from python.org). The two
  ABIs play different roles: **`arm64_v8a` is the real-device shipping target**
  (essentially all modern Android hardware is arm64), while **`x86_64` is the
  *testability* ABI** — cibuildwheel's testbed runs the on-device smoke test on a
  Gradle emulator **matching the build host's architecture**, and build hosts are
  x86_64 (Linux / Intel macOS), where the x86_64 system image runs near-native
  (KVM/HAXM) but an arm64 emulator would need slow full-CPU emulation. So the
  x86_64 wheel is the one you can actually *load and validate at speed* in CI (and
  in the Android Studio emulator during development); arm64_v8a builds but skips
  on-device testing on an x86_64 host (see §7).
- **Target path 2** (a wheel scoped to a kivyforge bootstrap contract), not the
  app-agnostic ideal — see the Findings update. If path 3 (in-build compile)
  proves cleaner for the requesting project, record that recommendation; the
  SDL3 patch applies either way.
- Apply p4a's `sdl3_jnienv_getter.patch` and build so pyjnius links **SDL3 as an
  external, host-provided** library (not bundled/grafted), completing with **no
  app present**.
- Deliver the Java glue via the **dot-directory convention** (`.java/` in the
  wheel) and document the residual host contract (§2).
- Pre-generate `jnius.c` from `jnius.pyx` at build/pin time so **Cython is not a
  build dependency** for consumers of the wheel.
- A reproducible cibuildwheel-based build (pin the NDK/API level).

**Out of scope**

- A perfect, production release pipeline / PyPI publish automation (note what it
  would take, but the deliverable is a proof + findings).
- Non-Android platforms (do not regress desktop builds, but no new work there).
- Downstream packagers' internals — you only need a minimal harness to *load and
  smoke-test* the wheel inside an app/emulator.

## 4. Concrete tasks

1. **Establish the starting point:** confirm PyPI has no wheel *and* the
   `kivyschool` channel does (both `pip` commands in §1); study the
   `pyjnius-builder` recipe and a downloaded kivyschool wheel's layout (per-ABI
   `.so`, injected `.java/`) as your baseline to reproduce and extend.
2. **Stand up a cibuildwheel Android build** for pyjnius on a Linux `x86_64` (or
   macOS) host:
   - `pipx run cibuildwheel --platform android` (or pinned in
     `pyproject.toml`/CI), building `cp314-android_arm64_v8a` and
     `cp314-android_x86_64`.
   - Use the `build`/`uv` frontend (Android does **not** support the `pip`
     frontend).
3. **Apply the SDL3 patch and fix the build** so it completes with **no app
   present**:
   - Apply p4a's `sdl3_jnienv_getter.patch` (`SDL2`→`SDL3`,
     `SDL_AndroidGetJNIEnv`→`SDL_GetAndroidJNIEnv`).
   - Link **SDL3 as an external, host-provided** library — allow the SDL symbol
     to remain undefined/resolved at load time; do **not** bundle or graft
     `libSDL3.so` (document the exact linker flags).
   - Pre-generate `jnius.c` from `jnius.pyx` (Cython as a build-only tool); ensure
     it compiles against NDK clang for each ABI.
4. **Make it load at runtime** inside a real **SDL3** Android process:
   - Ensure `libSDL3.so` is loaded (globally) **before** `import jnius`, per the
     host contract (§2).
   - Verify `autoclass('java.lang.System').getProperty('java.version')` (or
     similar) returns from Python running on an emulator/device.
   - Use the **CPython Android "testbed"** app (the same harness cibuildwheel
     uses for tests) or a minimal SDL3/Gradle app to load the wheel and run a
     smoke test on a **Gradle-managed emulator** matching the build arch.
5. **Resolve the Java glue delivery** and demonstrate an interface-implementation
   round-trip (Python implementing a Java interface via
   `NativeInvocationHandler`) working from the installed wheel.
6. **Pin for reproducibility:** record exact NDK version, `ANDROID_API_LEVEL`,
   cibuildwheel version, CPython version(s); note the re-pin path.
7. **Write the findings** (§6 deliverable).

## 5. Acceptance criteria

The spike **succeeds** if all of the following hold:

- [ ] `pyjnius` builds to `android_24_arm64_v8a` **and** `android_24_x86_64`
      wheels via cibuildwheel, **with no host app present at build time**.
- [ ] `pip install --only-binary=:all: --platform android_24_arm64_v8a
      --python-version 3.14 --target <dir> <the built wheel>` installs cleanly.
- [ ] The installed wheel **imports and runs on an emulator/device** under an
      SDL3 host: `autoclass` resolves a JVM class and calls a method, with the
      `JNIEnv` obtained via SDL (`SDL_GetAndroidJNIEnv`) after the host loaded
      `libSDL3.so`.
- [ ] A Python-implements-Java-interface round-trip works (Java glue delivery
      solved and documented).
- [ ] The build is reproducible from pinned inputs (NDK/API/toolchain recorded).

If any criterion cannot be met, the spike still **succeeds as a spike** provided
the findings document precisely *why* (the exact blocker), so the decision can be
made with evidence.

## 6. Deliverables

1. **Wheels** for the two ABIs (attach as artifacts), or a clear statement of why
   they can't be produced.
2. **A findings document** in the pyjnius repo (e.g.
   `docs/android-wheel-spike.md`) covering:
   - what worked / what didn't, with commands and logs;
   - the exact approach taken for the §2 coupling (SDL3 external link + the
     `SDL_GetAndroidJNIEnv` symbol, and Java-glue delivery) — including linker
     flags and the applied patch;
   - the pinned toolchain (NDK, API level, cibuildwheel, CPython versions) and
     reproducibility notes;
   - **residual runtime contract**: precisely what the *host app* must still
     provide for the wheel to work (e.g. an in-process JVM, a specific symbol,
     the dexed Java glue) — this is what downstream packagers must guarantee;
   - a recommendation on the **PyPI publication path** (per the Distribution
     model section): is a maintained, upstream-published pyjnius Android-wheel
     release realistic, and what would it take (CI, cadence, ABI/API matrix, the
     runtime-JNIEnv-lookup decision, and the documented runtime contract)?
3. **A minimal reproducible build config** (cibuildwheel settings in
   `pyproject.toml` / a CI workflow) so the result is re-runnable.

## 7. Constraints & gotchas

- **Host OS:** build on a **Linux `x86_64`** or **macOS** host (WSL2 counts as
  Linux) with an Android SDK; let cibuildwheel manage the NDK via `sdkmanager`.
  **Native Windows is unsupported *as the build host*** — this is a host-OS
  limitation of cibuildwheel / the Android build tooling (which is POSIX-shell
  oriented), **not** a lack of cross-compilation: the build always
  cross-compiles to the `arm64_v8a`/`x86_64` Android (bionic) target regardless
  of the host CPU, so an `x86_64` Linux host builds `arm64_v8a` wheels fine.
- **Frontend:** `build` / `build[uv]` / `uv` only — **not `pip`**.
- **API level:** default `ANDROID_API_LEVEL=24` (first with RUNPATH, needed by
  auditwheel; ~99% device coverage). Don't lower it without reason.
- **Testing:** only the **build-machine architecture** can be tested on the
  emulator; other ABIs build but skip on-device tests — plan the matrix
  accordingly.
- **Toolchain drift:** NDK/SDK/build-tools versions roll forward and drop old
  ones. **Pin them**, and make the pin easy to refresh.
- **Do not regress** desktop/other-platform builds.

## 8. Key references

- PEP 738 (Android as a supported platform) — <https://peps.python.org/pep-0738/>
- Android platform tags —
  <https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#android>
- cibuildwheel Android — <https://cibuildwheel.pypa.io/en/stable/platforms/#android>
- CPython Android runtime + testbed —
  <https://www.python.org/downloads/android/>,
  <https://github.com/python/cpython/issues/131531>
- pyjnius Android coupling (SDL) — `jnius/env.py` (`AndroidJavaLocation`) and
  `jnius/jnius_jvm_android.pxi` in <https://github.com/kivy/pyjnius>
- SDL3 `JNIEnv` rename — `SDL_GetAndroidJNIEnv` in `SDL3/SDL_system.h`; p4a fix
  `pythonforandroid/recipes/pyjnius/sdl3_jnienv_getter.patch` + the pyjnius recipe
  in <https://github.com/kivy/python-for-android>
- **Prior-art wheels + build recipe + consumer** —
  <https://pypi.anaconda.org/kivyschool/simple/pyjnius/> (published wheels),
  <https://github.com/kivy-school/pyjnius-builder> (PEP 517 backend),
  <https://github.com/kivy-school/ksproject> (resolve + dot-dir extraction)
- Reusable bootstrap / Java-glue prior art (dot-directory `.java`/`.libs`/`.gradle`
  convention) — <https://github.com/kivy-school/ksp-bootstraps>
- pyjnius still compiled-from-source in p4a (context) —
  <https://github.com/kivy/python-for-android/issues/3342>
