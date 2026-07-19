# Spike brief: publish pyjnius as a standalone Android wheel

**Audience:** an engineer or coding agent working **inside the `kivy/pyjnius`
repository**. This brief is self-contained — you do not need any context about
the project that requested it. Everything you need to know is here.

**One-line objective:** determine whether — and how — `pyjnius` can be built and
published as a **standalone, app-agnostic, PEP 738 Android wheel** (`android_*`
tags) that a downstream tool can `pip install` and load at runtime inside an
Android app, **without** building pyjnius from source per app.

This is a **spike**: the primary deliverable is a *working proof + a findings
document*, not a finished, merged release pipeline. If it proves easy, produce
the wheels; if it proves hard, document exactly what blocks it.

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

## 2. The core technical problem (read this carefully)

pyjnius is **not self-contained** on Android today. A naive wheel will fail
because pyjnius currently binds, at **link time**, to things only the *host app*
provides:

1. **`libmain.so` linkage.** pyjnius links with `-lmain`, resolving symbols
   against the application's `libmain.so` produced by the p4a/SDL (or Qt)
   bootstrap. With the Qt bootstrap the library is even ABI-suffixed
   (`libmain_<abi>.so`); see the recently added `PYJNIUS_ANDROID_LIBMAIN`
   environment variable (fallback `"main"`) and the `-lmain` linker errors in the
   issue tracker. **A standalone wheel cannot link against an app library that
   does not exist at wheel-build time.**
2. **The JVM `JNIEnv` / `JavaVM`.** pyjnius gets its `JNIEnv` from an
   app-provided symbol (e.g. `SDL_AndroidGetJNIEnv` /
   `WebView_AndroidGetJNIEnv`). A generic wheel has no such symbol available at
   build time.
3. **Java-side glue on the classpath.** pyjnius needs a small amount of **Java**
   (e.g. `org.jnius.NativeInvocationHandler`, used to implement Java interfaces
   from Python). A `.whl` contains no `.dex`, so this Java code must reach the
   final APK's dex some other way.

**The spike must resolve all three by deferring app/JVM binding from link time to
run time**, and by defining how the Java glue ships. Candidate approaches (you
decide which is cleanest):

- Link the extension with **undefined/lazy symbols allowed** (do not hard-link
  `-lmain`); resolve the JVM at runtime via
  **`JNI_GetCreatedJavaVMs`** (Bionic hosts a JVM in-process) and/or `dlsym` of a
  well-known app symbol, with a documented fallback.
- Replace the compile-time `PYJNIUS_ANDROID_LIBMAIN` linkage with a **runtime
  lookup**.
- Ship the Java glue as **source `.java` (or a prebuilt `.aar`/`.jar`) inside the
  wheel** (e.g. under a data directory) and document that the app packager must
  compile/dex it — or upstream the glue into an `.aar` that apps depend on.

## 3. Scope

**In scope**

- Build pyjnius wheels for **`arm64_v8a`** and **`x86_64`** (min two ABIs),
  targeting **`ANDROID_API_LEVEL=24`** (cibuildwheel default), for at least the
  **current stable CPython Android tier** (3.14; add 3.15 if trivial). The two
  ABIs play different roles: **`arm64_v8a` is the real-device shipping target**
  (essentially all modern Android hardware is arm64), while **`x86_64` is the
  *testability* ABI** — cibuildwheel's testbed runs the on-device smoke test on a
  Gradle emulator **matching the build host's architecture**, and build hosts are
  x86_64 (Linux / Intel macOS), where the x86_64 system image runs near-native
  (KVM/HAXM) but an arm64 emulator would need slow full-CPU emulation. So the
  x86_64 wheel is the one you can actually *load and validate at speed* in CI (and
  in the Android Studio emulator during development); arm64_v8a builds but skips
  on-device testing on an x86_64 host (see §7).
- Solve the link-time-vs-runtime binding problem (§2) so the wheel builds without
  an app present and loads inside a real app.
- Define the Java-glue delivery mechanism.
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
3. **Fix the build** so it completes with **no app present**:
   - Remove/replace the hard `-lmain` dependency; allow undefined symbols to be
     resolved at load time (document the exact linker flags used).
   - Ensure Cython/JNI compiles cleanly against the NDK clang for each ABI.
4. **Make it load at runtime** inside a real Android process:
   - Implement runtime acquisition of `JavaVM`/`JNIEnv`
     (`JNI_GetCreatedJavaVMs` and/or documented app hook).
   - Verify `autoclass('java.lang.System').getProperty('java.version')` (or
     similar) returns from Python running on an emulator/device.
   - Use the **CPython Android "testbed"** app (the same harness cibuildwheel
     uses for tests) or a minimal SDL/Gradle app to load the wheel and run a
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
- [ ] The installed wheel **imports and runs on an emulator/device**: `autoclass`
      resolves a JVM class and calls a method (JVM/`JNIEnv` acquired at runtime,
      not via a hard `-lmain` link).
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
   - the exact approach taken for the three §2 problems (`libmain`, `JNIEnv`,
     Java glue) — including linker flags and runtime-lookup code;
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
- pyjnius `libmain`/JNIEnv linkage today —
  <https://github.com/kivy/python-for-android/pull/3308>,
  <https://github.com/kivy/python-for-android/issues/3220>
- Evidence of the missing wheel —
  <https://github.com/kivy/python-for-android/issues/3342>
