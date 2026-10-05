---
title: Add a background service to your Android app
sources:
  - docs/design/platforms/android/01-pyproject-android.md
  - docs/design/platforms/android/05-bootstrap-android.md
  - kivyforge/config/loader.py
  - kivyforge/platforms/android/generate/manifest.py
  - kivyforge/platforms/android/generate/services.py
  - kivyforge/platforms/android/bootstrap/templates/java/org/kivy/android/PythonService.java
---

# Add a background service to your Android app

An Android service runs Python code outside your app's user interface, for
example a long download. You declare services in `pyproject.toml`, and kivyforge
generates a service class and its `<service>` manifest entry for each one. Each
service runs a Python module of your app in its own process.

## Before you begin

- [Configure your Android app](configure.md).
- Decide whether the service is a *foreground service*: long-running work that
  shows the user a notification while it runs.

## Declare a service

1. Write the service's code as a module in your app directory, for example
   `worker.py` next to `main.py`. kivyforge runs it the way
   `python -m worker` would, so `__name__` is `"__main__"`.

2. Add a `[[tool.kivy.android.services]]` entry:

    ```toml
    [[tool.kivy.android.services]]
    name = "Worker"
    entry_point = "worker"
    ```

    `name` must be a Java identifier; kivyforge generates the class
    `org.kivy.android.ServiceWorker` from it. `entry_point` is the Python
    module name, not a file path.

3. For a foreground service, also set a type and the notification it shows:

    ```toml
    [[tool.kivy.android.services]]
    name = "Worker"
    entry_point = "worker"
    foreground = true
    foreground_service_type = "dataSync"
    notification = { channel_id = "sync", channel_name = "Sync", title = "Syncing", text = "Downloading content" }
    ```

    kivyforge adds the `FOREGROUND_SERVICE` permission and the matching typed
    permission, here `FOREGROUND_SERVICE_DATA_SYNC`. It does not add
    `POST_NOTIFICATIONS`; declare it in `[tool.kivy.android.permissions]` if
    your app needs it. For the list of valid types, see the
    [Android overlay reference](../../reference/pyproject/android.md).

    The notification uses the app's launcher icon unless you add
    `icon = "<name>"` to the `notification` table. Android expects a
    monochrome silhouette there; ship it as a drawable, for example
    `drawable/ic_notification.xml`, as described in
    [Add Android resources](configure.md#add-android-resources), and set
    `icon = "ic_notification"`.

4. Re-lock, because `pyproject.toml` changed:

    ```bash
    kivyforge lock -p android
    ```

## Start and stop the service from Python

Each generated service class has static `start` and `stop` methods:

```python
from jnius import autoclass

import android

ServiceWorker = autoclass("org.kivy.android.ServiceWorker")
ServiceWorker.start(android.mActivity, "optional text")
...
ServiceWorker.stop(android.mActivity)
```

- `start` takes a `Context` and an argument string. The service reads the
  argument from the `PYTHON_SERVICE_ARGUMENT` environment variable.
- A foreground service also has a five-argument form,
  `start(context, small_icon_name, title, text, argument)`. A non-empty icon
  name, title or text replaces the notification value from `pyproject.toml`
  for that run. Pass `""` to keep the configured value.
- `stop` ends the service's process, and with it the service's Python code.

Inside the service, `PythonService.mService` is the running service, which is
the `Context` to use for Android calls:

```python
from jnius import autoclass

service = autoclass("org.kivy.android.PythonService").mService
print(service.getPackageName())
```

A service runs in its own process, which has no activity: `android.mActivity`
is `None` there.

pyjnius works in a service on every Android version kivyforge supports. The
service loads the app's SDL library before Python starts, because that is how
pyjnius finds the Java VM. The service creates no window.

### Coming from python-for-android

`start`, `stop` and `mService` match python-for-android's. Only the class name
changes: python-for-android names the class after your app's package, for
example `org.example.myapp.ServiceWorker`. kivyforge's class is always
`org.kivy.android.Service<name>`, with `name` exactly as written in
`pyproject.toml`. Change the name in your `autoclass` call.

`setAutoRestartService` is not provided.

## Verify

Run the smoke test on a device or emulator. When a service is declared, the
smoke test also starts the first declared service and checks that its Python
module imports without error:

```bash
kivyforge run -p android --smoke
```

For a complete app with a background and a foreground service, see
`examples/mobile/android-services`.

## What's next

- [Call Android APIs with pyjnius](pyjnius.md) from your service code.
- [Sign and publish to Google Play](signing.md).
- [Android overlay reference](../../reference/pyproject/android.md).
