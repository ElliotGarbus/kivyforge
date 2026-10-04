# android-services

Starts and stops two Android services from a Kivy app. `Worker` is a
background service; `Sync` is a foreground service with a notification. Both
run `src/worker.py`, each in its own process.

The app uses the calls python-for-android documents for its services, with
kivyforge's class names:

```python
from jnius import autoclass
import android

Worker = autoclass("org.kivy.android.ServiceWorker")
Worker.start(android.mActivity, "an argument")
Worker.stop(android.mActivity)
```

Inside the service, the argument is in the `PYTHON_SERVICE_ARGUMENT`
environment variable, and `autoclass("org.kivy.android.PythonService").mService`
is the running service.

## Build and run

```bash
kivyforge lock -p android
kivyforge run -p android
```

Tap **Start services**, then watch what each service logs:

```bash
adb logcat -s python.stdout | grep android-services
```

Each service logs its argument, its own class through `mService`, `None` for
`android.mActivity` (a service process has no activity) and its storage path.
**Stop services** ends both service processes.

pyjnius finds the Java VM in a service process only on Android 12 (API 31) and
later, so on older versions the service runs but its `jnius` calls fail.

The lock is gitignored, per the [example-repo lock
policy](../../../docs/design/common/03-lockfile-concept.md) — only the
on-device gate examples keep a committed lock as validation evidence.
