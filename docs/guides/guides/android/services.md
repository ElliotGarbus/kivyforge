---
title: Add a background service to your Android app
sources:
  - docs/design/platforms/android/01-pyproject-android.md
  - docs/design/platforms/android/05-bootstrap-android.md
  - kivyforge/config/loader.py
  - kivyforge/platforms/android/generate/manifest.py
  - kivyforge/platforms/android/generate/services.py
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

4. Re-lock, because `pyproject.toml` changed:

    ```bash
    kivyforge lock -p android
    ```

## Start the service from Python

Start the service with an intent from your app's code:

```python
from jnius import autoclass

PythonActivity = autoclass("org.kivy.android.PythonActivity")
Intent = autoclass("android.content.Intent")
ServiceWorker = autoclass("org.kivy.android.ServiceWorker")

activity = PythonActivity.mActivity
intent = Intent(activity, ServiceWorker)
intent.putExtra("kivyforge_service_argument", "optional text")
activity.startService(intent)
```

The service reads the optional argument from the `PYTHON_SERVICE_ARGUMENT`
environment variable.

## Verify

Run the smoke test on a device or emulator. When a service is declared, the
smoke test also starts the first declared service and checks that its Python
module imports without error:

```bash
kivyforge run -p android --smoke
```

## What's next

- [Call Android APIs with pyjnius](pyjnius.md) from your service code.
- [Sign and publish to Google Play](signing.md).
- [Android overlay reference](../../reference/pyproject/android.md).
