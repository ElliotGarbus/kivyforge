# Android load-model prototype — findings (Phase 0)

**Date:** 2026-07-23. **Status:** the load-model gate is **GREEN** — 5/5 probe
markers passed on-device, twice (fresh process + warm relaunch).

The Phase-0 prototype (plan:
`.cursor/plans/kivyforge_android_backend.plan.md`) is a hand-built Gradle app —
no kivyforge code — implementing the load model specified in
[05-bootstrap-android](../platforms/android/05-bootstrap-android.md) and
[04-gradle-project-generation](../platforms/android/04-gradle-project-generation.md):
version-stamped asset-bundle unpack, a `sys.meta_path` finder over **flattened**
extension `.so`s in `jniLibs/<abi>/`, the SDL2 → `libpython3.14` → `libmain`
load order, `SDL_main` launcher with `site_import = 0` and explicit module
search paths, and the pyjnius env/`invoke0` contract. The spike validated the
pyjnius *wheel* under p4a's bootstrap; this prototype validates **kivyforge's
own** bootstrap design.

- Prototype: WSL `~/kivyforge-android/proto/` (sources under the session
  scratchpad `proto/`; they become the Phase-3 template extraction base).
- Device: x86_64 API-32 emulator (`pyjnius_x86_64` AVD, WSL). Windows-host SDK
  (API 35 + NDK r27.3 + `kivyforge_x86_64` AVD) installed for later phases.
- Inputs: python.org `3.14.6` runtime (x86_64), spike pyjnius wheel
  (`android_24_x86_64`), SDL2 family `.so`s + stock SDL2 Java glue from the
  spike's p4a checkout, app-side `NativeInvocationHandler.java`.

## Probe results

```
PROTO_STDLIB_EXT=OK ssl=3.5.7      # _ssl/_sqlite3/zlib via the finder (flattened)
PROTO_UNPACK=OK skipped=1          # version-stamp skip on relaunch (fresh: 465 ms / 15 MB)
PROTO_JNIUS=OK vm=Dalvik           # wheel ext via finder; JNIEnv tier-2 (SDL_AndroidGetJNIEnv)
PROTO_PROXY=OK calls=4 ordered=['apple', 'banana', 'cherry']   # invoke0 round-trip
PROTO_ENV=OK all set               # ANDROID_ARGUMENT/APP_PATH/PRIVATE/UNPACK
PROTO_KIVY=OK kivy=2.3.1 window=(320, 640)   # ~50 Kivy extensions via finder; SDL window up
PROTO_ALL=OK passed=6/6
```

**The Kivy leg used an interim payload**: the spike's p4a harness compiled
Kivy 2.3.1 against Python 3.14 (same `cp314` ABI, `libpython3.14.so`
`DT_NEEDED`), so its compiled modules were staged through the same
flatten+manifest pipeline (final manifest: 120 extensions). This proves the
load model with real Kivy; the first-party cibuildwheel-built **wheel** (flat
`.libs/`, 16 KB flag) remains the open Phase-0 deliverable. Kivy needs
`filetype` (pure-Python dep) staged or `import kivy` fails — remember it in
example lock fixtures. Not yet exercised: arm64 hardware, SDL3.

## Confirmed design mechanics

1. **Flattened-extension finder works end to end.** Naming scheme
   `libpy.<dotted-module>.so` (e.g. `libpy._ssl.so`, `libpy.jnius.jnius.so`):
   Android's installer extracts them (the `lib` prefix + `.so` suffix satisfy
   the platform's native-lib extraction; dots in between are fine), and a stock
   `importlib.machinery.ExtensionFileLoader` pointed at
   `nativeLibraryDir/<file>` loads them. 68 extensions in the manifest.
2. **Flat-dir `DT_NEEDED` resolution works.** `libpy._ssl.so` needs
   `libssl_python.so`/`libcrypto_python.so`; both sit unrenamed in
   `jniLibs/<abi>/` and resolve via the linker default path — no rpath games.
3. **`module_search_paths_set = 1` cleanly bypasses `getpath`.** The bundle
   needs no prefix-shaped layout: `stdlib/`, `bootstrap/`, `app/` as explicit
   search paths + `home`/`prefix`/`exec_prefix` set to the bundle root. This is
   simpler than mimicking python.org's prefix layout and should be the
   production launcher's approach.
4. **`SDL_main` launcher model works** with stock SDL2 glue: SDLActivity loads
   `getLibraries()` in order, then `dlopen`s `libmain.so` and calls the
   exported `SDL_main` on the SDL thread. Export the symbol with default
   visibility explicitly.
5. **pyjnius contract holds under kivyforge's bootstrap** exactly as the spike
   findings predicted: tier-2 resolution fires with SDL2 loaded by the glue;
   the app-side (bootstrap-template) `NativeInvocationHandler` delivers
   `invoke0`.

## Corrections / decisions fed back into the design

1. **Use STOCK SDL Java glue — p4a's is incompatible.** p4a's patched
   `SDLActivity.onCreate` omits `loadLibraries()` and the surface/content-view
   setup (p4a does those in its own activity after its unpack task), so a
   plain subclass never starts the SDLMain thread → `SDL_main` never runs, with
   *no error anywhere*. The kivyforge bootstrap templates must vendor the
   stock `org.libsdl.app` glue at the exact SDL revision the shipped
   `libSDL2.so` was built from (05 already says this; now it's load-bearing
   fact, not preference).
2. **Bundle unpack moved to the Activity (Java), not `libmain`.** The 05
   flowchart puts unpack in the native launcher; the prototype does it in
   `PythonActivity.onCreate` *before* `super.onCreate()` (python.org's
   MainActivity model): assets API is right there, it runs before any SDL/
   native code, and env vars set via `Os.setenv` are inherited by the SDL
   thread. **Recommend updating 05**: Activity owns unpack + env contract;
   `libmain` owns interpreter init + finder + entry import.
3. **`PyConfig.use_system_logger` does not exist on the 3.14 Android build**
   (compile error). Python-level `sys.stdout`/`stderr` → logcat redirection is
   automatic on Android (tags `python.stdout`/`python.stderr`); update 05's
   PyConfig table accordingly. (Blank logcat lines appear after each print —
   the redirection emits the trailing newline as a separate write; harmless,
   worth knowing for smoke-test log parsing.)
4. **AAPT silently drops `_python_bundle` by default.** The default
   `ignoreAssetsPattern` excludes asset dirs starting with `_`. The generator
   MUST set `aaptOptions.ignoreAssetsPattern` (the testbed's trick: set it to
   a nonexistent name) or the bundle name must not start with underscore.
   Silent-failure class: the APK simply ships without the bundle.
5. **AGP auto-decompresses `.gz` assets** (testbed works around it by renaming
   with a trailing `-` and undoing at extract). The prototype excluded `.gz`
   stdlib files instead; the production stager must adopt the rename-dance or
   exclusion policy explicitly.
6. **Asset compression is fine for the bundle** (stream-extracted, not
   mmapped): the prototype shipped default-compressed assets and unpacked in
   465 ms. 04's "packaged uncompressed via noCompress" is an optimization
   choice, not a correctness requirement — keep or drop deliberately.

## Runtime-package facts (for `stage/runtime.py` + the lock provider)

- Artifact naming: `python-3.14.6-<aarch64|x86_64>-linux-android.tar.gz`
  (+ `.crt`/`.sig`/`.sigstore` siblings) — **differs from the illustrative URL
  in 02**; resolve from the release file listing as designed. SHA-256s
  recorded in `~/kivyforge-android/runtime/`.
- Layout: `README.md`, `android-env.sh`, `android.py`, `prefix/`, `testbed/`.
  `prefix/lib` holds `libpython3.14.so`, `libpython3.so` (stub),
  `lib{ssl,crypto,sqlite3}_python.so` (renamed sonames for app use), plain
  `lib{ssl,crypto,sqlite3}.so` + `engines-3/` + `ossl-modules/` (NOT needed at
  runtime — the prototype shipped only `libpython*` + `lib*_python.so` and ssl
  worked), stdlib at `prefix/lib/python3.14` with `lib-dynload/` (67 ext .so).
- The package ships its own **`testbed/` Gradle app** (the cibuildwheel
  harness) — the authoritative integration reference; and `android.py` with
  `test --connected/--managed`, directly reusable for CI ideas.
- The testbed pins: Gradle 8.11.1 wrapper (NO `gradle-wrapper.jar` in the
  package — bring your own), AGP 8.10.0, `compileSdk 35`,
  `-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON` (the CMake-side 16 KB flag for
  the launcher build — adopt in the kivyforge CMake template).

## Operational notes

- WSL Gradle builds: keep `GRADLE_USER_HOME`/`TMPDIR` off the small tmpfs
  (carried over from the spike findings).
- Harmless SELinux denial in logs: SDL reads `/proc/sys/vm/overcommit_memory`
  (`avc: denied` audit line) — cosmetic, don't chase it.
- Probe pattern worth keeping for the Phase-5 smoke test: markers to stdout
  (logcat `python.stdout`) **and** a `run-as`-readable file sink
  (`files/proto_markers.txt`) — the file survives logcat buffering issues.

## Phase-5 findings (first-party build, Windows-host emulator)

The Phase-0 prototype was hand-assembled; Phase 5 ran the **generated**
project (`kivyforge lock`/`build`/`run`) on the Windows-host `kivyforge_x86_64`
API-35 emulator. Two Kivy-compatibility gaps surfaced that the prototype's
narrower `import kivy` + `Window` probe never reached:

1. **Kivy hard-depends on `org.renpy.android.Hardware`.** `kivy/metrics.py`
   `get_dpi`/`get_fontscale` call `autoclass('org.renpy.android.Hardware')` at
   startup (DPI via `PythonActivity.mActivity.getWindowManager()`). The design
   doc's "namespace preservation" (05) covered `org.kivy.android.*` but not
   this legacy `org.renpy.android.*` shim. **Fix:** the bootstrap now vendors
   p4a's MIT `Hardware.java` and `render.py` emits it. This is Kivy's expected
   ABI, not optional.
2. **`org.kivy.android.PythonActivity.mActivity` must exist.** Kivy reaches the
   activity through this static (`app.py`, `metrics.py`). The prototype's
   activity used SDLActivity's `mSingleton`; the template now also exposes
   `public static PythonActivity mActivity`, set in `onCreate`.

Both are covered by the bootstrap diff-clean + compat tests. General rule for
the docs: **the kivyforge bootstrap must satisfy every Java class Kivy's own
Python autoclasses**, not only the ones app code uses directly — surface these
in 05's namespace-preservation section.

Harness note: assert on the log captured *during* the run (android_run now
returns it), never a second independent `logcat -d` — the ring buffer races.

## Entry-point contract: no `if __name__ == "__main__"` guard

kivyforge **imports** the entry-point module (`PyImport_ImportModule(entry_point)`
— the common bootstrap contract, shared with iOS), so `__name__` is `"main"`,
not `"__main__"`. An app whose `App().run()` sits under
`if __name__ == "__main__":` **silently never starts** (the module imports
cleanly, `entry-point import returned 0`, `Finished main function`, no error).
The app must call `run()` at module top level. This is a real migration trap
from **buildozer/p4a**, which run `main.py` as `__main__`. Surface it in the
user docs and the `init` template comment. (Caught by the Phase-8 example gate:
`DEVICEINFO_OK` was missing with no traceback until the guard was removed.)

## Interim Kivy wheel — 16 KB alignment gap (doctor-caught)

The interim Kivy 2.3.1 wheels packed from the spike's p4a build (NDK r27,
no explicit `-Wl,-z,max-page-size=16384`) are **4 KB-aligned**; `kivyforge
doctor`'s 16 KB check correctly **FAILs** on them (42 `.so`s at `0x1000`),
while the cibuildwheel-built pyjnius wheel passes (`0x4000`). This is the
expected state and validates the doctor check — the interim wheel is a proven-
functional stand-in for emulators / 4 KB-page devices, and the first-party
cibuildwheel Kivy wheel (Phase-0 open deliverable) resolves it by pinning the
flag (spike Step 7 wheel-build policy). Not a code defect; the honest FAIL is
the point.

## The SDL Java glue and `libSDL2.so` are a matched pair (silent failure)

Swapping in the first-party Kivy wheel — which carries the officially-built
**SDL 2.32.10** family in its flat `.libs/` — against bootstrap templates still
holding the prototype's **2.30.11** Java glue produced an app that launched,
unpacked its bundle, reached `RESUMED`, and then **did nothing at all**: no
Python, no `SDL_main`, no traceback, nothing in logcat, a black screen.

The cause is a check inside stock `SDLActivity.onCreate`:

```java
String version = nativeGetVersion();                 // from libSDL2.so
if (!version.equals(expected_version)) {             // Java-side constants
    mBrokenLibraries = true;
    errorMsgBrokenLib = "SDL C/Java version mismatch (...)";
}
if (mBrokenLibraries) { ...; return; }               // before the surface exists
```

Unlike the `UnsatisfiedLinkError` path beside it, this branch writes nothing to
`System.err`, so **the mismatch leaves no trace in logcat**. `onCreate` returns
before `mSurface` is created, so SDL never starts its thread and `SDL_main` —
kivyforge's entire launcher — is never called. The symptom is indistinguishable
from a hung interpreter.

Two consequences, both now enforced:

1. The glue in `bootstrap/templates/sdl2/org/libsdl/app/*.java` must be taken
   from the **same SDL release tarball** as the `libSDL2.so` shipped in the
   Kivy wheel (recipe step 2 said so; it had not actually been applied).
   Templates are now SDL 2.32.10, matching the wheel.
2. `check_sdl_glue_contract()` (`bootstrap/contract.py`) compares the rendered
   `SDLActivity.java` constants against the `release-X.Y.Z` string SDL stamps
   into `libSDL2.so`, and **fails the build** naming both versions. It sits
   beside the pyjnius `invoke0` gate because it is the same kind of contract:
   generated Java paired with a binary nothing links it to. A `.so` with no
   version stamp is not a build failure — unverifiable, not wrong.

## Benign Kivy warnings on a kivyforge app

Kivy 2.3.1 logs two warnings that are **expected** and not defects:

```
[WARNING] [Base] Unknown <android> provider
[WARNING] [Base] Failed to import "android" module. Could not remove android presplash.
```

Both come from Kivy looking for python-for-android's `android` Python module,
which kivyforge deliberately does not ship. Kivy degrades cleanly (the input
provider is skipped; there is no p4a presplash View to remove — kivyforge uses
the androidx core-splashscreen system splash, which dismisses itself). This
coupling is exactly what the Kivy 3 bootstrap contract removes.

## Gate status

**Load-model gate: PASSED, all six legs including Kivy.** Phase 0 is now
**closed**: the first-party Kivy 2.3.1 cross-build is done and validated
on-device for both locked ABIs.

| Leg | x86_64 (emulator, API 31) | arm64-v8a (Pixel 8a, Android 16 / API 36) |
|---|---|---|
| Contract smoke test | PASS | PASS |
| `EXT_OK` (flattened-extension finder) | PASS | PASS |
| `PROXY_OK` (pyjnius `invoke0`) | PASS | PASS |
| `KIVY_CONTRACT_OK` (Kivy 3 Activity contract) | PASS | PASS |
| Kivy app renders | main loop runs; GL live | **verified visually** |

Kivy reports `v2.3.1` on CPython `3.14.6` with `sdl2` window/text/image
providers on both. The emulator's SwiftShader GL surface does not appear in
`adb screencap` (a capture limitation, not an app failure), so the visual
confirmation comes from the Pixel's Mali-G715.

## Kivy 3.0 / SDL3 on-device (first run)

The [`hello-sdl3`](../../../examples/mobile/hello-sdl3) example is the SDL3 gate
— deliberately the same shape as `hello-android`, so a difference between them
is a difference in the bootstrap, not the app.

| Leg | x86_64 (emulator, API 31) | arm64-v8a (Pixel 8a, Android 16 / API 36) |
|---|---|---|
| Contract smoke test | PASS | PASS |
| `EXT_OK` / `PROXY_OK` / `KIVY_CONTRACT_OK` | PASS | PASS |
| Kivy 3.0 starts, reaches main loop | PASS | PASS |
| Kivy app renders | main loop runs; GL live | **verified visually** |

On the Pixel, `kivyforge run -p android --arch arm64_v8a --smoke` reports
`Contract smoke test PASSED`, and a plain launch logs:

```
[Kivy   ] v3.0.0.dev0
[Python ] v3.14.6
[Image  ] Providers: img_tex, img_dds, img_sdl3, img_thorvg_svg
[Text   ] Providers: text_sdl3
[Window ] Provider: sdl3
[GL     ] Backend used <sdl3>
[GL     ] OpenGL renderer <b'Mali-G715'>
[Base   ] Start application main loop
```

`adb screencap` shows the app's label rendered on the Mali surface — the first
visual confirmation of Kivy 3.0 / SDL3 on Android under kivyforge, and the
thing the emulator could not supply.

Two honest bounds on what this proves:

- **`libc++_shared.so` was the trap.** Kivy's `_img_sdl3` carries a
  `DT_NEEDED` on it; SDL2 needed no C++ runtime, so nothing shipped one. Every
  structural check passed and the app ran — Kivy just listed `img_sdl3` among
  *ignored* providers, so PNGs would silently not load. It is visible above as
  `img_sdl3` being **present**, and only debug-level logging exposed the cause.
  The wheels repo now ships the runtime.
- **`kivy.mobile` is still a stub.** Kivy warns
  `kivy.mobile Android support is not yet implemented. All kivy.mobile calls
  will return safe fallback values.` The Activity-resolution half of the
  `_kivy_bootstrap` contract is exercised (`KIVY_CONTRACT_OK`); the
  platform-services half that would sit on top of it is not yet written
  upstream, so this run cannot vouch for it.
