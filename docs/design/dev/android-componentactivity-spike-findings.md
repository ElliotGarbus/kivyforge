# Android bootstrap on `ComponentActivity` — spike findings

A throwaway spike for roadmap item 8's open question, "verify the
`ComponentActivity` obligation against the current bootstrap", prompted by
issue #85 (SDKs that need code in the activity's `onCreate`). Run on a scratch
worktree of `main` @ `1aa9a183`, nothing committed. Date: 2026-10-05.

**Summary.** Making the bootstrap activity an AndroidX `ComponentActivity` is a
one-line change per SDL generation and needs no new dependency. With it, both
generations build, pass the contract smoke test, and deliver activity results
through the AndroidX registry to Python, and Back behaves as before.
**Permission results do not arrive**: SDL's own `onRequestPermissionsResult`
does not call `super`, so `ComponentActivity` never sees them. That needs a
second change before this could ship. Option 3 alone also does not serve SDKs
that must register in `onCreate`; those need an app-owned activity subclass
(#85's option 1) as well.

The recommendation from the spike is **not to ship this yet**. No user is
blocked (#85's Paystack case works without it, see below), it means carrying a
patch to SDL's stock Java glue for both generations, and the spike did not
cover a real SDK, a physical device, keyboard input, or state restore after
process death.

## Environment

| Item | Value |
|---|---|
| Host | Windows 11 (10.0.26200, AMD64), JDK 17.0.19, NDK 27.3.13750724, CMake 3.22.1, Gradle 8.11.1 |
| Device | `kivyforge_x86_64` AVD, Android 15 (API 35) |
| kivyforge | `main` @ `1aa9a183` plus the patch below, uncommitted |
| SDL2 app | Kivy 2.3.1 (`kivy_generation = 2`), pyjnius 1.8.0, CPython 3.14.6 |
| SDL3 app | Kivy 3.0.0.dev202607301604 (`kivy_generation = 3`), pyjnius 1.8.0, CPython 3.14.6 |
| Project | One scratch project locked once per generation (the #66 test project), `uses = ["INTERNET", "CAMERA"]` so a permission has to be requested |

## Where the bootstrap stands today

The generated project is AndroidX at the project level but not at the activity
level:

- `android.useAndroidX=true` (`generate/project.py`), and every app depends on
  `com.google.android.material:material:1.11.0`. Gradle's `dependencyInsight`
  shows Material brings in `androidx.activity:activity:1.8.0` and
  `androidx.appcompat:appcompat:1.6.1`, so `ComponentActivity` is already on
  every app's classpath.
- The default theme is `Theme.Material3.DayNight.NoActionBar`.
- But `PythonActivity extends SDLActivity`, and SDL's stock
  `SDLActivity extends Activity` (`android.app.Activity`), in both
  `templates/sdl2/` and `templates/sdl3/`.

An SDK that needs a `ComponentActivity` (activity-result registration,
lifecycle owner, back dispatcher) checks the activity it is given, so having
the library on the classpath does not help.

## The patch

In `templates/sdl2/org/libsdl/app/SDLActivity.java` and the `sdl3` copy, line 60:

```diff
-public class SDLActivity extends Activity implements View.OnSystemUiVisibilityChangeListener {
+public class SDLActivity extends androidx.activity.ComponentActivity implements View.OnSystemUiVisibilityChangeListener {
```

Nothing else changed. `ComponentActivity`'s `final` methods (`getLifecycle`,
`onRetainNonConfigurationInstance`, ...) do not collide with anything SDL or
`PythonActivity` overrides, and javac agreed.

## Results

A probe app (pyjnius, run from `on_start`) printed the activity's class chain
and lifecycle state, tried `registerForActivityResult`, then used
`getActivityResultRegistry().register(...)` to open Settings and to request
`CAMERA`. A script pressed Back on each system screen and then inside the app.

| Check | SDL2 | SDL3 |
|---|---|---|
| Builds; no `final`-method clashes | PASS | PASS |
| `run --smoke` (load order, extension finder, pyjnius `invoke0`) | PASS (2 tests) | PASS (2 tests) |
| Class chain | `PythonActivity > SDLActivity > androidx.activity.ComponentActivity > androidx.core.app.ComponentActivity > android.app.Activity > ...` | same |
| `getLifecycle().getCurrentState()` | `RESUMED` | `RESUMED` |
| `registerForActivityResult(...)` from Python after startup | Refused: `IllegalStateException: LifecycleOwner ... is attempting to register while current state is RESUMED` | same |
| Activity result via the registry (Settings, then Back) | Python callback got `ActivityResult{resultCode=RESULT_CANCELED, data=null}` | same |
| Permission result via the registry (`CAMERA` dialog, then Back) | **Callback never called** | **Callback never called** |
| Back inside the app, compared with the unpatched build | Unchanged: `onPause`, `onStop`, app to background, process alive | Unchanged: app stays in front (Kivy 3 handles Back) |

The unpatched build, run the same way, prints a class chain going straight from
`SDLActivity` to `android.app.Activity`, and `getLifecycle` does not exist
(`AttributeError`).

## Defect: permission results stop in SDL's handler

The permission answer reaches `PythonActivity.onRequestPermissionsResult`
(logcat: `V kivyforge: onRequestPermissionsResult()`), which calls `super`. That
is SDL's handler, which forwards the result to native code and does not call
`super`:

```java
// sdl2 SDLActivity.java:1796, sdl3 :1962
public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
    boolean result = (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED);
    nativePermissionResult(requestCode, result);
}
```

`ComponentActivity` routes permission results to its registry from its own
`onRequestPermissionsResult`, so with SDL in between, any AndroidX SDK that asks
for a permission through `ActivityResultContracts.RequestPermission` waits
forever. Two fixes, neither tested:

- **Add `super.onRequestPermissionsResult(...)` to SDL's handler.** Simple, and
  the SDL patch becomes two lines per generation.
- **Forward from `PythonActivity`**, calling
  `getActivityResultRegistry().dispatchResult(...)` the way `ComponentActivity`
  does internally. Leaves SDL at one changed line, but copies AndroidX's
  internal behaviour, which could change between releases.

Activity results have no such problem: `PythonActivity.onActivityResult` and
SDL3's both call `super`, and SDL2 does not override it.

## What option 3 does not do on its own

SDKs that need a `ComponentActivity` usually register for results in
`onCreate`, because Android refuses registration once the activity has started
(the refusal above). Python only runs after `onCreate`, so those SDKs also need
code that runs there: an app-owned subclass of `PythonActivity` (#85's option 1).
The two options combine. A subclass inherits `ComponentActivity` once the
bootstrap has it, so doing option 1 first costs nothing toward this.

## Related: #85's actual case needs neither

The SDK in #85, `co.paystack.android:paystack:3.1.3`, was tested separately on
the same emulator (Kivy 2.3.1, unpatched `main`). It locks (50 Maven
coordinates) and builds. `PaystackSdk.initialize` works from Python, as does
the public key from manifest `<meta-data>` or `setPublicKey`. `Card` needs its
month and year boxed as `java.lang.Integer`. An invalid card opens Paystack's
own card-entry activity over Kivy, and cancelling it calls a pyjnius
`TransactionCallback.onError`, with Kivy's `@mainthread` moving the result onto
Kivy's thread. The recipe is in the #85 reply.

## Not covered

- A real third-party SDK that requires `ComponentActivity`. The probe used
  AndroidX's APIs directly.
- A physical device.
- Keyboard and IME input, which `SDLActivity` handles itself.
- Saved-state restore after process death.
- SDL3's file dialog, which uses `onActivityResult`. Its handler calls `super`,
  so it should be unaffected.

## If this is picked up

Ship it as its own PR, after option 1, with:

- the patch to both `SDLActivity` copies, and the permission-result fix;
- an exception for those lines in `scripts/check_sdl_glue_sync.py`, which
  otherwise requires the glue to be byte-identical to upstream, and a note so
  each SDL update re-applies them;
- a run of the target SDK on a physical device, plus a keyboard check;
- a smoke-test assertion that the activity is a `ComponentActivity`, so a
  future SDL update cannot silently drop the patch.
