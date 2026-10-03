# An `android` compatibility package for kivyforge: proposal

**Status:** proposed 2026-10-02; revised the same day after review (E8–E10, the scope
changes for `storage` and the splash no-ops, the delivery and conflict policy, the
service naming gap, and stage 0). Nothing here is implemented.

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
  switch very probably quits a kivyforge app today (E10). It is needed by the dark-mode
  part of this package but does not depend on it.
- **Shipping `android` changes Kivy 2.3.1's behaviour.** Kivy 2.3.1 imports it at
  startup (E8), so `kivy_generation = 2` apps take code paths they skip today.

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

- **Class names.** kivyforge generates `org.kivy.android.<Name>` (for example
  `org.kivy.android.ServiceWorker` in `docs/guides/guides/android/services.md`). p4a
  generates `<package>.Service<Name>`, from memory; not read from its template. Ported
  code that names the p4a class fails at `autoclass` before any `start` signature matters.
- **Intent extra.** kivyforge reads `kivyforge_service_argument`; p4a's is
  `pythonServiceArgument` (from memory). Both end up in `PYTHON_SERVICE_ARGUMENT`.
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

### E10. A system theme switch very probably quits the app today

kivyforge declares `android:configChanges="keyboardHidden|orientation|screenSize"`
(`generate/manifest.py:200`). Without `uiMode`, Android recreates the Activity on a
light/dark switch. SDL3's `SDLActivity.onCreate` (lines 354–366) then calls
`nativeAllowRecreateActivity()`, and unless the app has set SDL's allow-recreate hint,
logs "activity finished" and calls `System.exit(0)`. kivyforge does not set the hint
(searched `kivyforge/`). The SDL2 glue was not checked for the same logic.

Separately, SDL3's own `onConfigurationChanged` (lines 663–683) already forwards dark-mode
changes to native code with `onNativeDarkModeChanged`, but Android only calls it when
`uiMode` is declared. So adding `uiMode` fixes a likely crash and turns on SDL3's
theme events, independently of this package. Inferred from source; not observed on a
device.

## What was not verified

- Nothing was run on a device. The plyer failure in E4 is inferred.
- Kivyschool's `android` wheel was not downloaded; "depends on SDL2" is the user's report.
- p4a's generated `android/config.py` was not read. The values proposed below are inferred
  from how the modules use them and must be checked against a real p4a build.
- p4a's `android:configChanges` value. kivyforge's (`keyboardHidden|orientation|screenSize`)
  has no `uiMode`, which dark-mode support needs.
- The theme-switch exit (E10) was not reproduced on a device, and the SDL2 glue was not
  checked for the same recreate logic.
- That Kivy 2.3.1 imports `android` is verified from logs (E8). Which of its imports
  catch a missing *name*, and which other Kivy 2.3.1 modules use the package, were not.
- p4a's generated service class names and intent extra (E6) are from memory.
- Whether pyjnius gets a JNI environment in a service process, which loads no SDL. No
  recorded run of pyjnius inside a kivyforge service was found.
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
6. **Staged path** (below): ship now, then reduce deviations through small upstream PRs.

Revisions after review (2026-10-02):

7. **Keep `storage`, and keep `remove_presplash` and `loadingscreen.hide_loading_screen`
   as no-ops.** Decision 5's principle, that p4a code runs unchanged, applies: dropping a
   module turns a common import into an `ImportError` at load time, while keeping these
   costs about 130 lines and no Java. `remove_presplash` also matters to Kivy 2.3.1 (E8).
8. **A conflicting `android` is an error, not a policy question** (E9): fail `lock` when
   the lock would contain an `android` distribution, and fail `build` when `app_dir`
   contains an `android` module or package.
9. **The `uiMode` manifest change ships first and separately** as stage 0 (E10).

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
| `mixer`, `_android_sound` | Obsolete pygame-style audio; Kivy has audio providers |
| `billing`, `_android_billing` | Obsolete; community uses a third-party library |
| `touch` | Needs p4a's patched `SDLSurface`; kivyforge's glue is stock |
| `display_cutout` | Overlaps `kivy.mobile` geometry and kivyforge's safe-area support; imports Kivy's `Window` |
| `start_service`, `stop_service`, `AndroidService` (from `_android`) | Replaced by the declarative services and the start/stop API below; they call p4a-only Java |
| `vibrate`, accelerometer, wifi scan, `get_dpi`, keyboard helpers, `KEYCODE_*`, `TYPE_*`, `BuildInfo` | Legacy `org.renpy.android.Hardware` paths; plyer has its own facades and `kivy.mobile` covers DPI and keyboard |

If a dropped name turns out to matter, adding it later is additive.

## API details

### Config

`android.config` is required by plyer (E4) and by the vendored modules. Proposed values
(inferred from how the p4a modules use them; verify against a real p4a build before
implementing):

| Name | Value |
|---|---|
| `JAVA_NAMESPACE` | `org.kivy.android` |
| `JNI_NAMESPACE` | `org/kivy/android` |
| `ACTIVITY_CLASS_NAME` | `org.kivy.android.PythonActivity` |
| `ACTIVITY_CLASS_NAMESPACE` | `org/kivy/android/PythonActivity` |
| `SERVICE_CLASS_NAME` | `org.kivy.android.PythonService` |

These are static because kivyforge owns the class names. A later upstream change could
derive them from `_kivy_bootstrap` instead (stage 2).

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
  `remove_presplash`.
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
  `kivy_generation` 2 (SDL2) and 3 (SDL3), whose overrides differ.

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

**Services**

- `PythonService.mService`: a static set when the service starts, so
  `autoclass(SERVICE_CLASS_NAME).mService` works as the guide and plyer expect.
- Static `start(Context ...)` and `stop(Context)` on each generated service class, matching
  the signatures p4a's generated classes expose. From the guide: `start(mActivity, arg)`,
  `start(mActivity, icon, title, text, arg)`, `stop(mActivity)`. **The exact p4a
  signatures were not read from its template**; confirm before implementing. Today
  kivyforge starts a service with an intent carrying `kivyforge_service_argument`, and sets
  the `PYTHON_SERVICE_ARGUMENT` environment variable (the p4a convention) inside the
  service. `start` hides the extra-name difference (E6). For a foreground service it
  must use `startForegroundService`, as p4a's does; the current guide's `startService`
  example does not.
- **Class names (open).** `start`/`stop` only help once code finds the class, and p4a's
  generated names differ from kivyforge's (E6). Either also generate a p4a-named class
  (`<package>.Service<Name>`, once the convention is confirmed) that extends the
  kivyforge one, or document the rename in the migration guide. Generating aliases keeps
  ported code unchanged; documenting it keeps one name per service. Decide when
  implementing.
- **pyjnius in the service process** must be confirmed before promising `mService`: the
  process loads no SDL (E6).

A Java contract test (as already exists for the service classes) should assert these
members, so the Python and Java halves cannot drift.

## Vendoring approach

- **Copy, do not rewrite.** The kept modules are taken verbatim from p4a so behaviour and
  the documented rules (E5) come with them. Provenance: the p4a commit and file list are
  recorded in a `NOTICE` next to the vendored files, with the MIT text.
- **What is new:** `config.py`, `loadingscreen.py` (a no-op; p4a's calls p4a-only Java),
  and an `__init__.py` that replaces what the compiled `_android` gave us (`mActivity`,
  `python_act`, `api_version`, `version_codes`, `open_url`, `AndroidBrowser`,
  `remove_presplash`, the jnius re-exports). The `.pyx` cannot be vendored as is.
- **Vendored files stay byte-identical.** Every deviation lives in a new file, never as an
  edit to a vendored one, so the register below lists files, not patch hunks.
- **Sync check.** Add a script modelled on `scripts/check_sdl_glue_sync.py` that fetches the
  recorded p4a commit and requires each vendored file to match it exactly. Run it in CI.
- **Deviation register** (each entry names its stage-2 removal):

| Deviation | Reason | Removable by |
|---|---|---|
| New `__init__.py` | `import android` must not need the compiled extension | optional `_android` import upstream |
| Static `config.py` | p4a generates it at build time | derive from `_kivy_bootstrap` upstream |
| Lazy or live `mActivity` | p4a's is fixed at import | same upstream change |
| No-op `loadingscreen.py` | p4a's calls `removeLoadingScreen`, which kivyforge's activity does not have | a bootstrap-neutral splash hook upstream |

`permissions.py` line 579 does `from android import Permission`. That resolves against
the package `__init__`, not `permissions.py`. If p4a's compiled module exports
`Permission`, our `__init__` must too, which is an `__init__.py` change and not an edit to
the vendored file. If it does not, the line is a latent p4a bug on whatever path reaches
it, and a good first upstream PR. Check when vendoring.

## Staged path

### Stage 0: the `uiMode` fix (this repo, independent)

1. On a device, toggle the system theme with a current kivyforge build, for both
   `kivy_generation` values, and record what happens (E10 predicts the app exits on
   SDL3).
2. Add `uiMode` to `android:configChanges` in `generate/manifest.py`, with a test.
3. Repeat step 1: the app keeps running. Record both runs in `test-matrix.md` §7, and add
   a `CHANGELOG.md` entry, since every app's behaviour on a theme switch changes.

### Stage 1: ship (this repo)

1. Java contract in the bootstrap (activity hooks, broadcast, dark mode, service
   `mService`/`start`/`stop`), with a contract test.
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
6. `CHANGELOG.md` entry under `[Unreleased]`, including the migration note for apps that
   lock their own `android` (now an error).

### Stage 2: shrink the deviations (upstream, small PRs to p4a)

Each is its own PR; after it lands, delete the matching deviation.

1. `android.config` derived from `_kivy_bootstrap`, which p4a already ships. Small.
2. A pure-Python `mActivity`/`python_act` that asks the bootstrap. Small.
3. Document the Java contract for bootstrap authors (the listener and permission interfaces),
   as #3356 did for `_kivy_bootstrap`.
4. Later and larger: make the compiled import optional and move the plain-Python parts out
   of the `.pyx`, so that `android/__init__.py` is vendorable unchanged. Medium; must not
   break Kivy 2 builds.

Upstream acceptance and timing cannot be predicted. The recipe changed twice this year
(dark mode, 2026-05-29; `_kivy_bootstrap`, 2026-07-26). #3356 went from open to merged
about a day apart, which is one data point.

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
2. Exact p4a service `start`/`stop` signatures, class names and intent extra (E6), and
   plyer inside a service.
3. pyjnius in a service process, which loads no SDL (E6).
4. `permissions.py` line 579.
5. Whether `_ctypes_library_finder.py` (p4a's `ctypes.util.find_library` helper) matters on
   kivyforge. Out of scope here; worth a separate check.
6. Kivy 2.3.1 code paths that turn on once `android` exists (E8). Which ones, and whether
   each works against this package, is only known after the generation-2 gate.
7. The conflict check at `lock` rejects any app that currently locks kivyschool's
   `android`. That is intended, but it is a breaking change for those apps and needs the
   migration note.

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
- p4a recipe: `pythonforandroid/recipes/android/src` (reviewed at `f7798e69`)
- plyer: `plyer/platforms/android/` (default branch)
- [Android-for-Python-Users](https://github.com/Android-for-Python/Android-for-Python-Users)
  (archived 2023-11-13)
- `scripts/check_sdl_glue_sync.py` (the sync pattern to copy)
- `docs/design/platforms/android/05-bootstrap-android.md`,
  `03-artifact-distribution-android.md`
