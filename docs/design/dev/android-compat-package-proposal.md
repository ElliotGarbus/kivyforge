# An `android` compatibility package for kivyforge: proposal

**Status:** proposed 2026-10-02; revised the same day after review (E8–E10, the scope
changes for `storage` and the splash no-ops, the delivery and conflict policy, the
service naming gap, and stage 0). Revised 2026-10-04 (E11, decisions 10–12, the
vendoring layout and sync tooling, the p4a pin, stage 2) after Kivy 2.3.1's
`TextInput` was found to crash without the package (issue #72).

**Origin:** a user building Android apps with Kivy 3 on kivyforge needs the
python-for-android (p4a) `android` package. The only prebuilt one they found is
kivyschool's wheel, which they report depends on SDL2, so it cannot serve a Kivy 3
(SDL3) app. kivyforge provides no `android` package, and its docs do not say so.

This note records the evidence, the decisions made, the scope, and a staged plan.
It is a proposal and a record of reasoning; the implementation PRs should link back
here.

## Summary

- **Kivy 3 does not need `android`.** The Kivy 3 wheel kivyforge installs never
  imports it (see E1, E2). kivy/kivy#9345, #9346 and #9352 removed that dependency in
  favour of `kivy.mobile` and the `_kivy_bootstrap` contract.
- **The ecosystem still does.** plyer's Android facades, `androidstorage4kivy`, ad
  and billing wrappers, and a great deal of app code import `android` (E4, E5).
- **Decision:** ship a trimmed, pure-Python `android` package **bundled with
  kivyforge**, made by vendoring the p4a modules we keep. Do not publish it to PyPI
  for now. Reduce our deviations from p4a over time by sending small PRs upstream.
- **It needs Java too.** The kept Python modules call methods that exist only in p4a's
  `PythonActivity`. kivyforge's `PythonActivity` and `PythonService` do not have them
  (E6), so the work has a Java half.
- **Ship the `uiMode` manifest fix first, on its own.** Without it, a system theme
  switch quit a kivyforge app (E10, observed on both SDL generations). It is needed by
  the dark-mode part of this package but does not depend on it. Done as stage 0.
- **Shipping `android` changes Kivy 2.3.1's behaviour.** Kivy 2.3.1 imports it at
  startup (E8), so `kivy_generation = 2` apps take code paths they skip today.
- **Kivy 2.3.1 cannot work properly without it** (E11). Tapping a `TextInput`, the
  back key, `App.stop()` and `App.pause()` all reach `android.mActivity` uncaught,
  so today they raise. Generation 2 needs the package for basic behaviour, not only
  for the wider ecosystem.

## Evidence

Everything below was checked on 2026-10-02 unless stated. "Verified" means read from
source or observed; see [What was not verified](#what-was-not-verified).

### E1. Kivy 3 core never imports `android`

Checked at the commit the July Kivy 3 wheel is built from
(`71407bc176eaa93c98b2b3877c4e63c6d4476fc3`, 2026-07-30, pinned in
`kivy-mobile-wheels/recipes/PINNED_REFS.toml`).

- Fetched every `.py`, `.pyx` and `.pxi` file under `kivy/` at that commit: 412 files,
  406 with content, 6 returned empty (probably empty `__init__.py` files).
- Searched all of them for `import android`, `from android ...`,
  `importlib.import_module("android")`, `__import__("android")`, `find_spec("android")`,
  `PythonActivity` and `mActivity`. **No match anywhere** outside comments and the test
  harness. That includes function-level (lazy) imports.
- `kivy/core/window/_window_sdl3.pyx` says in a comment that Kivy "needs neither the p4a
  `android` module" on this path.
- The only file on Kivy's default branch that imports it is an example,
  `examples/android/takepicture/main.py`.

Older Kivy 3 wheels differ. `kivy-android-3.0.0.dev202606221936` carries a June 22
version stamp, before kivy/kivy#9345 (opened 2026-07-18), so it very likely still
imports `android`. Not downloaded or checked.

### E2. A Kivy 3 app locks without it

`examples/mobile/hello-sdl3/pylock.android.toml` (Kivy `3.0.0.dev202607301604`,
pyjnius 1.8.0, `requests` and its dependencies) contains no `android` package. Kivy's
own `pyproject.toml` declares no `android` runtime dependency (searched for the word
only).

### E3. What p4a's `android` package is

Source: `pythonforandroid/recipes/android/src/android` on p4a `master` (latest commit to
the directory at the time of checking: `f7798e69`, 2026-07-26, kivy/python-for-android#3356).

It is **not pure Python.** `android/__init__.py` is one line,
`from android._android import *`, so any `import android` or
`from android.permissions import ...` first loads the compiled `_android` extension.
There are three Cython extensions (`_android`, `_android_billing`, `_android_sound`);
their JNI helpers use `SDL_ANDROID_GetJNIEnv()`, which is why a built wheel is linked to
one SDL generation. `setup.py` selects SDL2 or SDL3 libraries from a `BOOTSTRAP`
environment variable. The recipe also ships `_kivy_bootstrap.py` (kivy/python-for-android#3356)
and relies on an `android.config` module generated at build time.

The Python modules, with line counts:

| Module | Lines | What it does | Java it needs on the activity or service |
|---|---|---|---|
| `permissions.py` | 621 | `Permission` (164 constants), `request_permissions`, `request_permission`, `check_permission` | `addPermissionsCallback`, `requestPermissions`, `requestPermissionsWithRequestCode`, `checkCurrentPermission`, interface `PermissionsCallback` |
| `activity.py` | 214 | `bind`/`unbind` for `on_new_intent` and `on_activity_result`; lifecycle callbacks | `registerNewIntentListener`, `registerActivityResultListener` (and unregister), interfaces `NewIntentListener`, `ActivityResultListener`. Lifecycle callbacks use the standard Android API |
| `runnable.py` | 58 | `run_on_ui_thread` | Standard `runOnUiThread` only |
| `broadcast.py` | 103 | `BroadcastReceiver` | `GenericBroadcastReceiver` class and `GenericBroadcastReceiverCallback` interface |
| `storage.py` | 117 | `app_storage_path`, `primary_external_storage_path`, `secondary_external_storage_path` | None (pyjnius) |
| `darkmode.py` | 57 | dark-mode listener | `setDarkModeListener`, interface `DarkModeListener` |
| `display_cutout.py` | 290 | cutout and system-bar helpers, immersive mode | None; imports Kivy's `Window` |
| `touch.py` | 231 | touch interception | p4a's patched `SDLSurface$OnInterceptTouchListener` (not in stock SDL) |
| `loadingscreen.py` | 9 | `hide_loading_screen` | `removeLoadingScreen` (p4a only) |
| `mixer.py` + `_android_sound` | 324 | SDL2_mixer-style audio | Legacy `org.renpy.android` classes |
| `billing.py` + `_android_billing` | 57 bytes + JNI | legacy billing | Legacy classes |

From the compiled `_android.pyx`: `mActivity`, `python_act`, `api_version`,
`version_codes`, `open_url`/`AndroidBrowser`, `start_service`/`stop_service`/`AndroidService`,
`vibrate`, accelerometer, wifi scan, `get_dpi`, keyboard helpers, `KEYCODE_*`, `TYPE_*`,
`BuildInfo`, `remove_presplash`. `_android.pyx` also does
`from jnius import autoclass, PythonJavaClass, java_method, cast`, which the star-import
re-exports (see [Re-exports](#re-exports)).

### E4. What plyer needs

33 Android facades under `plyer/platforms/android/` (default branch). They use:

| Need | Used by |
|---|---|
| `from android import config` (`config.JAVA_NAMESPACE`) | `__init__.py`, which every facade imports |
| `mActivity` | brightness, filechooser, storagepath |
| `python_act` | notification |
| `android.activity.bind` / `unbind` (`on_activity_result`) | camera, filechooser |
| `android.runnable.run_on_ui_thread` | notification, stt |

`plyer/platforms/android/__init__.py` does `from android import config` inside a
`try`, and on failure falls back to the namespace `org.renpy.android`. kivyforge ships
`org.renpy.android.Hardware` only, so that fallback would look for
`org.renpy.android.PythonActivity`, which does not exist. **So every plyer Android
facade very probably fails at import today** unless an `android.config` is present. This
is an inference from source; it has not been run on a device.

### E5. What the community uses

From the archived guide
[Android-for-Python-Users](https://github.com/Android-for-Python/Android-for-Python-Users)
(archived 2023-11-13, so it predates Android 14/15 and Kivy 3):

- Documents `from android.permissions import request_permissions, check_permission,
  Permission`, `from android import mActivity`, `from android.runnable import
  run_on_ui_thread`, and `from android.config import SERVICE_CLASS_NAME` with
  `PythonService.mService` inside services.
- Calls `BroadcastReceiver` the one notable `android` utility, with WiFi and Bluetooth
  scanner examples.
- Says `app_storage_path()` is "not secure" and `primary_external_storage_path` does not
  work on Android 10 and later; recommends `mActivity.getApplicationContext()` with
  pyjnius instead. `storage` is still kept (decision 7) so imports keep working; the
  docs point new code at pyjnius.
- Says plyer's Camera, Speech to text, Audio and FileChooser do not work on newer Android.
  That lowers their priority but not the need for `config`.
- Documents rules for `request_permissions`: call it after `on_start`, once per time
  step, and keep a reference to the callback object so it is not garbage collected.
- Points to a third-party library for in-app billing, not p4a's `billing`.

Other libraries (default branches, GitHub code search; counts are lower bounds because
search returns at most 30 results):

| Import | Hits | Examples |
|---|---|---|
| `from android import autoclass` | 9 | several apps, PyJniusTester |
| `from android import PythonJavaClass` | 13 | KivAds, kivy-in-app-review, GooglePlayBilling |
| `from android import cast` | 1 | PyJniusTester |
| `from android import java_method` | 0 | none |

`androidstorage4kivy` imports `from android import activity, mActivity, api_version` and
`from android import mActivity, autoclass, cast, api_version`.

### E6. What kivyforge's Java provides today

| Class | Present | Missing for the kept Python modules |
|---|---|---|
| `org.kivy.android.PythonActivity` | `mActivity` (static), `getMainFunction`, `getLibraries`, `onCreate` | Every permission and listener method and interface in E3 |
| `org.kivy.android.PythonService` | generated subclasses per `[[tool.kivy.android.services]]`; sets the `PYTHON_SERVICE_ARGUMENT` environment variable; argument arrives as an intent extra `kivyforge_service_argument` | A static `mService`; static `start(Context, ...)` and `stop(Context)` on the generated classes as the guide uses them |
| `org.renpy.android` | `Hardware` only | Not needed by the kept scope |

SDL already overrides some of the same Activity methods: the SDL3 `SDLActivity` overrides
`onActivityResult` (line 744) and `onRequestPermissionsResult` (line 1962); the SDL2 one
overrides `onRequestPermissionsResult` (line 1792). Neither overrides `onNewIntent`.

Services differ from p4a in more than the missing statics:

- **Class names.** kivyforge generates `org.kivy.android.Service<Name>` (for example
  `org.kivy.android.ServiceWorker` in `docs/guides/guides/android/services.md`). p4a
  generates `<package>.Service<Name>` (read from `Service.tmpl.java` at the pin). Ported
  code that names the p4a class fails at `autoclass` before any `start` signature matters.
- **Intent extra.** kivyforge reads `kivyforge_service_argument`; p4a's is
  `pythonServiceArgument`. Both end up in `PYTHON_SERVICE_ARGUMENT`.
- **Process.** Each service runs in its own `android:process` and loads only `libpython`
  and `libmain`, with no SDL (`PythonService.java`). Java statics are per process, so
  `PythonActivity.mActivity` is always `null` there, not merely stale.

### E7. What the docs say today

- `docs/design/platforms/android/05-bootstrap-android.md` ("Namespace preservation") says
  Kivy, plyer and app code reach Android through `autoclass('org.kivy.android.PythonActivity')`
  and that preserving the namespace means "that entire body of existing Kivy-Android Python
  code works unmodified".
- `03-artifact-distribution-android.md` says using pyjnius or plyer "needs no author-side
  compilation".

Neither mentions the `android` Python package. The first claim is true for code that calls
`autoclass` directly and false for code that does `from android import ...` (E4, E5). The
migration docs and `kivyforge init`'s list of dropped buildozer settings also say nothing
about it. This looks like an unexamined gap, not a deliberate omission. Searched
`docs/` and `.cursor/` only.

### E8. Kivy 2.3.1 imports `android` at startup

`android-loadmodel-findings.md` ("Benign Kivy warnings") records Kivy 2.3.1 on kivyforge
logging:

```
[WARNING] [Base] Unknown <android> provider
[WARNING] [Base] Failed to import "android" module. Could not remove android presplash.
```

So Kivy 2.3.1 tries to import `android` for the presplash and for its `android` input
provider. Today both fail and Kivy skips them. Once the package exists, those imports
succeed and the code behind them runs. Other Kivy 2.3.1 users of `android` are likely
(for example, from memory, the Android clipboard provider uses `android.runnable`); not
checked.

What happens to the presplash call depends on its form, which was not read. If Kivy does
`from android import remove_presplash`, a missing name raises `ImportError`, which the
warning shows is caught, so the only effect is the same warning. If it does
`import android` and then calls `android.remove_presplash()`, a missing name raises
`AttributeError`, which would not be caught and would break startup. Providing the
no-op (see [Scope](#scope)) is correct either way.

### E9. Where the bundled package lands on `sys.path`

`cpp/main.c` sets `module_search_paths` to `stdlib`, then `bootstrap`, then `app`
(line 68), and adds `site-packages` last with `site.addsitedir` (line 112). A package
staged under `bootstrap/` is therefore importable and comes before both the app's code
and every locked distribution. Consequences:

- A locked `android` distribution (for example kivyschool's) never wins. It is silently
  shadowed, but still shipped: its compiled `_android` extension is flattened into
  `jniLibs` and listed in `ext_manifest.json`, and the extension finder, which sits first
  on `sys.meta_path`, would load that SDL2-linked library if anything imported
  `android._android`.
- An `android.py` or `android/` package in the app's own `app_dir` is also shadowed.
- `bootstrap/` is byte-compiled with the rest of the bundle (`stage/bundle.py`, line 130),
  so the package needs no special handling there.

### E10. A system theme switch quit the app (fixed in stage 0)

kivyforge declared `android:configChanges="keyboardHidden|orientation|screenSize"`
(`generate/manifest.py`). Without `uiMode`, Android recreates the Activity on a
light/dark switch. SDL3's `SDLActivity.onCreate` (lines 354–366) then calls
`nativeAllowRecreateActivity()`, and unless the app has set SDL's allow-recreate hint,
logs "activity finished" and calls `System.exit(0)`. kivyforge does not set the hint
(searched `kivyforge/`). The SDL2 glue was not checked for the same logic.

Separately, SDL3's own `onConfigurationChanged` (lines 663–683) already forwards dark-mode
changes to native code with `onNativeDarkModeChanged`, but Android only calls it when
`uiMode` is declared. So adding `uiMode` fixes the exit and turns on SDL3's
theme events, independently of this package.

**Observed 2026-10-04** on a Pixel 8a (Android 17), checklist item
`android-theme-switch`: before the fix, a theme switch relaunched the activity and the
process exited, on both SDL2 (Kivy 2.3.1) and SDL3 (Kivy 3.0). The SDL2 glue therefore
has the same recreate exit. After stage 0, which declares p4a's whole
`configChanges` list (any undeclared change takes the same exit), the process
survives the switch with no relaunch, and SDL3 logs `onConfigurationChanged()`.

### E11. Kivy 2.3.1's uses of `android`, and which of them fail today

Read 2026-10-04 from the Kivy 2.3.1 sources staged in a kivyforge build
(`_python_bundle/site-packages/kivy`) and from `_window_sdl2.pyx` at the `2.3.1` tag.
Pygame-era paths (`window_pygame.py`, `audio_pygame.py`, `support.py`) are left out:
they never run under SDL2.

| Call site | Uses | Caught? | Effect today |
|---|---|---|---|
| `core/window/_window_sdl2.pyx:578`, `show_keyboard` | `from android import mActivity`; `mActivity.changeKeyboard(input_type)` | No | **Observed:** tapping a `TextInput` raises `ModuleNotFoundError` and the app exits (Pixel 8a, Android 17, during #63) |
| `core/window/__init__.py:2041`, `on_keyboard` | `mActivity.moveTaskToBack(True)` on key 27 (back) | No | Back key or gesture raises; inferred |
| `app.py:979`, `App.stop` | `mActivity.finishAndRemoveTask()` | No | `App.stop()` raises; inferred |
| `app.py:1002`, `App.pause` | `mActivity.moveTaskToBack(True)` | No | `App.pause()` raises; inferred |
| `core/window/window_sdl2.py:256` | `mActivity.finishAndRemoveTask()` when `on_pause` returns False | No | Raises; inferred |
| `core/audio/audio_android.py:8` | `from android import api_version` | Provider import | The Android audio provider is skipped |
| `core/clipboard/clipboard_android.py:13` | `android.runnable.run_on_ui_thread`, `python_act` | Provider import | The Android clipboard provider is skipped |
| `base.py:241` | `remove_presplash` | `ImportError` | The warning in E8 |
| `input/providers/androidjoystick.py:17` | `import android`, then `pygame.joystick` | Provider import | Still skipped with the package, since pygame is absent |
| `metrics.py:193` | `org.renpy.android.Hardware.getDPI()` under SDL2 | — | Works today; not an `android` use |

`changeKeyboard` is a Java method that only p4a's SDL2 `PythonActivity` has, and it
needs a field that only p4a's patched SDL2 `SDLActivity` has (`keyboardInputType`, read
by `DummyEdit.onCreateInputConnection`). So the fix has a Java half and touches the
SDL2 glue (decision 11). With a no-op stand-in for `changeKeyboard`, the keyboard opens
and `Window.softinput_mode = "below_target"` keeps the field above it, which confirms
the call is the only blocker on that path.

## What was not verified

- Only the `TextInput` crash (E11) and the theme-switch exit (E10) were run on a device.
  The plyer failure in E4 is inferred.
- Kivyschool's `android` wheel was not downloaded; "depends on SDL2" is the user's report.
- p4a's generated `android/config.py` was not built, but the recipe that writes it
  (`recipes/android/__init__.py`, `prebuild_arch`) was read on 2026-10-04; [Config](#config)
  follows it.
- That Kivy 2.3.1 imports `android` is verified from logs (E8), and its call sites from
  source (E11). Of the uncaught ones, only the `TextInput` crash was observed on a device.
- p4a's generated service classes were read on 2026-10-04 (`Service.tmpl.java` at the
  pin): `<package>.Service<Name>` with the name capitalised, static
  `start(Context, String)`, `start(Context, String, String, String, String)` and
  `stop(Context)`, and the argument passed as the intent extra
  `pythonServiceArgument`.
- pyjnius in a service process was observed on 2026-10-04 on a Pixel 8a, Android 17
  (API 37), in `examples/mobile/android-services`. It gets its JNI environment from
  tier 3 (`JNI_GetCreatedJavaVMs`). On API 24–30 that tier is expected to fail, as the
  pyjnius spike findings record; this was not observed, because no device or emulator
  image at those levels was available.
- The older Kivy 3 wheels were not inspected (E1).
- GitHub code search is incomplete; hit counts are lower bounds.

## Decisions (2026-10-02)

1. **Replace the `android` module** with a compatibility package, rather than pointing
   users at kivyschool's wheel or at plyer upstream.
2. **Bundle it with kivyforge; do not publish to PyPI yet.** The Python modules and the
   Java hooks are a matched pair that only kivyforge's bootstrap defines, so they are
   versioned together, like the SDL glue. It adds no index or lock entry and nothing
   for kivyschool's `android` to conflict with. It is designed so it can be extracted
   later.
3. **Vendor and trim.** Copy the p4a modules we keep verbatim; write only what the
   compiled `_android` provided. Do not compile anything.
4. **Services and dark mode are in scope** (`mService`, `start`, `stop`;
   `android.darkmode`).
5. **Re-export `autoclass`, `cast`, `PythonJavaClass` and `java_method` from `android`**,
   without a deprecation warning, for compatibility with existing code.
6. **Staged path** (below): ship now. Revised 2026-10-04: upstream PRs are optional
   (decision 10).

Revisions after review (2026-10-02):

7. **Keep `storage`, and keep `remove_presplash` and `loadingscreen.hide_loading_screen`
   as no-ops.** Decision 5's principle, that p4a code runs unchanged, applies: dropping a
   module turns a common import into an `ImportError` at load time, while keeping these
   costs about 130 lines and no Java. `remove_presplash` also matters to Kivy 2.3.1 (E8).
8. **A conflicting `android` is an error, not a policy question** (E9): fail `lock` when
   the lock would contain an `android` distribution, and fail `build` when `app_dir`
   contains an `android` module or package.
9. **The `uiMode` manifest change ships first and separately** as stage 0 (E10).

Revisions 2026-10-04:

10. **p4a is the pinned upstream source.** Vendored files are byte-identical to a
    recorded p4a commit, and pulling a later p4a change is a reviewed, one-command
    update (`scripts/sync_p4a.py`, see [Vendoring approach](#vendoring-approach)).
    Upstream PRs are not on the plan; they stay possible where one is useful.
    Deviations are retired once a merged or shared `android` solution exists.
11. **Patch the SDL2 glue for keyboard types.** Apply the `keyboardInputType` hunk of
    p4a's `SDLActivity.java.patch` to the SDL2 glue in kivy-mobile-wheels, then copy it
    here, so the glue sync check still holds. Kivy 2.3.1's `input_type` (`"number"`,
    `"mail"` and so on) then picks the keyboard, as it does on p4a. Only that hunk is
    taken; the rest of p4a's patch serves p4a's own loading screen and startup.
12. **Vendored and kivyforge-owned code live apart.** Vendored Python and Java files sit
    in `bootstrap/templates/p4a/` and are never edited. kivyforge's own files sit in
    `bootstrap/templates/android_pkg/`. Java taken from p4a's `PythonActivity` is pasted
    into ours between `// BEGIN p4a <name>` and `// END p4a <name>` markers, and each
    block is checked against the pinned source.

## Scope

**Keep**

- `android.config`: new, static constants (see [Config](#config)).
- `android.permissions`: `Permission`, `request_permissions`, `request_permission`,
  `check_permission`. Verbatim.
- `android.activity`: `bind`/`unbind` for `on_new_intent` and `on_activity_result`
  verbatim; the lifecycle-callback part is low priority (no custom Java needed).
- `android.runnable`: verbatim.
- `android.broadcast`: `BroadcastReceiver`, verbatim; needs two Java types (below).
- `android.darkmode`: `set_dark_mode_listener` and `DarkModeListener`, verbatim; needs a
  small Java hook and a manifest change (below).
- `android.storage`: verbatim. `primary_external_storage_path` is as limited on Android 10+
  as it is on p4a; the docs point new code at pyjnius (E5).
- `android.loadingscreen`: `hide_loading_screen` as a no-op. kivyforge's splash is the
  system splash, dismissed at first frame.
- Package-level names: `mActivity`, `python_act`, `api_version`, `version_codes`,
  `open_url`/`AndroidBrowser`, `remove_presplash` (a no-op, see E8), and the four jnius
  re-exports.
- Services: `PythonService.mService` and the start/stop API (below).

That is about 1,170 lines of vendored Python (621 + 214 + 58 + 103 + 57 + 117) plus new
`__init__.py`, `config.py` and `loadingscreen.py`, with no compiled code.

**Drop**

| Part | Why |
|---|---|
| `mixer`, `_android_sound` | Compiled, pygame-style audio; kivyforge apps use Kivy's audio providers |
| `billing`, `_android_billing` | Compiled, and needs legacy classes kivyforge does not ship; the community uses a third-party library |
| `touch` | Needs p4a's patched `SDLSurface`; kivyforge's glue is stock |
| `display_cutout` | Overlaps `kivy.mobile` geometry and kivyforge's safe-area support; imports Kivy's `Window` |
| `start_service`, `stop_service`, `AndroidService` (from `_android`) | Replaced by the declarative services and the start/stop API below; they call p4a-only Java |
| `vibrate`, accelerometer, wifi scan, `get_dpi`, keyboard helpers, `KEYCODE_*`, `TYPE_*`, `BuildInfo` | Legacy `org.renpy.android.Hardware` paths; plyer has its own facades and `kivy.mobile` covers DPI and keyboard |

If a dropped name turns out to matter, adding it later is additive.

## API details

### Config

`android.config` is required by plyer (E4) and by the vendored modules. p4a's recipe
writes it at build time with these keys (`recipes/android/__init__.py`, read at the
pin); kivyforge renders the same keys per build:

| Name | Value |
|---|---|
| `BOOTSTRAP` | `"sdl2"` or `"sdl3"`, from `kivy_generation` |
| `IS_SDL2`, `IS_SDL3` | `1`/`0` to match |
| `PY2` | `0` |
| `ANDROID_LIBS_DIR` | `""` (a build-host path in p4a; meaningless on the device) |
| `JAVA_NAMESPACE` | `org.kivy.android` |
| `JNI_NAMESPACE` | `org/kivy/android` |
| `ACTIVITY_CLASS_NAME` | `org.kivy.android.PythonActivity` |
| `ACTIVITY_CLASS_NAMESPACE` | `org/kivy/android/PythonActivity` |
| `SERVICE_CLASS_NAME` | `org.kivy.android.PythonService` |

The class names are constants because kivyforge owns them.

### Re-exports

In p4a, `from android import autoclass` works by accident: `_android.pyx` imports
`autoclass`, `PythonJavaClass`, `java_method` and `cast` from jnius, and the star-import in
`__init__.py` re-exports every public name. Libraries now depend on it (E5).

We keep it, plainly and without a deprecation warning, because the goal is that code
written for p4a runs unchanged, and a warning that only appears on kivyforge cannot reach
the library authors who could act on it. Adding a warning later is easy; removing a
re-export is a breaking change, so keeping it is the safer choice.

Guardrails:

- Define `__all__` explicitly: `autoclass`, `cast`, `PythonJavaClass`, `java_method`,
  `mActivity`, `python_act`, `api_version`, `version_codes`, `open_url`, `AndroidBrowser`,
  `remove_presplash`. `Permission` is not exported: p4a's package does not export it
  either, and the `from android import Permission` in `permissions.py` is inside a
  docstring.
  Without it, `from android import *` would also expose whatever the module happens to
  import.
- A test pins that list so it cannot grow by accident.
- The docs say the re-exports exist for p4a compatibility and that new code should import
  from `jnius`.
- The other accidental exports of the compiled module (`Rect`, `webbrowser`, `KEYCODE_*`,
  `TYPE_*`) are not provided; no use was found. The 30 hits for `from android import *`
  were mostly SL4A, an unrelated library of the same name.

### `mActivity` and `python_act`

p4a computes `mActivity` once at import time. **Proposed: a module-level `__getattr__`
(PEP 562) that asks `_kivy_bootstrap.get_activity()` on each access.** The choice matters
less than it first appears:

- `from android import mActivity`, the common form (E5), binds the value once at import
  whichever way it is provided. Only `android.mActivity` attribute access sees a live
  value.
- In a service it is always `None`, not stale: services run in their own process (E6).
- Rotation and screen-size changes do not recreate the Activity, given the declared
  `configChanges`; with stage 0's `uiMode` neither does a theme switch.

Lazy is never worse than eager and costs nothing, so there is no reason to copy p4a's
import-time lookup. `python_act` stays the class, which is valid in any process.

## Java contract

Additions to kivyforge's bootstrap (`PythonActivity`, `PythonService`, the generated
service classes). The p4a implementations are MIT-licensed and can be taken as the
reference.

**`PythonActivity`**

- Methods: `addPermissionsCallback`, `requestPermissions(String[])`,
  `requestPermissionsWithRequestCode(String[], int)`, `checkCurrentPermission(String)`,
  `registerActivityResultListener`, `unregisterActivityResultListener`,
  `registerNewIntentListener`, `unregisterNewIntentListener`.
- Nested interfaces: `PermissionsCallback`, `ActivityResultListener`, `NewIntentListener`.
- Overrides: `onRequestPermissionsResult`, `onActivityResult`, `onNewIntent`, each
  dispatching to the registered listeners. **`SDLActivity` already overrides the first two**
  (E6), so the overrides must call `super` and request codes must not collide with SDL's
  own. `SDLActivity` does not override `onNewIntent`. The package must work for both
  `kivy_generation` 2 (SDL2) and 3 (SDL3), whose overrides differ. p4a's
  `onRequestPermissionsResult` already calls `super`; its other two do not (see below).

**Broadcast**

- `GenericBroadcastReceiver` and `GenericBroadcastReceiverCallback`, in `org.kivy.android`.

**Dark mode**

- On `PythonActivity`: a nested interface `DarkModeListener` with
  `void onDarkModeChanged(boolean isDarkMode)`, a `setDarkModeListener(DarkModeListener)`
  setter, and an `onConfigurationChanged(Configuration)` override that derives
  `isDarkMode` from `newConfig.uiMode & Configuration.UI_MODE_NIGHT_MASK ==
  Configuration.UI_MODE_NIGHT_YES`, calls the listener if one is set, then calls `super`.
  This is what p4a's SDL3 `PythonActivity` does (read 2026-10-02; added upstream in
  kivy/python-for-android#3306).
- **Manifest change.** Android only calls `onConfigurationChanged` for a theme switch if
  the activity declares `uiMode` in `android:configChanges`. This change is stage 0
  (E10): it is a fix in its own right, and the listener depends on it. The override must
  call `super`, because SDL3's `onConfigurationChanged` forwards the same change to
  native code.

**Keyboard type (generation 2)**

- `PythonActivity.changeKeyboard(int)`, static, as in p4a (E11). On SDL2 it is p4a's
  SDL2 member: it sets `SDLActivity.keyboardInputType` (decision 11) and restarts the
  input connection. On SDL3 it is p4a's SDL3 member, which is commented out to a
  no-op; Kivy 3 never calls it. The render step chooses the member by generation.

**Where kivyforge's members differ from p4a's.** p4a's `onActivityResult` and
`onNewIntent` return early when no listener is registered and never call `super`. SDL3's
`SDLActivity.onActivityResult` delivers its file dialog's result, which reaches SDL on
kivyforge today, so taking p4a's member as is would break that. kivyforge's two overrides
keep p4a's dispatch (including the `onResume()` call before it) and then call `super`.
They are kivyforge-owned blocks and are listed in the deviation register.

**Services**

- `PythonService.mService`: a static set when the service starts, so
  `autoclass(SERVICE_CLASS_NAME).mService` works as the guide and plyer expect.
- Static `start(Context, String)`, `start(Context, String, String, String, String)` and
  `stop(Context)` on each generated service class: the signatures p4a's
  `Service.tmpl.java` generates (read at the pin). The five-argument form carries the
  icon name, notification title and text, and the argument. Today kivyforge starts a
  service with an intent carrying `kivyforge_service_argument`, and sets the
  `PYTHON_SERVICE_ARGUMENT` environment variable (the p4a convention) inside the
  service; `start` hides that extra's name. For a foreground service `start` uses
  `startForegroundService`, which Android 8+ requires for a service that calls
  `startForeground`; p4a's template calls `startService`.
- **Class names: a documented rename, no aliases.** p4a generates
  `<package>.Service<Name>`, with the name passed through Jinja's `capitalize` (first
  letter upper, the rest lower). kivyforge keeps `org.kivy.android.Service<Name>` with
  the name as written. Ported code changes one string, the `autoclass` name; the calls
  after it are unchanged. An alias would be a second generated class per service, in the
  app's package, for a one-line saving. The services guide gives the rename.
- **`stop` ends the service process**, as p4a's `onDestroy` does. The interpreter thread
  cannot be interrupted, so without that `stop` would leave the service's Python
  running. Each service has its own `android:process`, so nothing else dies with it.
- **pyjnius in the service process** works on API 31+ (observed on API 37; see
  [What was not verified](#what-was-not-verified)). The pyjnius wheel `dlopen`s `libSDL2.so` by name
  while looking for SDL's getter. SDL's `JNI_OnLoad` does not run for a library
  loaded that way, so SDL logs `Failed, there is no JavaVM`, and pyjnius falls through
  to tier 3. The log line is benign. Loading SDL with `System.loadLibrary` in the
  service would give API 24–30 a working tier 2; that is a possible follow-up, not part
  of this change.
- `setAutoRestartService` is not provided.

A Java contract test (as already exists for the service classes) should assert these
members, so the Python and Java halves cannot drift.

## Vendoring approach

The goal is that taking a later p4a change is cheap and reviewable, so the same imports
keep working on kivyforge's bootstrap as p4a's code moves.

- **Pin.** p4a's default branch (`develop`) at
  `94ffd5f31d816414ad1fe66c0fe587c61daac757` (2026-10-04). `master` is the May 2026
  release and predates the dark-mode listener.
- **Layout** (decision 12):
  - `kivyforge/platforms/android/bootstrap/templates/p4a/` holds only verbatim p4a
    files: `android/` (`permissions.py`, `activity.py`, `runnable.py`, `broadcast.py`,
    `darkmode.py`, `storage.py`), `java/org/kivy/android/GenericBroadcastReceiver.java`
    and `GenericBroadcastReceiverCallback.java`, p4a's `LICENSE` (MIT), a `NOTICE`, and
    `P4A_VENDOR.toml`.
  - `.../templates/android_pkg/` holds kivyforge's own `__init__.py`, `config.py` and
    `loadingscreen.py`. The `.pyx` cannot be vendored as is; `__init__.py` provides what
    the compiled `_android` gave (`mActivity`, `python_act`, `api_version`,
    `version_codes`, `open_url`, `AndroidBrowser`, `remove_presplash`, the jnius
    re-exports).
  - Java members from p4a's `PythonActivity` are pasted between
    `// BEGIN p4a <name>` and `// END p4a <name>` markers in ours. Each block is a
    byte-identical copy of one member (or a group of adjacent members) of the named p4a
    file. The SDL3 variant of `changeKeyboard` is kept as a fragment file under
    `templates/p4a/java/` and swapped in by the render step.
- **`P4A_VENDOR.toml`** is the single list of what is vendored: the pinned revision, each
  file with its p4a path, and each Java block with its p4a source file.
- **`scripts/sync_p4a.py`:**
  - `check` (CI): fetches the pinned revision and requires every vendored file, block
    and fragment to match byte for byte.
  - `drift`: lists p4a commits since the pin that touch a tracked path, with a unified
    diff for each file or block that would change.
  - `update --rev <sha>`: rewrites the vendored files, blocks and fragments at the new
    revision, updates the pin, and prints the diff for review. kivyforge-owned files and
    blocks are not touched.
- **Deviation register.** Each deviation is retired once a merged or shared `android`
  solution exists:

| Deviation | Reason |
|---|---|
| New `__init__.py` | `import android` must not need the compiled extension |
| Rendered `config.py` | p4a generates it at build time; kivyforge renders it per build |
| Lazy `mActivity` | p4a's is fixed at import |
| No-op `loadingscreen.py` and `remove_presplash` | p4a's call `removeLoadingScreen`; kivyforge's splash is the system splash |
| kivyforge's `onActivityResult` and `onNewIntent` | they also call `super`, so SDL3's file dialog keeps its result (see [Java contract](#java-contract)) |
| Static `start`/`stop` use `startForegroundService` for foreground services | Android 8+ requirement |

## Staged path

### Stage 0: the `uiMode` fix (this repo, independent) — done

1. On a device, toggle the system theme with a current kivyforge build, for both
   `kivy_generation` values, and record what happens. Done: the app exited on both.
2. Declare p4a's `android:configChanges` list, which includes `uiMode`, in
   `generate/manifest.py`, with a test.
3. Repeat step 1: the app keeps running. Both runs are recorded in `test-matrix.md` §7
   under `android-theme-switch`, with a `CHANGELOG.md` entry.

### Stage 1: ship (this repo)

0. The SDL2 keyboard glue (decision 11): kivy-mobile-wheels first, then the copy here.
1. Java contract in the bootstrap (activity hooks, broadcast, dark mode, `changeKeyboard`,
   service `mService`/`start`/`stop`), with a contract test.
2. The vendored, trimmed package, the `__all__` pin test, and the sync script with its CI job.
3. Stage it into the app bundle, and add the conflict checks (below).
4. Docs: a section in the Android guides on the `android` package (what is and is not
   provided, plyer, services); fix the overclaims in `03` and `05`; mention it in the
   migration guide and `kivyforge init`'s dropped-settings list; update the "Benign Kivy
   warnings" section of `android-loadmodel-findings.md`, whose warnings stop (E8).
5. On-device gate, as entries in `docs/design/dev/hardware-checklist.toml` so
   `scripts/hardware_pass.py` records the results in `test-matrix.md` §7: a small app that
   requests a permission, binds `on_activity_result`, runs a `BroadcastReceiver`,
   registers a dark-mode listener and toggles the system theme (the listener fires and the
   Activity is not recreated), starts a service via the p4a-style call, and loads plyer.
   On generation 2 also: a numeric `TextInput` shows the numeric keyboard, the back key
   backgrounds the app, `App.stop()` closes it, and the clipboard and audio providers
   load (E11).
6. `CHANGELOG.md` entry under `[Unreleased]`, including the migration note for apps that
   lock their own `android` (now an error).

### Stage 2: keep in step with p4a

Revised 2026-10-04 (decision 10). There is no planned upstream work. Keeping in step is
`scripts/sync_p4a.py drift` from time to time, and `update` when a p4a change is wanted.
Upstream PRs stay possible where one helps, for example making the compiled `_android`
import optional. The deviation register is retired once a merged or shared `android`
solution exists. The recipe changed twice this year (dark mode, 2026-05-29;
`_kivy_bootstrap`, 2026-07-26), so drift is expected and the tooling is sized for it.

### Stage 3: only if it still hurts

Extract the package for publishing (to PyPI, once the name and ownership are settled), with a
version-range contract check like pyjnius's. As of 2026-10-02 the JSON endpoint on PyPI
returned 404 for `android`, `android-compat`, `kivy-android` and `kivyforge-android`, so
none appeared to be registered. Registering `android` is a decision for the Kivy
maintainers, since kivyschool's index already serves a package of that name.

## Delivery

- Stage the package into the app bundle as `bootstrap/android/`, next to
  `_kivy_bootstrap.py` (`kivyforge/platforms/android/stage/bundle.py`). That directory is
  on `sys.path` ahead of the app and `site-packages` (E9), and is byte-compiled with the
  rest of the bundle.
- **Conflicts are errors** (decision 8). Because the bundled package always wins (E9), a
  second `android` would otherwise ship unused and unannounced.
  - `lock`: if the resolved set contains a distribution that provides a top-level
    `android` package (kivyschool's, for example), fail, naming the distribution and the
    requirement that pulled it in. Check what the distribution *provides*, not only its
    name. This is a configuration problem, so exit 1.
  - `build`: if `app_dir` contains `android.py` or an `android/` package, fail, naming the
    path.
  - Each needs a new `KF-*` code in `kivyforge/report/diagnostics.py`, with tests for the
    human and `--json` output.

## Verification plan

- Hermetic tests: re-export list pinned; `config` constants; `permissions` and `activity`
  logic against a fake jnius; the sync script against a recorded fixture; Java contract
  test for the new members.
- Behaviour tests for the documented `request_permissions` rules.
- Hermetic tests for the conflict checks: a lock containing an `android` provider, and an
  `app_dir` with `android.py` and with `android/`.
- On-device gate (stage 1, step 5) on both `kivy_generation` 2 and 3, since SDL's overrides
  differ. On generation 2 the gate must also cover Kivy 2.3.1's own `android` paths (E8):
  the app starts, the presplash warning is gone, and the clipboard works.
- plyer smoke: import `plyer.platforms.android` and one facade (for example
  `storagepath`, which needs only `mActivity`). Run it once *before* stage 1 too, to turn
  E4's inference into a recorded failure.

## Risks and open questions

1. Request-code collisions with SDL's own permission handling.
2. plyer inside a service. (p4a's service signatures, class names and intent extra were
   read on 2026-10-04; see [Java contract](#java-contract).)
3. pyjnius in a service process on API 24–30. It works on API 31+ (observed on API 37);
   below that its only tier is expected to fail (see [Java contract](#java-contract)).
4. Resolved 2026-10-04: `permissions.py` line 579 is inside a docstring.
5. Whether `_ctypes_library_finder.py` (p4a's `ctypes.util.find_library` helper) matters on
   kivyforge. Out of scope here; worth a separate check.
6. Kivy 2.3.1 code paths that turn on once `android` exists. E11 lists them from source;
   whether each works against this package is only known after the generation-2 gate.
7. The conflict check at `lock` rejects any app that currently locks kivyschool's
   `android`. That is intended, but it is a breaking change for those apps and needs the
   migration note.
8. SDL3's file dialog result. kivyforge's `onActivityResult` calls `super` where p4a's
   does not (deviation register); an SDL3 file dialog should be on the gate.

## Related, not decided here

- **Per-package index pinning.** The same user hit the pip behaviour that makes
  `extra_index_urls` order unreliable: pip picks the highest version across all indexes
  and breaks ties arbitrarily. A uv-style "explicit index for named packages" feature was
  discussed (Android and iOS, pip backend, two-pass resolution with direct URLs). Not
  decided; this package removes the `android` case but not the general one.
- **BOMs and Gradle plugins** ("android: BOMs and Gradle plugins (enables Firebase)",
  ElliotGarbus/kivyforge#57) landed while this note was being written. It appears to cover
  another request from the same user; it was not reviewed for this note.

## References

- kivy/kivy#9345, #9346, #9347, #9352 (`kivy.mobile`, removal of the p4a `android`
  dependency, the `_kivy_bootstrap` contract)
- kivy/python-for-android#3356, #3358 (the `_kivy_bootstrap` implementation and tests)
- kivy/pyjnius#796 (SDL-agnostic Android wheel)
- p4a recipe: `pythonforandroid/recipes/android/src` (reviewed at `f7798e69`; vendored at
  `94ffd5f3`, see [Vendoring approach](#vendoring-approach))
- p4a SDL2 bootstrap: `bootstraps/sdl2/build/src/patches/SDLActivity.java.patch` (the
  `keyboardInputType` hunk, decision 11)
- plyer: `plyer/platforms/android/` (default branch)
- [Android-for-Python-Users](https://github.com/Android-for-Python/Android-for-Python-Users)
  (archived 2023-11-13)
- `scripts/check_sdl_glue_sync.py` (the sync pattern to copy)
- `docs/design/platforms/android/05-bootstrap-android.md`,
  `03-artifact-distribution-android.md`
