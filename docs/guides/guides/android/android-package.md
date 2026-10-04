---
title: Use the android package
sources:
  - docs/design/dev/android-compat-package-proposal.md
  - kivyforge/platforms/android/bootstrap/templates/android_pkg/__init__.py
  - kivyforge/platforms/android/bootstrap/templates/p4a/P4A_VENDOR.toml
  - kivyforge/platforms/android/stage/conflicts.py
  - examples/mobile/android-package/src/main.py
---

# Use the android package

Every kivyforge Android app includes an `android` Python package, the one
python-for-android apps import. Code written for it runs unchanged: requesting
permissions, binding to activity results, receiving broadcasts, following the
system theme. Kivy 2.3.1 also uses it, for the on-screen keyboard, the back key,
`App.stop()`, the clipboard and audio.

You don't add it as a dependency. kivyforge puts it first on `sys.path` in
every build.

## Before you begin

- [Configure your Android app](configure.md).
- Add `pyjnius` to your dependencies. The package calls Android through
  pyjnius, so `import android` fails without it. See
  [Call Android APIs with pyjnius](pyjnius.md).

## What is included

These modules are taken unchanged from python-for-android, at the revision
recorded in kivyforge's `P4A_VENDOR.toml`:

| Module | What it gives you |
|---|---|
| `android.permissions` | `Permission`, `request_permissions`, `request_permission`, `check_permission` |
| `android.activity` | `bind` and `unbind` for `on_new_intent` and `on_activity_result`, and activity lifecycle callbacks |
| `android.runnable` | `run_on_ui_thread` |
| `android.broadcast` | `BroadcastReceiver` |
| `android.darkmode` | `set_dark_mode_listener` |
| `android.storage` | `app_storage_path`, `primary_external_storage_path`, `secondary_external_storage_path` |

The package itself provides `mActivity` (the running activity), `python_act`
(its class), `api_version`, `version_codes`, `open_url` and `AndroidBrowser`.
`android.config` has python-for-android's constants, such as `BOOTSTRAP`
(`"sdl2"` or `"sdl3"`) and `ACTIVITY_CLASS_NAME`.

`from android import autoclass` (and `cast`, `PythonJavaClass`,
`java_method`) also works, because existing code relies on it. In new code,
import those from `jnius`.

## Use it

For example, to ask for a permission and act on the answer:

```python
from android.permissions import Permission, request_permissions


def on_result(permissions, grants):
    print(dict(zip(permissions, grants)))


request_permissions([Permission.POST_NOTIFICATIONS], on_result)
```

Declare every permission you request under
`[tool.kivy.android.permissions]`, or Android denies it without asking.

To follow the system's light and dark theme:

```python
from android.darkmode import set_dark_mode_listener

set_dark_mode_listener(lambda dark: print("dark mode:", dark))
```

## How it differs from python-for-android

- `android.mActivity` is looked up each time you read it. `from android import
  mActivity` still binds it once, as before.
- `remove_presplash()` and `android.loadingscreen.hide_loading_screen()` do
  nothing: the app's splash is Android's system splash screen, which closes on
  the first frame.
- In a service, `android.mActivity` is `None`, because a service runs in its
  own process. Use `PythonService.mService`; see
  [Add a background service](services.md).
- Not included: `android.mixer`, `android.billing`, `android.touch`,
  `android.display_cutout`, and the compiled module's `start_service`,
  `stop_service`, `AndroidService`, `vibrate` and hardware helpers. Use
  [services](services.md), Kivy's audio, [plyer](https://github.com/kivy/plyer)
  or pyjnius instead.

## Don't ship your own android package

Because kivyforge's package always comes first, a second one would be
bundled and never imported. kivyforge stops instead:

- `kivyforge lock` fails with `KF-ANDROID-DEPENDENCY-CONFLICT` when your
  dependencies include a distribution named `android`. Remove it from your
  dependencies, or from the package that pulls it in.
- `kivyforge build` fails with `KF-ANDROID-APP-CONFLICT` when your `app_dir`
  has an `android.py` or an `android/` package, and with
  `KF-ANDROID-DEPENDENCY-CONFLICT` when an installed wheel provides a top-level
  `android`. Rename your module, or drop the dependency.

Both exit with status 1, a configuration error.

## Verify

The `android-package` example (Kivy 2.3.1) and `android-package-sdl3` (Kivy
3.0) use each module and log one `android-package:` line per check:

```bash
cd examples/mobile/android-package
kivyforge lock -p android
kivyforge run -p android
```

## What's next

- [Add a background service](services.md).
- [Call Android APIs with pyjnius](pyjnius.md).
