# pyjnius Android-wheel spike — status & handoff

> **Provenance.** Copied 2026-07-23 from the spike working repo (`~/pyjnius-spike`
> in WSL — a clone of `ElliotGarbus/pyjnius`, branch `spike/android-universal-wheel`),
> where it was authored as `SPIKE_STATUS.md`. This is the **findings/evidence
> record** the Android design docs cite; where it disagrees with the pre-spike
> brief ([pyjnius-android-wheel-spike](pyjnius-android-wheel-spike.md) —
> `RTLD_DEFAULT` resolution, `.java/` glue delivery), **this document supersedes
> it**. Local paths (`~/pyjnius-spike`, `~/wheelhouse`, `/mnt/c/...`) refer to
> that WSL environment.

**Purpose of this file:** a self-contained handoff so work can continue in the
WSL-connected Cursor window (a fresh agent or a human). It records what has been
done, how to reproduce it, and the exact next steps. Companion to
[pyjnius-android-wheel-proposal](pyjnius-android-wheel-proposal.md) (the design
brief, authored as `ANDROID_WHEEL_PROPOSAL.md`).

---

## TL;DR

The **universal, SDL-agnostic Android wheel works.** pyjnius now builds to
`android_24_arm64_v8a` and `android_24_x86_64` (CPython 3.14) via cibuildwheel,
**with no host app present**, with **no `DT_NEEDED` on any `libSDL`** and **no
undefined SDL symbol** (verified at the ELF level), and the wheels **pip-install**
via cross-download. **Steps 2–7 are done** (incl. real arm64 hardware — Pixel 8a,
Android 16/API 36). The runtime resolver is
three-tier (SDL3 → SDL2 → `JNI_GetCreatedJavaVMs`), and **both** the SDL-independent
path and the SDL-host path are now confirmed on-device:

- **Step 3 (SDL-less):** the cibuildwheel Android testbed on an API-35 x86_64
  emulator ran `autoclass('java.lang.System').getProperty('java.vm.name')` →
  **`Dalvik`**, `JNIEnv` via the tier-3 `dlopen(libnativehelper)` fallback.
- **Step 4 (real SDL2 host):** a **buildozer/p4a Kivy app** (SDL2 bootstrap) built
  against this source and run on an **API-32 x86_64 emulator** resolved the env via
  **tier 2 (`SDL_AndroidGetJNIEnv`)** and round-tripped to `Dalvik` — deterministic
  across relaunches.

**KEY CORRECTION from Step 4:** the original premise that a host-loaded SDL getter
is reachable via `dlsym(RTLD_DEFAULT, …)` is **false on device**. A CPython
extension `dlopen`'d from site-packages does **not** have the host's
`System.loadLibrary`'d SDL in its default lookup scope (empirically NULL on API 32),
so each tier now `dlopen`s the library **by soname** (`libSDL3.so` / `libSDL2.so` /
`libnativehelper.so`) and `dlsym`s the handle — same fix tier 3 already needed.
ELF verification still shows **no** `DT_NEEDED` on any of them (only
`dlopen`/`dlsym@LIBC`). **Step 5** then proved the last criterion — the
Python-implements-Java-interface round-trip (`@java_method` → `invoke0`) — on-device,
with the Java glue delivered **app-side** (bootstrap-template model), not from the wheel.
**Step 6** confirmed the runtime hygiene assumptions: the upstream `ANDROID_ARGUMENT`
thread-detach hook fires, and pyjnius attaches to the host VM without ever calling
`JNI_CreateJavaVM`.

---

## Direction & scope (updated 2026-07-20)

**kivyforge is the only target.** The wheel is no longer chasing portability across
build systems (p4a / ksproject compatibility is explicitly a non-concern — they build
pyjnius from source, not a wheel, and kivyforge aims to displace p4a). Concretely:

- **Ship a plain, Java-free Python wheel** — patched pyjnius source (SDL link removed,
  `get_libraries()` → `['log']`, runtime SDL-getter JNIEnv resolver) → cibuildwheel →
  `arm64-v8a` (and `x86_64` for the emulator). No Java payload, no `.java/` machinery.
- **JNIEnv acquisition stays the validated SDL-getter resolver** (Step 4). The wheel's
  `.so` finds the SDL-provided VM itself via `dlopen(libSDL*.so)` + `dlsym`, so it needs
  **nothing from the bootstrap for the env**. (Note: "JNI_OnLoad inside the wheel" is
  *not* used and is not possible — ART never calls `JNI_OnLoad` for a `.so` imported by
  CPython via `dlopen`.)
- **The Java glue moves to kivyforge's bootstrap templates.** `NativeInvocationHandler.java`
  is generated/delivered like `MainActivity.java` / `PythonActivity.java` and compiled +
  dex'd by the app's own Gradle. This **supersedes** the earlier `.java/` dot-directory
  decision and makes the p4a-consumption work (and its draft issue) obsolete.
- **Upstream PR to `kivy/pyjnius`: deferred** — revisit after the glue round-trip is proven.

Superseded below (kept only for history, marked as such): the `.java/` Java-glue
decision, the consumer-compatibility matrix, and the draft p4a issue appendix.

---

## Environment (WSL2)

- Host: **WSL2, Ubuntu 26.04 LTS, x86_64**
- Python **3.14.4**, pip **25.1.1**, uv **0.11.28**
- Java **17** (`/usr/lib/jvm/java-17-openjdk-amd64`)
- Android SDK at **`~/android-sdk`** (`sdkmanager 20.0`); cibuildwheel auto-installed
  **NDK 27.3.13750724**
- **cibuildwheel 4.1.0** (installed as a `uv` tool → `~/.local/bin/cibuildwheel`)
- `/dev/kvm` present, but the user is **not yet in the `kvm` group** (needed for the
  emulator; requires a one-time privileged step — see Next steps)

**Environment file:** `~/.pyjnius-spike-env.sh` sets `ANDROID_HOME`,
`ANDROID_SDK_ROOT`, `JAVA_HOME`, and `PATH`. Source it before any build:

```bash
source ~/.pyjnius-spike-env.sh
```

**Repo:** this working copy is `~/pyjnius-spike`, a local `git clone` of
`/mnt/c/Users/ellio/PycharmProjects/pyjnius`. `origin` therefore points at the
Windows path — repoint it at the GitHub fork before any upstream PR.

- Build outputs: `~/wheelhouse/`

---

## The two source changes (Android-only; no desktop impact)

### 1. `jnius_config/env.py` — drop the hard SDL link

`AndroidJavaLocation.get_libraries()` now returns `['log']` instead of
`['SDL2', 'log']`. A `DT_NEEDED` on a specific `libSDL*.so` would lock the wheel
to one SDL/Kivy generation and fail to `dlopen` against the other. (`jnius/env.py`
is just a shim that re-exports `jnius_config.env`.)

### 2. `jnius/jnius_jvm_android.pxi` — resolve the JNIEnv at runtime (three-tier)

Replaced the direct `extern SDL_AndroidGetJNIEnv()` call with a runtime
`dlsym(RTLD_DEFAULT, ...)` resolver that tries, in order:

1. `SDL_GetAndroidJNIEnv` (SDL3)
2. `SDL_AndroidGetJNIEnv` (SDL2)
3. `JNI_GetCreatedJavaVMs` + `AttachCurrentThread` (SDL-independent) — **Step 2**

The SDL getters return a `JNIEnv*` directly. The `JNI_GetCreatedJavaVMs` fallback
(`_jnienv_from_created_vm()`) `dlsym`s the symbol, retrieves the process' existing
JavaVM, and `AttachCurrentThread`s to get the `JNIEnv`. If all three fail it
raises a clear `RuntimeError` naming the host contract.

> **API-level scope of the three tiers (settled).** Tiers 1–2 (SDL) are the
> primary path and work on **all** supported API levels (≥ 24): a Kivy/SDL host
> `System.loadLibrary`s SDL, SDL's own `JNI_OnLoad` captures the JavaVM, and SDL
> re-exposes it via the getter we `dlsym`. Tier 3 (`JNI_GetCreatedJavaVMs`) is
> **best-effort, effectively API 31+**: that symbol only became a public
> `libnativehelper` export in Android 12 / API 31 (`introduced=S`,
> [android/ndk#1969](https://github.com/android/ndk/issues/1969)); on API 24–30
> it's outside the app linker namespace and the `dlsym` typically returns `NULL`,
> so a non-SDL host there falls through to the `RuntimeError`. This is fine —
> `minSdk` stays 24 because the SDL path covers those levels for the real target.
>
> **`JNI_OnLoad` is *not* an alternative here.** It's the officially-blessed,
> all-API way to receive the JavaVM, but Android only calls it for libs loaded
> via `System.loadLibrary` (ART does `dlopen` + `dlsym("JNI_OnLoad")`). This `.so`
> is a CPython extension loaded by a plain `dlopen()` on `import`, so ART never
> calls a `JNI_OnLoad` defined in it — it would be dead code. The all-API
> SDL-independent option, if ever needed, is an explicit host-provided setter
> (a §5 runtime-contract API), not autodetection.

Removing every direct symbol reference is **required**, not just preferred: the
NDK link uses `-Wl,--no-undefined`, so any leftover undefined symbol (SDL *or*
JNI) would fail the link. The ELF check below confirms none survive.

> These edits are committed and pushed on branch
> **`spike/android-universal-wheel`** (tracks `origin`). Remotes: `origin` →
> `github.com/ElliotGarbus/pyjnius` (the fork), `upstream` → `github.com/kivy/pyjnius`,
> `local` → the Windows clone `/mnt/c/Users/ellio/PycharmProjects/pyjnius`.

---

## Reproduce the build

```bash
source ~/.pyjnius-spike-env.sh
cd ~/pyjnius-spike

# The Android branch of jnius.pyx needs config.pxi + a pre-generated jnius.c
# (Cython is a build-only tool; consumers of the wheel do not need it).
echo "DEF JNIUS_PLATFORM = 'android'" > jnius/config.pxi
uvx --from "Cython~=3.1.2" cython -3 jnius/jnius.pyx -o jnius/jnius.c

# API level, ABIs, and build frontend are now pinned in
# pyproject.toml [tool.cibuildwheel.android] — no manual exports needed.
# --only computes the platform, so no CIBW_PLATFORM either.
cibuildwheel --only cp314-android_x86_64    --output-dir ~/wheelhouse
cibuildwheel --only cp314-android_arm64_v8a --output-dir ~/wheelhouse
```

### ELF verification (proves the universal design)

```bash
READELF=~/android-sdk/ndk/27.3.13750724/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf
# unzip a wheel, then:
$READELF -d        jnius/jnius*.so | grep NEEDED       # -> libm liblog libpython3.14 libdl libc  (NO libSDL)
$READELF --dyn-syms jnius/jnius*.so | grep -i sdl      # -> (none)
$READELF --dyn-syms jnius/jnius*.so | grep -iE "JNI_GetCreatedJavaVMs|AttachCurrentThread"  # -> (none: dlsym'd / vtable, not linked)
$READELF --dyn-syms jnius/jnius*.so | grep -i dlsym    # -> dlsym@LIBC (the runtime resolver)
```

### pip cross-install check

```bash
python3 -m pip install --only-binary=:all: --platform android_24_arm64_v8a \
    --python-version 3.14 --target /tmp/x --no-deps \
    ~/wheelhouse/pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl
```

---

## Acceptance criteria status (see proposal §8)

- [x] Builds `android_24_arm64_v8a` **and** `android_24_x86_64`, no host app present
- [x] `pip install` cross-download installs cleanly
- [x] Imports/runs on an emulator/device — **both paths confirmed.**
      (a) SDL-less: cibuildwheel testbed, API-35 x86_64 emulator, env via tier-3
      `dlopen(libnativehelper)` + `JNI_GetCreatedJavaVMs` → `Dalvik`.
      (b) Real SDL2 host: buildozer/p4a Kivy app (SDL2 bootstrap) on an API-32
      x86_64 emulator, env via **tier 2 `SDL_AndroidGetJNIEnv`** → `Dalvik`,
      deterministic across relaunches.
      (c) **Real arm64 hardware (Step 7):** Pixel 8a, arm64-v8a, Android 16/API 36,
      env via **tier 2 `SDL_AndroidGetJNIEnv`**, all markers green, ELF clean.
      **SDL3** host not yet exercised (Kivy is SDL2; would need an SDL3 host build).
- [x] Python-implements-Java-interface round-trip — **PROVEN on-device (Step 5)** with
      the glue delivered **app-side** (`android.add_src`, bootstrap-template model), NOT
      from the wheel. On an API-32 SDL2 emulator a Python `Comparator` was driven by
      `java.util.Collections.sort` (`compare` called 3×, String args in, `int` return used
      to sort → `['apple','banana','cherry']`) and a Python `Runnable` was called back via
      `java.util.concurrent.FutureTask.run()` — both through
      `NativeInvocationHandler.invoke0`. See "Step 5" below.
- [x] Reproducible from pinned inputs (locked into `pyproject.toml`
      `[tool.cibuildwheel.android]`; NDK pinned via the cibuildwheel version).
      Caveat: toolchain inputs are pinned, but wheels are not yet *bit-for-bit*
      identical (would additionally need `SOURCE_DATE_EPOCH` etc.)

## Reproducibility pins

Locked in `pyproject.toml` `[tool.cibuildwheel.android]` except where noted.
cibuildwheel has **no NDK-version key**: the NDK is a function of the cibuildwheel
version, so pinning cibuildwheel pins the NDK.

| Input | Value | Where pinned |
|---|---|---|
| NDK | 27.3.13750724 | implied by cibuildwheel 4.1.0 (documented in `pyproject.toml` comment) |
| ANDROID_API_LEVEL | 24 | `[tool.cibuildwheel.android].environment` |
| ABIs | arm64_v8a (ship), x86_64 (test) | `[tool.cibuildwheel.android].archs` |
| build frontend | `build` (Android forbids `pip`) | `[tool.cibuildwheel.android].build-frontend` |
| cibuildwheel | 4.1.0 | operational (uv tool); pin in CI when set up |
| Cython | ~=3.1.2 (3.1.8 used) | `[build-system].requires` |
| CPython target | 3.14 (cp314); add 3.15 pre-release via `--enable cpython-prerelease` | build invocation (`--only`) |

> Verified: building with **no** `ANDROID_API_LEVEL`/`CIBW_PLATFORM` exports still
> produces `android_24_*` — the config alone drives it.

---

## Next steps (agreed plan: option 2 then 3)

### Step 2 — SDL-independent `JNI_GetCreatedJavaVMs` fallback — DONE ✅

Implemented in `jnius_jvm_android.pxi` as `_jnienv_from_created_vm()` /
`_resolve_get_created_javavms()`: if neither SDL getter resolves, obtain the
process' JavaVM via `JNI_GetCreatedJavaVMs` and `AttachCurrentThread` to get the
`JNIEnv`. See Step 3 for the empirical correction to *how* the symbol is resolved
(`dlopen` by soname, not `RTLD_DEFAULT`). Confirmed not linked (ELF check).

### Step 3 — on-device smoke test — DONE ✅

Ran via cibuildwheel's Android testbed on a `--managed maxVersion` (API-35)
x86_64 emulator (KVM available). Result:

```
ANDROID_SMOKE_OK vm.name=Dalvik vendor=The Android Project java.version=0
✓ cp314-android_x86_64 finished
```

`autoclass('java.lang.System')` resolved and `getProperty('java.vm.name')`
returned `Dalvik` — a real ART round-trip, with the `JNIEnv` from the tier-3
fallback (the testbed has no SDL). (`java.version` is `0` on Android; that's
normal — `java.vm.*` carries the real info.) Test config lives in
`pyproject.toml` `[tool.cibuildwheel.android].test-command`.

> **KEY EMPIRICAL FINDING (changed the implementation).** The first run *failed*:
> `dlsym(RTLD_DEFAULT, "JNI_GetCreatedJavaVMs")` returned NULL **even on API 35**.
> "Public export at API 31+" means you may *link* `-lnativehelper`, not that the
> symbol is reachable via `RTLD_DEFAULT` — `libnativehelper.so` isn't in the
> extension's default lookup scope. Fix: **`dlopen("libnativehelper.so")` by
> soname** (permitted for apps on API 31+) then `dlsym` the handle. `dlopen` is
> runtime-only, so ELF re-verification shows **no new `DT_NEEDED`** (still no
> libSDL/libnativehelper/libart; only `dlopen`/`dlsym@LIBC`). After this change the
> testbed passes.

### Step 4 — real SDL2 host on device — DONE ✅

cibuildwheel's testbed has **no SDL loaded**, so Step 3 only exercised tier 3, not
the SDL getters. Step 4 closes that gap with a real SDL2 host: a minimal
**buildozer/p4a Kivy app** (`~/sdl-host-test/`, SDL2 bootstrap) built against *this*
source (via `P4A_pyjnius_DIR` + a local recipe that drops p4a's link-time getter
patches and keeps `use_cython.patch`) and run on an **API-32 x86_64 emulator**
(`pyjnius_x86_64` AVD). A one-line `__android_log_print` in the resolver reports the
winning tier to logcat:

```
I pyjnius : JNIEnv source: tier 2 SDL2 (SDL_AndroidGetJNIEnv)
I python  : SDL_HOST_SMOKE_OK vm.name=Dalvik vendor=The Android Project java.version=0
```

Deterministic across relaunches. ELF re-check of the p4a-built `jnius.so`: `NEEDED`
= only `libpython3.14.so`, `liblog.so`, `libdl.so`, `libc.so` — **no libSDL/
libnativehelper/libart**, no directly-linked SDL/`JNI_GetCreatedJavaVMs` symbol,
`dlopen`/`dlsym@LIBC` present.

> **KEY CORRECTION (changed the SDL path too).** The first Step-4 run resolved via
> **tier 3**, not the SDL getter, even though libSDL2 was loaded — i.e.
> `dlsym(RTLD_DEFAULT, "SDL_AndroidGetJNIEnv")` returned NULL. This falsifies the
> spike's original premise (a host-loaded SDL symbol is reachable via
> `RTLD_DEFAULT`). Same root cause as tier 3: an extension `dlopen`'d from
> site-packages does not have the host's `System.loadLibrary`'d SDL in its default
> lookup scope. Fix: `_resolve_sdl_getter()` now tries `RTLD_DEFAULT` first, then
> **`dlopen`s the SDL soname** (`libSDL3.so`/`libSDL2.so`) and `dlsym`s the handle
> — still runtime-only, no `DT_NEEDED`. After this change tier 2 fires. On API
> 24–30 (no tier 3) this SDL path is what carries the wheel; the dlopen-by-soname
> approach works on those levels because libSDL* is an app lib in the app linker
> namespace.

Not yet exercised at this point: an **SDL3** host (Kivy is SDL2) and **arm64** on real
hardware. (arm64-on-hardware was subsequently done — see Step 7.)

### Step 5 — glue round-trip via app-side (bootstrap-template) delivery — DONE ✅

Proves the *Python-implements-a-Java-interface* path with the new direction's delivery
model: the wheel ships **no** Java, and `org.jnius.NativeInvocationHandler` is delivered
**app-side** exactly as kivyforge will ship it as a bootstrap template.

Harness changes (`~/sdl-host-test/`):

- **Wheel/recipe made Java-free.** The stock p4a `PyjniusRecipe.postbuild_arch` copies
  `jnius/src/org` into the dex (`ctx.javaclass_dir`). The local `PyjniusSpikeRecipe` now
  overrides `postbuild_arch` to **skip** that copy (calls the grandparent
  `PyProjectRecipe.postbuild_arch`), so the recipe contributes no Java.
- **Glue delivered app-side.** `NativeInvocationHandler.java` lives at
  `sdl-host-test/javaglue/org/jnius/` and is added via `android.add_src = ./javaglue`
  → a Gradle `srcDir` (verified: `java {srcDir '.../javaglue'}`; the dist's
  `src/main/java/.../org/jnius/` copy is gone). So the class in the dex comes **only**
  from the app-side file.
- **Round-trip exercised** (`app/main.py`): a Python `java.util.Comparator` driven by
  `Collections.sort`, and a Python `java.lang.Runnable` driven by
  `java.util.concurrent.FutureTask.run()`.

Logcat on the API-32 SDL2 emulator:

```
I pyjnius : JNIEnv source: tier 2 SDL2 (SDL_AndroidGetJNIEnv)
I python  : SDL_HOST_SMOKE_OK vm.name=Dalvik ...
I python  : PROXY_COMPARATOR_OK calls=3 ordered=['apple', 'banana', 'cherry']
I python  : PROXY_RUNNABLE_OK
I python  : PROXY_ROUNDTRIP_OK
```

`compare` was invoked 3× with String args and its `int` return drove the sort → the
full args-in/value-out callback goes through `invoke0`. No `ClassNotFoundException`
(glue resolved), no CheckJNI abort, process stayed alive.

> **Harness gotcha (not a wheel bug):** the first attempt used `Thread(runnable).run()`
> and hit a **CheckJNI abort** — pyjnius resolved the single-proxy-arg constructor to
> `Thread(String)` and passed the proxy as a String. Switched to the unambiguous
> `FutureTask(Runnable, V)` 2-arg ctor. This is a pyjnius overload-resolution sharp edge
> to note for kivyforge docs, unrelated to the wheel/glue.

### Step 6 — thread-detach hook + no-VM-creation — DONE ✅

Same harness, two extra runtime checks (`app/main.py`):

- **Thread-detach hook fires.** The upstream `ANDROID_ARGUMENT`-gated wrapper in
  `jnius/__init__.py` wraps `threading.Thread.run` to call `jnius.detach()` in a
  `finally`. Spawned a Python `threading.Thread` that does a JNI call
  (`System.getProperty`), then joined it; a temporary wrapper around `jnius.detach`
  observed the call. Logcat: `THREAD_DETACH_OK calls=1 threads=['detach-probe']`.
  Confirms JNI thread hygiene works for free with kivyforge's bootstrap (which sets
  `ANDROID_ARGUMENT`); nothing to build.
- **Attaches to host VM, never creates one.** `jnius_config.vm_running` is set `True`
  only by the desktop/dlopen `JNI_CreateJavaVM` paths; on Android it stays `False`.
  Logcat: `VM_ATTACH_OK vm_running=False options=[] (attached to host VM, no
  JNI_CreateJavaVM)`. Confirms `jnius_config` is runtime-inert on Android.

### Step 7 — real arm64 hardware (Pixel 8a, Android 16 / API 36) — DONE ✅

The shipping ABI, on a physical device (not the emulator). Rebuilt the same harness for
`android.archs = arm64-v8a` (full from-scratch arch bootstrap of python3/SDL2/kivy/our
pyjnius) and ran it on a **Pixel 8a, arm64-v8a, Android 16 (API 36)**, attached to WSL2
over USB via `usbipd-win` (`usbipd bind`/`attach --wsl`; install needed
`adb install --no-streaming` because streaming installs stall over the usbip transport).

All checks green — same markers as the emulator, one level newer OS:

```
I pyjnius : JNIEnv source: tier 2 SDL2 (SDL_AndroidGetJNIEnv)
I python  : SDL_HOST_SMOKE_OK vm.name=Dalvik ...
I python  : PROXY_COMPARATOR_OK calls=3 ordered=['apple', 'banana', 'cherry']
I python  : PROXY_RUNNABLE_OK
I python  : THREAD_DETACH_OK calls=1 threads=['detach-probe']
I python  : VM_ATTACH_OK vm_running=False options=[]
I python  : ALL_CHECKS_OK
```

ELF re-check of the **arm64** `jnius.so` (NDK r27d, Android 24, stripped): `NEEDED` =
only `libpython3.14.so`, `liblog.so`, `libdl.so`, `libc.so` — no libSDL/libnativehelper/
libart, no SDL/`JNI_GetCreatedJavaVMs`/`JNI_CreateJavaVM` symbol refs, `dlopen`/
`dlsym@LIBC` present. Identical clean profile to the x86_64 build.

> **16 KB page alignment (Android 15+/16) — a toolchain concern, not a source one.**
> On the Pixel 8a (Android 16) the app showed a compatibility warning about 16 KB
> alignment. Investigated: every `.so` in the **p4a test harness** (libpython3.14,
> libSDL2, libmain, and the p4a-rebuilt `jnius.so`) has LOAD-segment alignment
> `0x1000` = **4 KB**, because p4a here uses **NDK r27**, which does not 16 KB-align by
> default. The warning is non-fatal on a device booted in 4 KB-page mode (as this one
> is), but 4 KB-aligned libs fail to load on a 16 KB-page device.
>
> Crucially, the on-device run used p4a's rebuilt-from-source `jnius.so` (the recipe
> re-cythonizes via `use_cython.patch`), **not** the wheel. The **cibuildwheel wheel —
> the actual deliverable — IS 16 KB-aligned**: `pyjnius-1.7.0-cp314-cp314-
> android_24_arm64_v8a.whl`'s `jnius.so` has LOAD segments at `0x4000`.
>
> **Corrected 2026-07-21 (earlier note misattributed the toolchain).** The wheel was
> built with the pinned **NDK r27 (27.3.13750724)**, not "r28-series": its `.comment`
> reads `clang version 18.0.4 ... based on r522817d` (build 13691557), which *is* r27's
> clang — r28 ships clang 19 (`r530567e`), as the later p4a-SDL3 build (NDK r28c →
> 16 KB) confirms. So the 16 KB alignment does **not** come from an NDK default:
> empirically the *same* r27 clang produced 16 KB via cibuildwheel but 4 KB via the
> p4a-SDL2 build. The difference is a **linker flag** — the CPython-Android build/
> sysconfig that cibuildwheel compiles against already passes
> `-Wl,-z,max-page-size=16384`; p4a's r27 build does not. NDK r27 does **not** default
> to 16 KB; NDK r28+ does.
>
> **Wheel-build policy (updated):** because the wheel's alignment on r27 currently
> rides on CPython's *implicit* LDFLAGS, the PR adds `-Wl,-z,max-page-size=16384`
> explicitly to `[tool.cibuildwheel.android].environment` — redundant-but-harmless
> today, a guarantee against toolchain/flag drift. This aligns only `pyjnius.so`.
>
> **Action for kivyforge (not pyjnius):** ELF alignment ≠ APK zip-alignment, and the
> flag above does not touch the bootstrap libs. kivyforge must ensure the
> bootstrap-provided libs (libpython/SDL/libmain) are 16 KB-aligned — build with
> NDK r28+ or link with `-Wl,-z,max-page-size=16384` — and 16 KB zip-align the APK.

### Later

- **Java-glue delivery — DECIDED (direction change): plain Java-free wheel; the glue
  (`NativeInvocationHandler.java`) lives in kivyforge's bootstrap templates.** See
  "Java-glue delivery" below. (Supersedes the earlier `.java/` dot-directory decision.)
- ~~Lock the pins into a `[tool.cibuildwheel]` config in `pyproject.toml`.~~ DONE ✅
- Prove the glue round-trip (`PythonJavaClass`/`@java_method`) with the glue delivered
  as a bootstrap file — see "What we still need to prove".
- Upstream PR to `kivy/pyjnius` (SDL-link removal + runtime resolver): **deferred** —
  decide after the glue round-trip is proven.

## Java-glue delivery — decision & consumer compatibility

### What the glue is

A single ~40-line class, `org.jnius.NativeInvocationHandler` (in
`jnius/src/org/jnius/`), with a `native invoke0(...)` method bound at runtime via
`RegisterNatives`. It is **only** needed for the *Python-implements-a-Java-interface*
feature (`PythonJavaClass`/`@java_method`), used in `create_proxy_instance`
(`jnius_proxy.pxi`) via `autoclass('org.jnius.NativeInvocationHandler')`. Plain
`autoclass` + method calls need no glue (Step 3 passed with none present). The hard
requirement is runtime: the class must be **compiled + dex'd into the APK** and
findable by the classloader pyjnius uses — a `.whl` carries no `.dex`, so the
source (or a compiled form) must reach the app's dex step. It cannot be eliminated:
a `java.lang.reflect.Proxy` handler can't be built from pure Python.

### Decision (updated 2026-07-20): plain Java-free wheel + glue in the kivyforge bootstrap

**Direction change.** Earlier this spike chose option B — ship the glue as source in a
`.java/` dot-directory for a generic downstream extractor (`pyjnius-builder`/`ksproject`).
That is now **dropped**. kivyforge is the only target, so:

- **The wheel ships no Java at all** — just the patched pyjnius Python + `.so` (SDL link
  removed, `get_libraries()` → `['log']`, runtime SDL-getter resolver validated in Step 4).
- **`NativeInvocationHandler.java` becomes a kivyforge bootstrap template**, generated/
  delivered like `MainActivity.java` / `PythonActivity.java`, so the app's own Gradle/AGP
  compiles + dex'es it into the APK.

Why the change:

- **Wrong tool for the problem.** The `.java/` convention is general machinery for
  arbitrary, unpredictable third-party Java. pyjnius needs one small, fixed ~40-line file.
- **Unproven at scale.** No real package — pyjnius included — actually uses
  `pyjnius-builder`/`ksp-builder` today; it targets a hypothetical future plugin ecosystem.
- **The wheel is self-sufficient for the env.** The `.so` resolves the JNIEnv itself via
  the SDL getter (Step 4), so it needs nothing from the bootstrap for the env — the *only*
  thing the bootstrap must supply is the Java glue. Putting it in the templates keeps that
  in one place kivyforge already owns.
- **Not contradicted by desktop precedent.** Desktop pyjnius bundles a *compiled* `.class`
  inside its own namespace, self-consumed by its self-created JVM — a different mechanism,
  not prior art for cross-build-system source injection.

**Matched-pair coupling (must document — nothing enforces it).** The wheel's `invoke0`
native-method contract and the bootstrap's `NativeInvocationHandler.java` are a matched
pair that must move together. With `.java/` gone, no packaging step catches drift.
Mitigations: pyjnius already resolves `autoclass('org.jnius.NativeInvocationHandler')` at
proxy-creation, so a mismatch surfaces as a clear `ClassNotFound`/`NoSuchMethod` at first
use (not silent corruption); add a version comment in **both** the wheel build script and
the bootstrap template, and consider a runtime version-constant check.

### Runtime notes (audited from the real wheel; no code changes needed)

- **Thread-detach hook is already upstream.** `jnius/__init__.py` (unmodified, every
  release; lines 75–89 here) installs an `ANDROID_ARGUMENT`-gated `threading.Thread.run`
  wrapper that calls `jnius.detach()` on thread exit — correct JNI hygiene. kivyforge's
  bootstrap already sets `ANDROID_ARGUMENT`, so this works for free. **Do not
  reimplement**; just confirm it fires during smoke-testing.
- **`env` / `jnius_config` are runtime-inert on Android — but `env` is build-time
  load-bearing.** `setup.py` imports `jnius_config/env.py` for `get_libraries()` → `['log']`
  (the SDL-link removal). At *runtime*, `jnius/__init__.py` imports `get_java_setup` but
  only uses it on `win32`; `jnius_config.py` (classpath/JVM options) is moot because the
  wheel never calls `JNI_CreateJavaVM` — it attaches to the bootstrap's existing VM.
  Document as runtime-inert; no code change.

### Superseded — `.java/` decision & p4a consumption (history)

The prior direction shipped the glue as source in a `.java/` dot-directory so any generic
consumer (`ksproject` as-is, kivyforge/p4a with an extractor) could route it into the dex
step, and included a draft p4a issue asking the maintainer to teach the prebuilt-wheel
installer to extract `.java/`. **All of that is obsolete** under the kivyforge-only,
Java-free-wheel direction. See git history (pre-2026-07-20) for the full matrix and the
draft issue if p4a interop is ever revisited.

## What we still need to prove (updated direction)

Ordered by importance. The env-resolution work (Steps 2–4) is done; the open items are
now mostly about the glue path and the new delivery model.

1. ~~**Glue round-trip, glue delivered as a bootstrap file (PRIMARY, never yet proven).**~~
   **DONE ✅ (Step 5).** Built an app where `NativeInvocationHandler.java` is delivered as
   an app-side Java source (`android.add_src`, simulating the bootstrap template), *not*
   from the wheel or p4a's recipe (the recipe's `postbuild_arch` glue copy was overridden
   off), and confirmed `PythonJavaClass`/`@java_method` proxies fire `invoke0` on-device
   (Comparator + Runnable). See "Step 5".
2. ~~**Thread-detach hook fires.**~~ **DONE ✅ (Step 6).** Confirmed the
   `ANDROID_ARGUMENT`-gated `threading.Thread.run` wrapper calls `jnius.detach()` on
   worker-thread exit (`THREAD_DETACH_OK calls=1`).
3. ~~**`jnius_config`/`env` inert at runtime.**~~ **DONE ✅ (Step 6).** No
   `JNI_CreateJavaVM` path taken — `jnius_config.vm_running` stayed `False`
   (`VM_ATTACH_OK`); attaches to the bootstrap VM only.
4. **Coverage gaps carried over from Step 4:** ~~**arm64 on real hardware**~~ **DONE ✅
   (Step 7** — Pixel 8a, arm64-v8a, Android 16/API 36, all markers green, ELF clean).
   **Only remaining: an SDL3 host** (Kivy is SDL2, so tier 1 `SDL_GetAndroidJNIEnv` is
   still unexercised on device — though its code path is identical to the validated tier 2).

## Open risks to settle empirically

- ~~Is `JNI_GetCreatedJavaVMs` reliably `dlsym`-able and does it reach ART across
  API levels?~~ **SETTLED EMPIRICALLY (Step 3).** It's a public `libnativehelper`
  export only on **API 31+** (`introduced=S`, [android/ndk#1969](https://github.com/android/ndk/issues/1969)),
  and `RTLD_DEFAULT` does **not** reach it even at API 35 — must `dlopen`
  `libnativehelper.so` by soname. With that, ART round-trip confirmed on an API-35
  emulator. Best-effort tier 3 (API 31+); SDL path (tiers 1–2) carries API 24–30.
  A 24–30 non-SDL check would just confirm the documented fall-through to RuntimeError.
- ~~Does `dlsym(RTLD_DEFAULT, ...)` find a host-loaded SDL getter on bionic at the
  target API levels?~~ **SETTLED EMPIRICALLY (Step 4): NO.** On a real p4a SDL2
  host (API 32) `dlsym(RTLD_DEFAULT, "SDL_AndroidGetJNIEnv")` returned NULL despite
  libSDL2 being loaded — an extension `dlopen`'d from site-packages doesn't see the
  host's `System.loadLibrary`'d SDL in its default scope. Fix applied: `dlopen` the
  SDL soname (`libSDL3.so`/`libSDL2.so`) and `dlsym` the handle (like tier 3). With
  that, tier 2 resolves and round-trips to `Dalvik`. Still open: **SDL3** host and
  **arm64 on real hardware** (only SDL2 + x86_64 emulator exercised so far).

---

## Productionization & consumption (2026-07-21)

Phase 1 of the delivery plan is done and committed (`1b45cf1`): the spike source
is now PR-quality and both wheels rebuild clean.

- **Code productionized.** Stripped the `__android_log_print` tier instrumentation
  from `jnius_jvm_android.pxi`; made the Android wheel **truly Java-free** in
  `setup.py` (skips `javac`/`is_jdk` and prunes `src/org/jnius/*` from
  `package_data` when `PLATFORM == 'android'`); pinned
  `LDFLAGS = -Wl,-z,max-page-size=16384` in `pyproject.toml`.
- **Rebuilt + verified** (`~/wheelhouse`, cp314): arm64_v8a + x86_64 are Java-free
  (only the `.so`), no libSDL `DT_NEEDED`, `0x4000` (16 KB) LOAD alignment,
  `dlopen`/`dlsym`-only. x86_64 on-device testbed: `ANDROID_SMOKE_OK vm.name=Dalvik`.
- **No desktop regression** (verified): desktop `build_ext` + `import jnius` +
  `autoclass` + a `Comparator` proxy round-trip all pass on Java 17. All `setup.py`
  changes are no-ops on the desktop path.
- **PR scaffolding added** (for the eventual upstream PR): `.github/workflows/
  android-wheels.yml` (cibuildwheel build+test matrix + release-triggered PyPI
  trusted-publishing) and `docs/source/android-wheel.rst` (runtime + Java-glue
  contract, build steps, 16 KB note).

**Build gotchas (baked into the CI workflow and the doc):**

- **Pre-generate `jnius.c`.** On Android `setup.py` compiles a pre-generated
  `jnius.c` (Cython is build-only); it's gitignored, so CI/local must run
  `printf "DEF JNIUS_PLATFORM = 'android'\n" > jnius/config.pxi && cython -3
  jnius/jnius.pyx -o jnius/jnius.c` first.
- **Build from a clean tree.** `python -m build --no-isolation` reuses
  `build/lib.android-*`; a stale dir from an earlier build **re-injects the Java
  payload** and silently breaks the Java-free guarantee. `rm -rf build` first. A
  fresh CI checkout is inherently clean.
- **Local-only: keep temp off the tmpfs.** In this WSL sandbox `/tmp` is a ~4 GB
  tmpfs and `GRADLE_USER_HOME` is pinned there; the x86_64 emulator testbed
  exhausts it. Set `TMPDIR` and `GRADLE_USER_HOME` to the big ext4 disk. Hosted CI
  runners are unaffected.

**kivyforge consumption (interim, before the wheel is on PyPI):**

1. `pip install` the local `pyjnius-1.7.0-cp314-cp314-android_24_arm64_v8a.whl`
   (from `~/wheelhouse` / a local index) into the app's site-packages.
2. kivyforge's bootstrap emits `org/jnius/NativeInvocationHandler.java` as a
   generated template (like `MainActivity.java`) and dexes it into the APK — the
   wheel ships none. Proven app-side in Step 5 (`sdl-host-test/javaglue/`).
3. Keep the wheel's `invoke0` contract and the template a **matched pair**
   (see the coupling warning above); a mismatch is a `ClassNotFound`/`NoSuchMethod`
   at first proxy creation.
4. Ensure the bootstrap libs are 16 KB-aligned and the APK is 16 KB zip-aligned
   (a kivyforge toolchain task — the wheel already satisfies its half).

---

## Appendix — draft p4a issue — OBSOLETE (removed 2026-07-20)

The draft `kivy/python-for-android` issue (asking the maintainer to teach the
prebuilt-wheel installer to extract a wheel's `.java/` glue into the bootstrap dex
path) is **obsolete**: p4a consumption is a non-concern under the kivyforge-only,
Java-free-wheel direction, and there is no longer any `.java/` payload to extract.
The full draft text is preserved in git history (pre-2026-07-20) should p4a interop
ever be revisited.
