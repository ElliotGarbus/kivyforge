# AndroidX on a `main_activity` subclass — spike findings

Throwaway spikes for
[issue #184](https://github.com/ElliotGarbus/kivyforge/issues/184), which asks
the docs to say what AndroidX does and does not do on an app-owned subclass of
`PythonActivity`. Run on a scratch copy of `examples/mobile/android-activity-class`
outside the repo, with kivyforge at `4a2ec209` (branch `main-activity-85`).
Nothing from the scratch project is committed. Date: 2026-10-24.

**Summary.** The issue's lists hold, with two corrections. First, App Startup
and `ProcessLifecycleOwner` are in every APK but **not on the compile
classpath**: Material brings them in at runtime only, so Java that imports them
does not compile until the project declares them in
`[tool.kivy.android.gradle].dependencies`. Second, a Java permission request
from the subclass shares its request-code space with `android.permissions`,
which reuses codes from 2 upward and never forgets one: a Java request that
picks a code Python has used fires Python's callback again. Everything that
needs a `LifecycleOwner`, `FragmentActivity` or `AppCompatActivity` fails at
compile time with a javac message naming the type it wanted. A second activity
of the app's own that extends `AppCompatActivity` hosts a `DialogFragment` and
a `BiometricPrompt` correctly and returns its result to Python.

No kivyforge defect was found.

## Environment

| Item | Value |
|---|---|
| Host | Windows 11 (10.0.26200, AMD64), Temurin JDK 17.0.19, Gradle 8.11.1, AGP 8.10.0 |
| Device | `kivyforge_x86_64` AVD, Android 15 (API 35); no biometrics enrolled |
| kivyforge | `4a2ec209` (editable install), unmodified |
| App | Kivy 2.3.1 (`kivy_generation = 2`), pyjnius 1.8.0, CPython 3.14.6; `main_activity = "org.kivyforge.activityclass.MainActivity"`; `uses = ["INTERNET", "CAMERA"]` |
| Extra Maven deps (spikes A run 2, B, C) | `androidx.startup:startup-runtime:1.2.0`, `androidx.lifecycle:lifecycle-process:2.6.1`, `androidx.biometric:biometric:1.1.0` |

## Spike A — what compiles against the subclass

### Which AndroidX libraries a subclass can see

`gradlew :app:dependencies` for `debugCompileClasspath` and
`debugRuntimeClasspath`, with no `gradle.dependencies` declared. Count of tree
lines naming each artifact:

| Artifact | compile | runtime |
|---|---|---|
| `androidx.core:core` | 19 | 21 |
| `androidx.activity:activity` | 4 | 3 |
| `androidx.fragment:fragment` | 4 | 3 |
| `androidx.appcompat:appcompat` | 3 | 3 |
| `androidx.startup:startup-runtime` | **0** | 3 (1.1.1) |
| `androidx.lifecycle:lifecycle-process` | **0** | 7 (2.6.1) |
| `androidx.biometric:biometric` | 0 | 0 |

So the issue's "`startup` is present" is true of the APK and false of the
compiler.

### Run 1: no extra dependencies

Three probe classes in the `src.java` root, compiled with
`gradlew --offline :app:compileDebugJavaWithJavac`:

- `PositiveProbe` passes the subclass to `ContextCompat.checkSelfPermission`,
  `ContextCompat.getColor`, `ActivityCompat.shouldShowRequestPermissionRationale`,
  `ActivityCompat.requestPermissions`, `WindowCompat.getInsetsController`
  (then `setAppearanceLightStatusBars`), `NotificationCompat.Builder` and
  `NotificationManagerCompat.from`. **No errors.**
- `NegativeProbe` and `UndeclaredProbe` — 13 errors, verbatim apart from the
  path prefix:

```
NegativeProbe.java:17: error: incompatible types: MainActivity cannot be converted to ViewModelStoreOwner
          new ViewModelProvider(act).get(ViewModel.class);
NegativeProbe.java:20: error: incompatible types: MainActivity cannot be converted to LifecycleOwner
          androidx.lifecycle.LifecycleOwner owner = act;
NegativeProbe.java:21: error: incompatible types: MainActivity cannot be converted to ComponentActivity
NegativeProbe.java:22: error: incompatible types: MainActivity cannot be converted to FragmentActivity
NegativeProbe.java:23: error: incompatible types: MainActivity cannot be converted to AppCompatActivity
NegativeProbe.java:14: error: cannot find symbol
          ActivityResultLauncher<String> l = act.registerForActivityResult(
    symbol:   method registerForActivityResult(RequestPermission,(granted)->{ })
NegativeProbe.java:16: error: cannot find symbol
          act.getLifecycle();
NegativeProbe.java:18: error: cannot find symbol
          act.getOnBackPressedDispatcher();
NegativeProbe.java:19: error: cannot find symbol
          new DialogFragment().show(act.getSupportFragmentManager(), "tag");
UndeclaredProbe.java:3: error: cannot find symbol
  import androidx.lifecycle.ProcessLifecycleOwner;
UndeclaredProbe.java:4: error: cannot find symbol
  import androidx.startup.AppInitializer;
```

(plus the two uses of those imports). `ViewModelProvider` and `DialogFragment`
themselves resolve: `lifecycle-viewmodel` and `fragment` are on the compile
classpath, and only the activity argument is wrong.

### Run 2: the three dependencies declared

`kivyforge lock` (3 Maven dependencies) then `kivyforge build -p android
--debug --abi x86_64`, with `NegativeProbe` removed, `UndeclaredProbe` kept and
one new probe constructing `BiometricPrompt(act, executor, callback)`. The
build failed at `compileDebugJavaWithJavac` (exit 5) on that probe alone;
`UndeclaredProbe`, the initializer of spike B and the `AppCompatActivity` of
spike C all compiled:

```
BiometricNegativeProbe.java:11: error: no suitable constructor found for BiometricPrompt(MainActivity,Executor,<anonymous AuthenticationCallback>)
    constructor BiometricPrompt.BiometricPrompt(FragmentActivity,Executor,AuthenticationCallback) is not applicable
      (argument mismatch; MainActivity cannot be converted to FragmentActivity)
    constructor BiometricPrompt.BiometricPrompt(Fragment,Executor,AuthenticationCallback) is not applicable
      (argument mismatch; MainActivity cannot be converted to Fragment)
```

## Spike B — the helpers and App Startup at runtime

`MainActivity.onCreate` calls `PositiveProbe.run(this)` after `super`. An
`androidx.startup.Initializer` (`SpikeInitializer`, depending on
`ProcessLifecycleInitializer`) records its time and adds a
`DefaultLifecycleObserver` to `ProcessLifecycleOwner`; it is declared with the
entry Android documents, pasted unchanged into `extra_application_xml`:

```xml
<provider android:name="androidx.startup.InitializationProvider"
          android:authorities="${applicationId}.androidx-startup"
          android:exported="false"
          tools:node="merge">
    <meta-data android:name="org.kivyforge.activityclass.SpikeInitializer"
               android:value="androidx.startup" />
</provider>
```

`main.py` prints the activity's class chain and `Class.isInstance` for four
AndroidX types, then runs the permission sequence below. Installed with
`adb install -g` (so `CAMERA` is granted and requests answer without a
dialog), launched with `am start -n org.kivyforge.activityclass/.MainActivity`,
log read after 40 s. An excerpt of the second run, with dates and PIDs removed
(`spike184` is the Java tag, `python.stdout` the Python lines):

```
19:45:27.083 I/spike184: SpikeInitializer.create at 4338015
19:45:28.278 I/spike184: MainActivity.onCreate after super at 4339182; initializer at 4338015; perm=0 color=ff000000 rationale=false insets=true notification=true notificationsEnabled=false
19:45:28.281 I/spike184: process ON_START
19:45:31.281 I/python.stdout: spike184: chain org.kivyforge.activityclass.MainActivity > org.kivy.android.PythonActivity > org.libsdl.app.SDLActivity > android.app.Activity > android.view.ContextThemeWrapper > android.content.ContextWrapper > android.content.Context > java.lang.Object
19:45:31.288 I/python.stdout: spike184: isInstance androidx.activity.ComponentActivity = False
19:45:31.288 I/python.stdout: spike184: isInstance androidx.lifecycle.LifecycleOwner = False
19:45:31.291 I/python.stdout: spike184: isInstance androidx.fragment.app.FragmentActivity = False
19:45:31.294 I/python.stdout: spike184: isInstance androidx.appcompat.app.AppCompatActivity = False
19:45:31.506 I/spike184: MainActivity.onRequestPermissionsResult 2:0
19:45:31.509 I/python.stdout: spike184: python callback #1 ['android.permission.CAMERA'] [True]
19:45:32.643 I/spike184: MainActivity.onRequestPermissionsResult 4711:0
19:45:34.509 I/python.stdout: spike184: after java 4711: python_cb=1 java='2:0,4711:0,'
19:45:34.642 I/spike184: MainActivity.onRequestPermissionsResult 2:0
19:45:34.645 I/python.stdout: spike184: python callback #2 ['android.permission.CAMERA'] [True]
```

- **Helpers:** every call returned a real value (`perm=0` is
  `PERMISSION_GRANTED`; the insets controller and the built `Notification` are
  non-null). `notificationsEnabled=false` is API 33+'s `POST_NOTIFICATIONS`,
  which the spike did not declare, not the subclass.
- **App Startup** ran 1.2 s before `MainActivity.onCreate` returned, and the
  process-level observer saw `ON_START`: `ProcessLifecycleOwner` is the
  lifecycle owner a kivyforge app *does* have.
- **Permission request codes.** The sequence was: Python
  `request_permissions([CAMERA], callback)` (its first request with a callback
  uses code 2); after that callback, Java `ActivityCompat.requestPermissions`
  with code 4711; then Java with code 2. Code 4711 reached the subclass's
  override and did not touch Python. Code 2 fired Python's callback a second
  time. The reason is in `android/permissions.py`: `python_callback` looks the
  code up in `_callbacks`, which grows from 2 with each Python request and is
  never pruned. Every result also reaches SDL's `nativePermissionResult`, as
  the ComponentActivity spike found; nothing visible happened there.
- **Concurrent requests.** In the first run, Kivy's clock fired the Java request
  while Python's was still pending. Android answered the Java one with empty
  arrays (`4711:none`) — its documented cancellation — and Python's arrived
  normally. Two requests in flight at once, from any two callers, is the
  app's problem.

## Spike C — a second activity for what needs a `FragmentActivity`

`HostActivity extends AppCompatActivity`, declared in `extra_application_xml`
with `android:exported="false"` and no theme of its own. In `onCreate` it shows
a `DialogFragment` (which dismisses itself in `onStart`), then constructs a
`BiometricPrompt` with itself and calls `authenticate`, finishing with the
outcome as extras. `main.py` starts it with `startActivityForResult(..., 77)`
and reads the result through `android.activity.bind(on_activity_result=...)`
(same run; `{...}` repeats the extras of the line above):

```
19:45:36.658 I/spike184: HostActivity.onCreate theme ok, lifecycle=INITIALIZED
19:45:37.022 I/spike184: HostActivity: DialogFragment shown
19:45:37.160 I/spike184: HostActivity: biometric error 11 You haven't set up Face Unlock
19:45:37.220 I/python.stdout: spike184: host activity result code=-1 extras={'dialog_shown': True, 'can_authenticate': 11, 'biometric_error': 11}
19:45:45.512 I/python.stdout: spike184: kivy clock alive after host activity; host_result=(-1, {...})
```

- The generated application theme (`Theme.Kivyforge`, parent
  `Theme.Material3.DayNight.NoActionBar`) is an AppCompat theme, so
  `AppCompatActivity` accepted it without an `android:theme` of its own.
- `BiometricPrompt` ran its whole path through the fragment manager; error 11
  is `ERROR_NO_BIOMETRICS`, the emulator having none enrolled.
- Kivy kept running after the host finished.

This is a route, not a recommendation: no real SDK, no physical device, and
an enrolled-biometric success path were not tried.

## What this changes in the docs

- The `main_activity` guide section and the proposal's §3.4 state the
  single-inheritance limit and the two lists from the issue, with
  `startup-runtime` and `lifecycle-process` marked "declare it".
- The guide gives the request-code rule: pick codes Python will not reach (it
  counts up from 2), and keep one request in flight.
- The App Startup form of the library route, which §3.4 deferred until #182,
  is shown in the guide.
- Proposal §4: `FragmentActivity`/`AppCompatActivity` SDKs stay out of scope;
  this spike's second-activity route is recorded there as observed.

## Not covered

- SDL3 (`kivy_generation = 3`). `templates/sdl3/.../SDLActivity.java` also
  extends `android.app.Activity` and has the same permission handler, so the
  class-chain and compile results carry over by construction; not run.
- A physical device, a permission dialog answered by a person, and a real
  third-party SDK of either kind.
- A newer `lifecycle-process` than the 2.6.1 Material already resolves; its
  effect on the rest of the lifecycle group was not measured.
