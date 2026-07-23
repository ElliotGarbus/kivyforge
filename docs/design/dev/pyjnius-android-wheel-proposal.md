# Proposal: publish pyjnius as a prebuilt Android wheel

> **Provenance.** Copied 2026-07-23 from the spike working repo (`~/pyjnius-spike`
> in WSL — a clone of `ElliotGarbus/pyjnius`, branch `spike/android-universal-wheel`),
> where it was authored as `ANDROID_WHEEL_PROPOSAL.md`. It is the upstream-facing
> brief with the post-spike "outcome & revised direction" preamble; the full
> evidence record is [pyjnius-android-wheel-spike-findings](pyjnius-android-wheel-spike-findings.md).

**Audience:** a pyjnius maintainer or contributor. This document is
self-contained.

**Objective:** produce **first-party, reproducible, PEP 738 Android wheels** for
pyjnius (`android_*` tags), published to **PyPI** and hash-pinnable, so that any
downstream Android packager (python-for-android, Briefcase, and others) can
`pip install` pyjnius instead of compiling it from source per app. The wheels
should target **current CPython (3.14 stable + the 3.15 pre-release)** and,
ideally, be **universal across SDL2 and SDL3** (see
[the universal-wheel decision](#design-decision-one-universal-wheel-for-sdl2-and-sdl3)).

This is scoped as a **spike**: the primary deliverable is a *working proof plus a
findings write-up*, not a finished release pipeline. If it proves easy, produce
the wheels; if it proves hard, document exactly what blocks it.

---

## Spike outcome & revised direction (2026-07-20)

> This proposal predates the spike and is preserved as the **upstream-facing
> brief**. The spike validated the core technical bet but **narrowed the scope**.
> Where this document and the points below disagree, the points below win; the
> empirical corrections to §3–§4 are also folded in inline. Full status and
> on-device evidence live in
> [pyjnius-android-wheel-spike-findings](pyjnius-android-wheel-spike-findings.md).

**Proved on device (incl. real arm64 hardware — Pixel 8a, Android 16 / API 36):**
the SDL-agnostic wheel builds with no host app present, resolves the `JNIEnv` at
runtime with **no `DT_NEEDED` on libSDL**, and round-trips both `autoclass` and the
Python-implements-a-Java-interface path (`@java_method` → `invoke0`). The upstream
`ANDROID_ARGUMENT` thread-detach hook fires, pyjnius attaches to the host VM without
`JNI_CreateJavaVM`, and the cibuildwheel wheel is **16 KB-aligned**.

**Direction change (supersedes §1, §3.2, §5, §6, §7.5):**

- **Ship a plain, Java-free wheel.** The `.java/` dot-directory convention
  (`pyjnius-builder`/`ksproject`) is **dropped** — it is general machinery for
  arbitrary third-party Java, overkill for pyjnius's one fixed ~40-line file, and
  unproven at scale. The wheel carries **no Java payload**.
- **The Java glue moves to kivyforge's bootstrap templates**
  (`NativeInvocationHandler.java`, delivered like `MainActivity.java` and compiled
  + dex'd by the app's own Gradle; proven on device via `android.add_src`). The
  wheel's `invoke0` native-method contract and the bootstrap's copy are a
  **matched pair** that must be versioned together — nothing enforces it once
  packaging is out of the loop.
- **kivyforge is the only target.** p4a/ksproject compatibility and a
  first-party PyPI publication "serving every packager" are **out of scope**; the
  upstream PR to `kivy/pyjnius` (SDL-link removal + runtime resolver) is
  **deferred**.
- **Still open:** an **SDL3 host** (only SDL2 validated on device; the tier-1 code
  path is identical), and bootstrap-side 16 KB alignment (a kivyforge toolchain
  task, not a wheel one).

---

## 1. Why this is worth doing now

The ecosystem pieces are in place:

- Android is a **CPython Tier 3 platform** since 3.13 (PEP 738). Wheel tags are
  `android_<apilevel>_<abi>` (ABIs: `arm64_v8a`, `armeabi_v7a`, `x86_64`, `x86`).
- **PyPI accepts** `android_*` wheels and **pip ≥ 25.1 installs** them.
- **cibuildwheel ≥ 3.1** builds Android wheels on a Linux `x86_64` / macOS host
  (it drives the NDK via `sdkmanager`), with auditwheel grafting external `.so`s.
- The **CPython Android runtime** is published at
  <https://www.python.org/downloads/android/> (a prebuilt artifact, analogous to
  the iOS runtime), so downstream tools consume a prebuilt interpreter rather
  than building one.

PEP 738 explicitly noted that adoption stays limited "until prominent libraries
routinely release their own Android wheels." pyjnius is a keystone library for
the Kivy Android stack; a first-party wheel is a lighthouse for the whole
ecosystem and unblocks a wheel-only (no per-app source compilation) app pipeline.

## 2. Prior art (start here — do not start from scratch)

Working prebuilt pyjnius Android wheels **already exist**, and there is a
reusable build backend. This makes the spike "reproduce and harden," not "prove
it's possible."

- **Prebuilt wheels — the `kivyschool` Anaconda channel**
  (<https://pypi.anaconda.org/kivyschool/simple/pyjnius/>) publishes today:

  ```
  pyjnius-1.7.0-cp313-cp313-android_21_arm64_v8a.whl
  pyjnius-1.7.0-cp313-cp313-android_21_x86_64.whl
  pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl
  pyjnius-1.7.0-cp314-cp314-android_24_x86_64.whl
  ```

- **Build backend — `pyjnius-builder`**
  (<https://github.com/kivy-school/pyjnius-builder>): a **PEP 517 build backend**
  that compiles the per-ABI extension and **injects the Java glue into the
  wheel's `.java/`** from `[tool.pyjnius].java-paths`. This is the reference
  recipe — reuse or port it. (Sibling: `ksp-builder`, which injects
  `.gradle/<pkg>.json`.)
- **Consumer — `ksproject`** (<https://github.com/kivy-school/ksproject>)
  resolves the wheel with a plain `uv pip install --python-platform <arch>
  --extra-index-url <channel>`, then extracts the wheel's dot-directories
  (`.java/`, `.libs/<abi>/`, `.gradle/*.json`) into a generated AGP project — with
  **no pyjnius-specific handling**, relying entirely on the wheel plus a bootstrap
  load-order guarantee.
- **`ksp-bootstraps`** (<https://github.com/kivy-school/ksp-bootstraps>): MIT,
  `Protocol`-based Gradle/Xcode project generator. Early-stage, and its `main.c`
  currently targets SDL2 (so reusing it needs the same SDL3 handling discussed
  below).

**What is still missing** (and is exactly what this spike should deliver):

- No Android pyjnius wheel on **PyPI** (nor the Chaquopy index or conda-forge).
- The `kivyschool` wheels are **community-run**, cover only `cp313/android_21`
  and `cp314/android_24`, and are SDL2-linked. There is **no SDL3 build, no 3.15,
  and nothing first-party on PyPI**.

Note that **Kivy itself is already wheel-available** on the same channel
(`Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl`, and cp313). With CPython 3.14
stable on Android and a Kivy wheel in hand, **pyjnius is the single remaining
first-party keystone** for a wheel-only Kivy-on-Android stack.

## 3. The technical coupling (what makes pyjnius not fully self-contained)

pyjnius's Android coupling is small and well understood. It is **SDL**, in two
parts, plus a Java-glue delivery problem:

1. **A `JNIEnv` obtained from SDL.** On Android, pyjnius currently links `SDL2`
   and calls an SDL symbol to get the JVM `JNIEnv`:

   ```python
   # jnius/env.py
   class AndroidJavaLocation(UnixJavaLocation):
       def get_libraries(self):
           return ['SDL2', 'log']       # -> links -lSDL2 -llog
   ```

   ```cython
   # jnius/jnius_jvm_android.pxi  — on android, rely on SDL to get the JNI env
   cdef extern JNIEnv *SDL_AndroidGetJNIEnv()
   cdef JNIEnv *get_platform_jnienv() except NULL:
       return <JNIEnv*>SDL_AndroidGetJNIEnv()
   ```

   The symbol is resolved at load time from the SDL library the host app has
   already loaded. **SDL3 renamed it**: `SDL_AndroidGetJNIEnv` (SDL2) →
   `SDL_GetAndroidJNIEnv` (SDL3) (`SDL3/SDL_system.h`, since 3.2.0). python-for-android
   already ships a verified two-line patch,
   `pythonforandroid/recipes/pyjnius/sdl3_jnienv_getter.patch`, and its pyjnius
   recipe supports both SDL2 and SDL3
   (`depends = [('genericndkbuild', 'sdl2', 'sdl3'), 'six']`, applying the patch
   conditionally). Relevant upstream work already exists too: PR #710 added a
   `get_jni_java_vm` accessor, which is directly useful for the SDL-independent
   fallback discussed below.

2. **Java-side glue on the classpath.** pyjnius needs a small amount of Java
   (e.g. `org.jnius.NativeInvocationHandler`, used to implement Java interfaces
   from Python). A `.whl` carries no `.dex`, so the glue must reach the APK's
   dex. This is **solved by the dot-directory convention**: ship the sources in
   the wheel's `.java/` and let the app's project generator compile/dex them (as
   `pyjnius-builder` already does). *(Superseded — the spike drops `.java/` and
   delivers this glue via the kivyforge bootstrap templates instead; see "Spike
   outcome & revised direction" above.)*

## 4. Design decision: one universal wheel for SDL2 *and* SDL3

**Preferred target: a single `android_*` wheel that works against an SDL2 host
*or* an SDL3 host** (and, ideally, any host with an in-process JVM). This
decouples pyjnius from the SDL/Kivy generation: the *same* wheel serves Kivy
2.3.1 (SDL2) today and Kivy 3.0 (SDL3) later — no per-generation rebuild, no
forked wheels.

The only thing that pins a build to a single SDL generation is the *link-time*
symbol name plus a hard SDL `DT_NEEDED`. Remove both:

1. **Drop the hard SDL link.** Change `get_libraries()` from `['SDL2', 'log']`
   (or `['SDL3', 'log']`) to **`['log']`**, so the `.so` carries **no
   `DT_NEEDED` on any `libSDL*.so`**. A specific SDL soname is exactly what would
   otherwise lock the wheel to one generation and make it fail to `dlopen`
   against the other.
2. **Resolve the `JNIEnv` at runtime**, taking whichever is present (see the
   empirical correction below for *how* each is resolved):
   - `SDL_GetAndroidJNIEnv` from `libSDL3.so` (SDL3), else
   - `SDL_AndroidGetJNIEnv` from `libSDL2.so` (SDL2), else
   - `JNI_GetCreatedJavaVMs` (from `libnativehelper.so`) + `AttachCurrentThread` —
     SDL-independent, **API 31+ only** (public libnativehelper export since S; see
     PR #710's `get_jni_java_vm` for related work).

   **Empirical correction (spike, on device — supersedes the original claim that
   `RTLD_DEFAULT` suffices):** a CPython extension `dlopen`'d from site-packages does
   **not** have the host's `System.loadLibrary`'d SDL (nor `libnativehelper`) in its
   default lookup scope, so `dlsym(RTLD_DEFAULT, …)` returns **NULL** even though the
   library is resident and exports the symbol. Each tier therefore tries
   `RTLD_DEFAULT` first, then **`dlopen`s the library by soname** (`libSDL3.so` /
   `libSDL2.so` / `libnativehelper.so` — already loaded in the app's linker
   namespace, so `dlopen` just returns a handle + refcount) and `dlsym`s that handle.
   This stays runtime-only: **no `DT_NEEDED`** on any of them. The SDL path (tiers
   1–2) carries API 24–30; tier 3 adds SDL-independence on API 31+. `JNI_OnLoad`
   inside the wheel is **not** usable (ART never calls it for a `.so` imported via
   `dlopen`, not `System.loadLibrary`). See
   [pyjnius-android-wheel-spike-findings](pyjnius-android-wheel-spike-findings.md)
   (Steps 2–4, 7).

This is a small, low-risk change to `jnius/env.py` (drop SDL from linked libs)
plus a few lines of runtime resolution in `jnius_jvm_android.pxi`. It weakens the
runtime contract from "you must be an SDL3 app" to the honest **"an in-process
JVM exists and the Java glue is on the classpath."**

**Fallback:** if the runtime lookup proves too fiddly, an **SDL3-only** wheel —
built by applying p4a's `sdl3_jnienv_getter.patch` and linking SDL3 as an
external, host-provided library — is an acceptable result. Document clearly which
path was taken. The universal build is preferred; the SDL3-only build is the
floor.

## 5. Distribution model and the runtime contract

**Publish to PyPI, first-party, from `kivy/pyjnius`** — not to a private/community
index. First-party beats a community channel for any consumer that pins by
URL + SHA-256: no extra index, no single-maintainer supply-chain risk, canonical
provenance. It helps every packager (p4a, Briefcase, and others), not just one.
The `kivyschool` channel is the proof of concept; PyPI is the production home.

**The residual runtime contract the host must satisfy** (document it precisely —
it is what downstream packagers guarantee):

- An in-process JVM discoverable at import (via the runtime lookup in §4). For
  the SDL path specifically, `libSDL2.so`/`libSDL3.so` must be **loaded, with
  global symbol visibility, before the first `import jnius`**.
- The wheel's `.java/` glue is compiled and dexed into the APK, with the
  **`org.kivy.android.*` namespace preserved** so that
  `autoclass('org.kivy.android.PythonActivity')` and Plyer-style access keep
  working unmodified. *(Superseded: the wheel ships no Java; the glue is a
  kivyforge bootstrap template — see "Spike outcome & revised direction".)*
- **Fail loudly**: a missing JVM/glue should raise a clear `ImportError`
  ("pyjnius' Android wheel needs a host that provides an in-process JVM; see
  <link>"), not a cryptic dlopen/symbol failure — so e.g. a Termux user gets
  guidance instead of a crash.

**Ownership:** this is a maintainer commitment (CI, release cadence, the
CPython × ABI × API matrix, NDK-drift re-pins). Coordinating the contract with
the p4a maintainers keeps *one* contract rather than per-bootstrap variants.

## 6. Scope

**In scope**

- Build pyjnius wheels for **`arm64_v8a`** and **`x86_64`** (minimum two ABIs),
  targeting **`ANDROID_API_LEVEL=24`** (cibuildwheel default), for **CPython 3.14
  (stable)** and the **3.15 pre-release** (cibuildwheel's `cpython-prerelease`
  enable flag; 3.15 is final in October 2026).
  - `arm64_v8a` is the **real-device shipping target** (essentially all modern
    Android hardware is arm64).
  - `x86_64` is the **testability ABI**: cibuildwheel's testbed runs the
    on-device smoke test on a Gradle emulator matching the build host's
    architecture, and build hosts are x86_64, where the x86_64 system image runs
    near-native (KVM/HAXM). So the x86_64 wheel is the one you can load and
    validate at speed in CI and in the Android Studio emulator; arm64_v8a builds
    but skips on-device testing on an x86_64 host.
- **Aim for the universal SDL2+SDL3 wheel** (§4): drop the SDL `DT_NEEDED` and
  resolve the `JNIEnv` at runtime, completing the build with **no app present**.
  The **SDL3-only build via p4a's `sdl3_jnienv_getter.patch` is the documented
  fallback** if the runtime lookup proves too fiddly.
- Deliver the Java glue via the **dot-directory convention** (`.java/` in the
  wheel) and document the residual host contract (§5).
- Cython runs only at **wheel-build** time; consumers of a prebuilt-`.so` wheel
  never need it. (The spike lets cibuildwheel cythonize `.pyx`/`.pxi` at build
  time rather than pre-generating and shipping a stale `jnius.c` — the latter
  risks compiling the stale `.c` instead of our `.pxi` changes.)
- A reproducible cibuildwheel-based build (pin the NDK/API level).

**Out of scope**

- A perfect, production release/publish-automation pipeline (note what it would
  take, but the deliverable is a proof + findings).
- Non-Android platforms (do not regress desktop builds; no new work there).
- Downstream packagers' internals — you only need a minimal harness to *load and
  smoke-test* the wheel inside an app/emulator.

## 7. Concrete tasks

1. **Establish the starting point.** Confirm PyPI has no wheel and the
   `kivyschool` channel does (commands below); study the `pyjnius-builder` recipe
   and a downloaded kivyschool wheel's layout (per-ABI `.so`, injected `.java/`)
   as the baseline to reproduce and extend.

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

2. **Stand up a cibuildwheel Android build** on a Linux `x86_64` (or macOS)
   host: `pipx run cibuildwheel --platform android` (or pinned in
   `pyproject.toml`/CI), building `cp314-android_arm64_v8a` and
   `cp314-android_x86_64`. Use the `build`/`uv` frontend (Android does **not**
   support the `pip` frontend).

3. **Make it SDL-agnostic and fix the build** so it completes with **no app
   present** (preferred path):
   - Drop SDL from `get_libraries()` (→ `['log']`) so there is no SDL
     `DT_NEEDED`; document the exact linker flags (allow the resolver's symbols
     to remain undefined/resolved at runtime).
   - Implement the runtime `JNIEnv` resolver in `jnius_jvm_android.pxi`
     (SDL3 → SDL2 → `JNI_GetCreatedJavaVMs`); each tier tries `dlsym(RTLD_DEFAULT)`
     then `dlopen(soname)` + `dlsym` (see §4's empirical correction).
   - **Fallback:** if runtime lookup is impractical, apply p4a's
     `sdl3_jnienv_getter.patch` and link SDL3 as an external, host-provided
     library (do not bundle/graft `libSDL3.so`).
   - Pre-generate `jnius.c` from `jnius.pyx` (Cython as a build-only tool);
     ensure it compiles against NDK clang for each ABI.

4. **Make it load at runtime** on an emulator/device, under **both an SDL2 host
   and an SDL3 host** (for the universal build; SDL3-only if the fallback path
   was taken):
   - Ensure the host loads its SDL (globally) **before** `import jnius`.
   - Verify `autoclass('java.lang.System').getProperty('java.version')` returns
     from Python running on the emulator.
   - Use the CPython Android "testbed" app (the harness cibuildwheel uses for
     tests) or a minimal SDL/Gradle app to run the smoke test on a Gradle-managed
     emulator matching the build arch.

5. **Resolve the Java-glue delivery** and demonstrate a Python-implements-Java-interface
   round-trip (`NativeInvocationHandler`) from the installed wheel.

6. **Pin for reproducibility:** record exact NDK version, `ANDROID_API_LEVEL`,
   cibuildwheel version, and CPython version(s); note the re-pin path.

7. **Write the findings** (§9 deliverable).

## 8. Acceptance criteria

The spike **succeeds** if all of the following hold:

- [ ] pyjnius builds to `android_24_arm64_v8a` **and** `android_24_x86_64` wheels
      via cibuildwheel, **with no host app present at build time**.
- [ ] `pip install --only-binary=:all: --platform android_24_arm64_v8a
      --python-version 3.14 --target <dir> <the built wheel>` installs cleanly.
- [ ] The installed wheel **imports and runs on an emulator/device**: `autoclass`
      resolves a JVM class and calls a method, with the `JNIEnv` obtained by the
      runtime resolver. For the universal build, verify under **both an SDL2 host
      and an SDL3 host**; an SDL3-only pass is acceptable if the fallback path was
      taken (documented).
- [ ] A Python-implements-Java-interface round-trip works (Java-glue delivery
      solved and documented).
- [ ] The build is reproducible from pinned inputs (NDK/API/toolchain recorded).

If any criterion cannot be met, the spike still **succeeds as a spike** provided
the findings document precisely *why* (the exact blocker), so the decision can be
made with evidence.

## 9. Deliverables

1. **Wheels** for the two ABIs (attach as artifacts), or a clear statement of why
   they can't be produced.
2. **A findings document** (e.g. `docs/source/android-wheel.rst` or a markdown
   note) covering:
   - what worked / what didn't, with commands and logs;
   - the exact approach taken for the §3 coupling — the `JNIEnv` resolution
     (universal runtime lookup, or the SDL3 patch fallback) and the Java-glue
     delivery — including linker flags and any applied patch;
   - the pinned toolchain (NDK, API level, cibuildwheel, CPython versions) and
     reproducibility notes;
   - the **residual runtime contract** (§5): precisely what the host app must
     provide;
   - a recommendation on the **PyPI publication path**: is a maintained,
     upstream-published pyjnius Android-wheel release realistic, and what would it
     take (CI, cadence, ABI/API matrix, the runtime-`JNIEnv`-lookup decision, and
     the documented runtime contract)?
3. **A minimal reproducible build config** (cibuildwheel settings in
   `pyproject.toml` / a CI workflow) so the result is re-runnable.

## 10. Constraints & gotchas

- **Host OS:** build on a **Linux `x86_64`** or **macOS** host (WSL2 counts as
  Linux) with an Android SDK; let cibuildwheel manage the NDK via `sdkmanager`.
  Native Windows is unsupported *as the build host* — this is a host-OS
  limitation of cibuildwheel / the Android build tooling (POSIX-shell oriented),
  **not** a lack of cross-compilation: the build always cross-compiles to the
  `arm64_v8a`/`x86_64` Android (bionic) target regardless of host CPU, so an
  `x86_64` Linux host builds `arm64_v8a` wheels fine.
- **Frontend:** `build` / `build[uv]` / `uv` only — **not `pip`**.
- **API level:** default `ANDROID_API_LEVEL=24` (first with RUNPATH, needed by
  auditwheel; ~99% device coverage). Don't lower it without reason.
- **Testing:** only the **build-machine architecture** can be tested on the
  emulator; other ABIs build but skip on-device tests — plan the matrix
  accordingly.
- **Toolchain drift:** NDK/SDK/build-tools versions roll forward and drop old
  ones. **Pin them**, and make the pin easy to refresh.
- **16 KB page alignment (Android 15+/16):** native `.so`s need 16 KB LOAD-segment
  alignment or they fail to load on 16 KB-page devices (and warn on others). The
  cibuildwheel wheel is already 16 KB-aligned (NDK r28-series default, verified);
  an NDK r27 build (e.g. the p4a test harness) is only 4 KB-aligned. Align
  bootstrap/host libs with **NDK r28+** or `-Wl,-z,max-page-size=16384`, and 16 KB
  zip-align the APK. This is a *bootstrap/toolchain* task, not a wheel change.
  (Spike finding; see
  [pyjnius-android-wheel-spike-findings](pyjnius-android-wheel-spike-findings.md) Step 7.)
- **Do not regress** desktop/other-platform builds.

## 11. References

- PEP 738 (Android as a supported platform) — <https://peps.python.org/pep-0738/>
- Android platform tags —
  <https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#android>
- cibuildwheel Android — <https://cibuildwheel.pypa.io/en/stable/platforms/#android>
- CPython Android runtime + testbed —
  <https://www.python.org/downloads/android/>,
  <https://github.com/python/cpython/issues/131531>
- pyjnius Android coupling (SDL) — `jnius/env.py` (`AndroidJavaLocation`) and
  `jnius/jnius_jvm_android.pxi`
- `get_jni_java_vm` accessor (useful for the SDL-independent fallback) —
  pyjnius PR #710
- SDL3 `JNIEnv` rename — `SDL_GetAndroidJNIEnv` in `SDL3/SDL_system.h`; p4a fix
  `pythonforandroid/recipes/pyjnius/sdl3_jnienv_getter.patch` + the pyjnius recipe
  in <https://github.com/kivy/python-for-android>
- Prior-art wheels + build recipe + consumer —
  <https://pypi.anaconda.org/kivyschool/simple/pyjnius/> (published wheels),
  <https://github.com/kivy-school/pyjnius-builder> (PEP 517 backend),
  <https://github.com/kivy-school/ksproject> (resolve + dot-dir extraction)
- Reusable bootstrap / Java-glue prior art (dot-directory convention) —
  <https://github.com/kivy-school/ksp-bootstraps>
- pyjnius still compiled-from-source in p4a (context) —
  <https://github.com/kivy/python-for-android/issues/3342>
