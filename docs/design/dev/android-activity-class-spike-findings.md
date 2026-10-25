# An app-owned `PythonActivity` subclass — spike findings

A throwaway spike for the design questions behind
[`android-activity-class-proposal.md`](android-activity-class-proposal.md)
(issue [#85](https://github.com/ElliotGarbus/kivyforge/issues/85), SDKs that
need code in the activity's `onCreate`). Run against `main`-equivalent
`25c0483d` (branch `include-files-relock-176`, editable install), nothing in the
repo changed. Scratch project in `%TEMP%\kf-spike-85`, not committed.
Date: 2026-10-23.

**Summary.** A subclass of the generated `org.kivy.android.PythonActivity`,
compiled from the app's own Java and named as the launcher activity, works
with no bootstrap change: every lifecycle override and every result callback
reaches it, `mActivity` is the subclass instance, pyjnius reaches it through
the base class and the subclass alike, and Kivy 3's bootstrap contract returns
it. Code placed after `super.onCreate()` runs about 0.8 s before the first line
of the app's Python, which starts on SDL's thread after the surface exists; so
a Java subclass is the only place "run this in `onCreate`" can be satisfied.
Separately, a library-style hook that never touches the activity — a
`ContentProvider` registering `Application.ActivityLifecycleCallbacks`, the
pattern Sentry and AndroidX App Startup use — also works in a kivyforge app
today, unchanged, and can reach the p4a listener registries from
`onActivityCreated`.

**Two defects, one blocking.** `[tool.kivy.android.src].java` has never
compiled anything: the generated `app/build.gradle` names the source root
relative to the `app/` module, where it does not exist, and Gradle ignores a
missing source directory without a word. The subclass design depends on this
key, so the fix is a prerequisite. And three places in kivyforge name the base
class by string (`run`'s launch, the instrumented smoke test, the release
export allowlist); with a subclass as the launcher, the first two fail outright
(`Error: Activity class ... does not exist`), the third would refuse to package.

## Environment

| Item | Value |
|---|---|
| Host | Windows 11 (10.0.26200, AMD64), JDK 17.0.19 (Temurin), build-tools 35.0.0, NDK 27.3.13750724, CMake 3.22.1, AGP 8.10.0, Gradle 8.11.1 |
| Device | `kivyforge_x86_64` AVD, Android 15 (API 35), x86_64 |
| kivyforge | `25c0483d`, unmodified (editable install) |
| App | Kivy 2.3.1 (`kivy_generation = 2`), pyjnius 1.8.0, CPython 3.14.6, `abis = ["x86_64"]`, `uses = ["INTERNET", "CAMERA"]` |
| Scratch project | `hello-android` copied, plus `[tool.kivy.android.src] java = ["android/java"]`, a `<provider>` through `extra_application_xml`, and a `main.py` that reports what Python sees |

## Method

Two Java classes in `android/java/org/example/spike/`:

- `SpikeActivity extends PythonActivity`: logs before and after
  `super.onCreate()`, in `onStart`, `onResume`, `onPause`, `onNewIntent` and
  `onRequestPermissionsResult`, each calling `super`; after `super.onCreate()`
  it registers a p4a `ActivityResultListener` from Java, as SDK glue would. A
  `public static String marker` exists only on the subclass.
- `SpikeInitProvider extends ContentProvider`: in `onCreate()`, registers an
  `Application.ActivityLifecycleCallbacks` on the application context that logs
  `onActivityPreCreated`/`Created`/`PostCreated`/`Started`/`Resumed`/`Paused`,
  and from `onActivityCreated` casts the activity to `PythonActivity` and
  registers a `NewIntentListener`. Declared in the manifest with
  `android:authorities="${applicationId}.spikeinit"`.

`main.py` prints a marker at import, then in `on_start` prints
`autoclass("org.kivy.android.PythonActivity").mActivity.getClass().getName()`,
whether `autoclass("org.example.spike.SpikeActivity").mActivity` is the same
object, `sub.marker`, `android.config.ACTIVITY_CLASS_NAME`, and
`_kivy_bootstrap.get_activity().getClass().getName()`; one second later it
calls `android.permissions.request_permissions([CAMERA], callback)`.

Steps, with the stock tool wherever it could do the job:

1. `kivyforge lock -p android` — 8 packages pinned.
2. `kivyforge build -p android --debug --abi x86_64` — `BUILD SUCCESSFUL in 23s`.
3. The one thing kivyforge has no key for: in the generated
   `spike85-android/app/src/main/AndroidManifest.xml`, `android:name` of the
   launcher `<activity>` changed from `org.kivy.android.PythonActivity` to
   `org.example.spike.SpikeActivity`, then `gradlew assembleDebug` in the
   generated project. (The loader rejects `android:name` through
   `[tool.kivy.android.manifest].activity`: it is a managed attribute.)
4. `aapt dump badging`: `launchable-activity: name='org.example.spike.SpikeActivity'`.
5. `adb install -r -t`, `adb shell am start -W -n org.kivyforge.spike85/org.example.spike.SpikeActivity`, `adb logcat -d -v threadtime`.
6. Tap "While using the app" on the permission dialog; `am start --activity-single-top` against the running activity for `onNewIntent`.
7. `am start -n org.kivyforge.spike85/org.kivy.android.PythonActivity`, which is what `kivyforge run` does today.

## Defect 1 (blocking): `[tool.kivy.android.src].java` compiles nothing

The first launch after step 3 died before any activity existed:

```
E AndroidRuntime: java.lang.RuntimeException: Unable to get provider org.example.spike.SpikeInitProvider:
    java.lang.ClassNotFoundException: Didn't find class "org.example.spike.SpikeInitProvider" on path: DexPathList[...]
```

Neither class was in the APK. The generated module says:

```
# spike85-android/app/build.gradle, line 61
java.srcDirs += 'android/java'
```

Gradle resolves that against the module directory, `spike85-android/app/`, so
it points at `spike85-android/app/android/java`, which does not exist, and a
missing `srcDir` is silently empty. The user's sources are at
`<project>/android/java`, two levels up. `app/build/intermediates/javac/debug`
held no `Spike*.class`. The build had reported success, and the docs
([`java-libraries.md`](../../guides/guides/android/java-libraries.md) and the
reference) describe the key as working.

The path is written by `generate/project.py`:

```
src_dirs = "".join(
    f"            java.srcDirs += '{_gradle_path(Path(p))}'\n"
    for p in [*android.src.java, *android.src.kotlin]
)
```

and the only test (`tests/platforms/android/test_generate.py:557`) asserts the
literal `java.srcDirs += 'extra/java'`, so it pins the bug. No example uses the
key, and nothing in `test-matrix.md` §7 says it was ever exercised; this is the
first time.

**Workaround used for the rest of the spike:** `java.srcDirs += '../../android/java'`
in the generated file, then `gradlew assembleDebug`. Both classes then compiled
(`SpikeActivity.class`, `SpikeActivity$1.class`, `SpikeInitProvider.class`,
`SpikeInitProvider$1.class`, `SpikeInitProvider$1$1.class`).

## Defect 2: three string references to the base class

After step 3 the APK's only launcher is the subclass, so:

```
$ adb shell am start -n org.kivyforge.spike85/org.kivy.android.PythonActivity
Error type 3
Error: Activity class {org.kivyforge.spike85/org.kivy.android.PythonActivity} does not exist.
```

That is the command `kivyforge run -p android` issues
(`platforms/android/cli.py`, `adb_mod.launch(device, android.package, "org.kivy.android.PythonActivity")`).
The same is true by inspection of:

- `bootstrap/templates/androidtest/KivyforgeContractTest.java`:
  `new Intent(ctx, org.kivy.android.PythonActivity.class)` — an explicit intent
  to a component the manifest no longer declares, so `run --smoke` would fail
  with `ActivityNotFoundException` before any self-test ran.
- `platforms/android/policy.py`: `BOOTSTRAP_EXPORTED` tolerates
  `org.kivy.android.PythonActivity` as exported; the subclass is exported (it
  is the launcher) and is not in the set, so `kivyforge package` would FAIL
  the release policy unless the user added their own launcher to
  `allow_exported`.

Not defects, but also fixed-string today and listed because the proposal has
to decide each: `generate/manifest.py` `MAIN_ACTIVITY`,
`tests/artifact_checks.py` (imports `MAIN_ACTIVITY` for the merged-manifest
check), `bootstrap/templates/android_pkg/config.py` `ACTIVITY_CLASS_NAME`, and
`bootstrap_py/_kivy_bootstrap.py` `_ACTIVITY_CLASS`.

## Results

Every check passed once the two workarounds above were in place.

| Check | Result |
|---|---|
| Subclass compiles against the generated `PythonActivity` and is the launcher | PASS (`aapt dump badging`) |
| `onCreate` before `super`: what is available | `mActivity=null`; the bundle is not unpacked; SDL and libpython not yet loaded (nativeloader lines follow `SDL onCreate()`) |
| `onCreate` after `super`: what is available | `mActivity` is `org.example.spike.SpikeActivity`; SDL2 family, `libpython3.14.so`, `libmain.so` loaded; Python not started |
| Time from "after super" to the first Python line | 39.040 -> 39.820 (`PY_MAIN_START`), 0.78 s; `on_start` at 41.302; `Start application main loop` at 41.440 |
| `onStart`, `onResume`, `onPause` overrides | PASS, each after SDL's own |
| `onRequestPermissionsResult` override, then the p4a path | PASS: subclass logged `granted=true`, then `kivyforge: onRequestPermissionsResult passed to callback`, then Python printed `['android.permission.CAMERA'] [True]` |
| `onNewIntent` override | PASS (`am start --activity-single-top`) |
| p4a `ActivityResultListener` registered from Java in the subclass | Registered without error (no result was produced to deliver) |
| `autoclass("org.kivy.android.PythonActivity").mActivity` | the subclass instance |
| `autoclass("org.example.spike.SpikeActivity").mActivity` | same object (`hashCode` equal); `sub.marker = set-by-SpikeActivity` |
| `android.config.ACTIVITY_CLASS_NAME` | still `org.kivy.android.PythonActivity` (fixed in the template; p4a substitutes its `--activity-class-name` here) |
| `_kivy_bootstrap.get_activity()` | the subclass instance, with the base-class string unchanged |
| `ContentProvider` runs before any activity | PASS: `SpikeInitProvider.onCreate` at 38.194, `application class=android.app.Application`; first activity callback at 38.246 |
| `ActivityLifecycleCallbacks` sees the subclass | PASS: `onActivityPreCreated`, `onActivityCreated` (inside `super.onCreate`), `onActivityPostCreated`, `Started`, `Resumed`, `Paused`, all naming `org.example.spike.SpikeActivity` |
| p4a registry reached from `onActivityCreated` without a subclass | PASS: `ALC-registered listener: onNewIntent` fired |
| `androidx.startup` already present | `androidx.startup:startup-runtime:1.1.1` is on every app's classpath (Material 1.11.0 -> emoji2 1.2.0 -> lifecycle-process), and `androidx.startup.InitializationProvider` is in the merged manifest (`dumpsys package`) |
| Today's `run` launch command against the subclass APK | **FAIL**, `Error type 3` (Defect 2) |

### The ordered log

Process 3727; main thread 3727, SDL thread 3781. Noise removed, nothing reordered.

```
17:36:38.194  3727 I spike85 : SpikeInitProvider.onCreate: application class=android.app.Application
17:36:38.246  3727 I spike85 : ALC.onActivityPreCreated org.example.spike.SpikeActivity
17:36:38.246  3727 I spike85 : SpikeActivity.onCreate BEFORE super: mActivity=null
17:36:38.251  3727 I kivyforge: unpacking bundle...
17:36:38.935  3727 I kivyforge: bundle unpacked in 684 ms
17:36:38.936  3727 V SDL     : onCreate()
17:36:38.937  3727 I spike85 : ALC.onActivityCreated org.example.spike.SpikeActivity
17:36:38.944  3727 D nativeloader: Load .../lib/x86_64/libSDL2.so ... ok
17:36:38.960  3727 D nativeloader: Load .../lib/x86_64/libpython3.14.so ... ok
17:36:38.963  3727 D nativeloader: Load .../lib/x86_64/libmain.so ... ok
17:36:39.040  3727 I spike85 : SpikeActivity.onCreate AFTER super: mActivity class=org.example.spike.SpikeActivity
17:36:39.041  3727 I spike85 : ALC.onActivityPostCreated org.example.spike.SpikeActivity
17:36:39.042  3727 V SDL     : onStart()
17:36:39.042  3727 I spike85 : ALC.onActivityStarted
17:36:39.042  3727 I spike85 : SpikeActivity.onStart
17:36:39.044  3727 V SDL     : onResume()
17:36:39.044  3727 I spike85 : ALC.onActivityResumed
17:36:39.044  3727 I spike85 : SpikeActivity.onResume
17:36:39.104  3727 V SDL     : surfaceCreated()
17:36:39.104  3727 V SDL     : surfaceChanged()
17:36:39.109  3781 V SDL     : Running main function SDL_main from library .../libmain.so
17:36:39.199  3781 I kivyforge: launcher: interpreter up
17:36:39.450  3781 I python.stdout: kivyforge bootstrap: finder installed (108 extensions)
17:36:39.820  3781 I python.stdout: spike85 PY_MAIN_START
17:36:41.302  3781 I python.stdout: spike85 PY_ON_START
17:36:41.435  3781 I python.stdout: base.mActivity class = org.example.spike.SpikeActivity
17:36:41.435  3781 I python.stdout: sub.mActivity is same = True
17:36:41.435  3781 I python.stdout: sub.marker = set-by-SpikeActivity
17:36:41.435  3781 I python.stdout: android.config.ACTIVITY_CLASS_NAME = org.kivy.android.PythonActivity
17:36:41.435  3781 I python.stdout: _kivy_bootstrap.get_activity() class = org.example.spike.SpikeActivity
17:36:41.440  3781 W python.stderr: [INFO   ] [Base        ] Start application main loop
17:36:41.456  3781 V kivyforge: addPermissionsCallback(): Added callback for onRequestPermissionsResult
17:36:41.469  3727 I spike85 : SpikeActivity.onPause            <- the permission dialog
17:36:41.470  3727 I spike85 : ALC.onActivityPaused
17:37:58.922  3727 I spike85 : SpikeActivity.onRequestPermissionsResult 2 granted=true
17:37:58.922  3727 V kivyforge: onRequestPermissionsResult()
17:37:58.922  3727 V kivyforge: onRequestPermissionsResult passed to callback
17:37:58.923  3727 I python.stdout: spike85 PY permission result ['android.permission.CAMERA'] [True]
17:37:58.925  3727 I spike85 : ALC.onActivityResumed
17:37:58.925  3727 I spike85 : SpikeActivity.onResume
17:38:01.947  3727 I spike85 : SpikeActivity.onPause            <- am start --activity-single-top
17:38:01.949  3727 I spike85 : SpikeActivity.onNewIntent
17:38:01.950  3727 I spike85 : ALC-registered listener: onNewIntent
17:38:01.950  3727 I spike85 : SpikeActivity.onResume
17:38:01.950  3727 I spike85 : SpikeActivity.onResume
```

The doubled `onResume` after `onNewIntent` is python-for-android's own
`onNewIntent`, which calls `this.onResume()` before dispatching and then the
framework resumes the activity again. Pre-existing, in the vendored p4a block,
not introduced here.

## What this settles for the proposal

1. **Python cannot host an `onCreate` hook.** Python's first line ran 0.78 s
   after the subclass's `onCreate` returned, on another thread, after the
   surface existed. Briefcase can offer `IPythonApp.onCreate` because Chaquopy
   runs Python synchronously inside `MainActivity.onCreate`; kivyforge's SDL
   model rules that out. Java it is.
2. **The subclass needs no bootstrap change and no new runtime contract.**
   `mActivity` is declared on the base and assigned in the base's `onCreate`,
   so every consumer of the base class name keeps working, and
   `autoclass(<subclass>)` works too because `Class.getFields()` includes
   inherited public statics.
3. **The composition problem is Android's to solve, and it already has.** A
   provider plus `ActivityLifecycleCallbacks` hooks the activity from library
   code with no slot to compete for, and App Startup is already in every
   kivyforge app. The single subclass slot is the app author's; library
   authors do not need it.
4. **`src.java` must be fixed first**, and the fix needs an on-device or
   dex-level check, because the failure mode is a successful build with the
   classes missing.
5. **Four string sites follow the key** (`manifest.py`, `cli.py` run,
   `KivyforgeContractTest.java`, `policy.py`); `_kivy_bootstrap.py` need not.
   The first draft of this point also had `android.config.ACTIVITY_CLASS_NAME`
   follow the key "for p4a parity". Review corrected that, and reading
   settles it: `ACTIVITY_CLASS_NAMESPACE` is the prefix of the nested
   interface names (`$NewIntentListener`, `$ActivityResultListener`,
   `$PermissionsCallback`, `$DarkModeListener`) in `activity.py`,
   `permissions.py` and `darkmode.py`, and nested-type binary names are not
   inherited, so a subclass value breaks every proxy at first creation; and
   `_kivyforge_selftest.py` calls `getDeclaredMethods()` on
   `ACTIVITY_CLASS_NAME`, which on a subclass reports every inherited method
   missing. This spike could not have seen either, because its
   `android/config.py` still named the base. p4a itself derives both
   constants from `--activity-class-name` (`recipes/android/__init__.py`), so
   p4a has the first bug; its manifest launcher is the *other* flag,
   `--android-entrypoint`. Both constants stay on the base in kivyforge.

## Spike 2 (2026-10-23): a compile-time check of the configured class

Review asked for the configured class to be proved at compile time rather
than by looking for a source file. The question was whether one generated
Java expression catches every wrong class, and what javac says when it does.

**Setup.** Same scratch project and host as above, Gradle daemon warm. A
script (`verifier-spike.ps1`, outside the repo) wrote
`app/src/main/java/org/kivy/android/KivyforgeLauncherCheck.java`:

```java
package org.kivy.android;

final class KivyforgeLauncherCheck {
    private KivyforgeLauncherCheck() {}

    static PythonActivity launcher() {
        return new <configured class>();
    }
}
```

then ran `gradlew :app:compileDebugJavaWithJavac --offline -q` once per
candidate class, with the negative cases added to the app's own source root
(`android/java/org/example/spike/`) for the run and removed afterwards.

**Result.** Eight runs, 24 s in total. The valid subclass compiled; every
other candidate failed on line 10 of the generated file with one message
naming the class:

| Candidate | exit | javac (first line) |
|---|---|---|
| `SpikeActivity` (valid) | 0 | — |
| `org.example.spike.DoesNotExist` | 1 | `error: cannot find symbol` / `symbol: class DoesNotExist` / `location: package org.example.spike` |
| `org.nowhere.Nothing` | 1 | `error: package org.nowhere does not exist` |
| `WrongBase extends android.app.Activity` | 1 | `error: incompatible types: WrongBase cannot be converted to PythonActivity` |
| `public abstract class AbstractAct extends PythonActivity` | 1 | `error: AbstractAct is abstract; cannot be instantiated` |
| `NoDefaultCtor` (only `NoDefaultCtor(int)`) | 1 | `error: constructor NoDefaultCtor in class NoDefaultCtor cannot be applied to given types;` |
| `PrivateCtor` (`private PrivateCtor()`) | 1 | `error: PrivateCtor() has private access in PrivateCtor` |
| `class NotPublic extends PythonActivity` (package-private) | 1 | `error: NotPublic is not public in org.example.spike; cannot be accessed from outside package` |

**What it settles.** `PythonActivity x = new <configured>()` is a complete
check of what Android needs of a launcher (exists, is a `PythonActivity`,
concrete, public, public no-arg constructor), and javac's messages are
specific enough to ship as the user-facing error without parsing. kivyforge
streams Gradle output rather than parsing it, so the failure surfaces as
`KF-BUILD-TOOL-FAILED` (exit 5) with the line above in the log. Not run: a
Kotlin subclass (the Kotlin plugin was not in the scratch project); Kotlin
classes are visible to javac in a mixed AGP module by design, so the same
expression should resolve, but that is for the implementation's T3 matrix.

## Not covered

- A physical device; the AVD only. (`run --smoke` and `package` were not run
  against the subclass because both fail by inspection today, Defect 2.)
- `kivy_generation = 3`. The subclass is the same Java either way; the SDL3
  glue's `onActivityResult` calls `super` as SDL2's does, so nothing suggests a
  difference, but it was not run.
- A Kotlin subclass (`src.kotlin`), which shares the srcDirs defect.
- A real third-party SDK in `onCreate`. The spike registered a p4a listener
  and requested a permission; it did not initialise a vendor SDK.
- Process death and recreation: whether the subclass's state survives is the
  app's business, as for any activity.
- An activity result delivered to the Java-registered `ActivityResultListener`
  (registered, not triggered).
