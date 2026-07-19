# Spike brief: publish pyjnius as a prebuilt Android wheel

**Audience:** an engineer or coding agent working **inside the `kivy/pyjnius`
repository**. This brief is self-contained — you do not need any context about
the project that requested it. Everything you need to know is here.

**One-line objective:** determine whether — and how — `pyjnius` can be built and
published as a **prebuilt PEP 738 Android wheel** (`android_*` tags) that a
downstream tool can `pip install` (never compiling pyjnius from source per app)
and load at runtime inside an Android app that provides a **documented bootstrap
contract** — specifically an **SDL3 host** that has loaded `libSDL3.so` (which
supplies the JVM `JNIEnv`) before the first `import jnius`.

> **This brief was updated 2026-07 after verified downstream research** — see
> [Findings update](#findings-update-2026-07) immediately below. In short: the
> earlier "`-lmain`" description was **wrong**; the real coupling is **SDL**; the
> one symbol problem (SDL2→SDL3) already has a **known, verified two-line fix**;
> **no prior-art wheel exists anywhere**; and the recommended scope is narrowed
> from a fully *app-agnostic* wheel to one that relies on a **kivyforge-defined
> bootstrap contract**. Read the update first — it supersedes the original §2
> where they conflict.

This is a **spike**: the primary deliverable is a *working proof + a findings
document*, not a finished, merged release pipeline. If it proves easy, produce
the wheels; if it proves hard, document exactly what blocks it.

---

## Findings update (2026-07)

Verified against `kivy/pyjnius` master, `kivy/python-for-android`, SDL docs, PyPI,
the Chaquopy index, and the kivy-school (`ksp`) ecosystem. This section
**supersedes the original §2** where they differ.

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

### No pyjnius Android wheel exists anywhere (confirmed exhaustively)

Not merely "not on PyPI":

- **PyPI:** no `android_*` tag in any release, including current 1.7.0.
- **Chaquopy index** (`chaquo.com/pypi-13.1/`): pyjnius absent — Chaquopy has its
  own Java bridge (`from java import …`) and never needed it.
- **conda-forge:** has pyjnius, but desktop-only.
- **p4a:** still compiles pyjnius from source per app (`PyProjectRecipe`,
  `hostpython_prerequisites = ["Cython<3.2"]`).

There is **no existing artifact to adapt** — whatever this spike builds
establishes the first one.

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

- The single "hard" runtime problem (JNIEnv) is **already solved** by SDL + the
  known SDL3 patch.
- The Java-glue-delivery problem is **solved by convention** (dot-directory).
- The remaining work is mechanical: apply the patch, link SDL3 as external, ship
  the Java glue by convention, and confirm load under an SDL3 host on-device.
- **Scope is narrowed to path 2** (bootstrap-contract wheel); the app-agnostic
  ideal (path 1) is explicitly *not* required.

---

## 1. Why this is not already solved

Today pyjnius has **no Android wheel on PyPI**; downstream build tools
(python-for-android / Buildozer) compile it **from source per project**. Confirm
the current state yourself:

```bash
pip install --only-binary=:all: --platform android_24_arm64_v8a \
    --python-version 3.14 --target /tmp/x pyjnius
# Expected today: "No matching distribution found for pyjnius"
```

The context that makes wheels now possible:

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

1. **Reproduce the gap** (the `pip` command in §1) and record it.
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
   - a short recommendation: is a maintained pyjnius Android-wheel release
     realistic, and what would it take (CI, cadence, ABI/API matrix)?
3. **A minimal reproducible build config** (cibuildwheel settings in
   `pyproject.toml` / a CI workflow) so the result is re-runnable.

## 7. Constraints & gotchas

- **Host:** build on **Linux `x86_64`** or **macOS** with an Android SDK; let
  cibuildwheel manage the NDK via `sdkmanager`. Windows cannot build Android
  wheels.
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
- Reusable bootstrap / Java-glue prior art (dot-directory `.java`/`.libs`/`.gradle`
  convention) — <https://github.com/kivy-school/ksp-bootstraps>
- Evidence of the missing wheel —
  <https://github.com/kivy/python-for-android/issues/3342>
