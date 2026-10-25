# android-activity-class

A Kivy app whose launcher is its own Java class. `MainActivity` extends
`org.kivy.android.PythonActivity` and logs from `onCreate`, before and after
`super.onCreate()`. That is where an SDK that has to be set up in the
activity's `onCreate` goes:

```toml
[tool.kivy.android]
main_activity = "org.kivyforge.activityclass.MainActivity"

[tool.kivy.android.src]
java = ["android/java"]
```

Beside it, `LifecycleProvider` shows Android's other route, the one a library
takes when it needs every activity's lifecycle without owning the activity: a
`ContentProvider`, which Android creates before the first activity, registering
`Application.ActivityLifecycleCallbacks`. It is declared through
`[tool.kivy.android.manifest].extra_application_xml` and needs no
`main_activity` of its own.

Python sees the subclass where it always sees the activity:
`android.mActivity` is the running `MainActivity`. The bundled `android`
package keeps working unchanged, `android.activity.bind`,
`android.permissions.request_permissions` and
`android.darkmode.set_dark_mode_listener` included.

## Build and run

```bash
kivyforge lock -p android
kivyforge run -p android
```

The app checks each of the above once it starts and prints one line per check:

```bash
adb logcat -s activityclass python.stdout
```

```
I activityclass: LifecycleProvider: registered
I activityclass: MainActivity.onCreate: before super
I activityclass: LifecycleProvider: created org.kivyforge.activityclass.MainActivity
I activityclass: MainActivity.onCreate: after super
I python.stdout: activityclass: running-activity OK org.kivyforge.activityclass.MainActivity
...
I python.stdout: activityclass: ALL_OK
```

and its label reads **All checks passed**.

This is also an **on-device gate example**: CI runs its contract smoke test
(`kivyforge run --smoke --release`) on an API 35 emulator, and the test asserts
the activity it launched is the configured class. So `pylock.android.toml` is
committed rather than ignored. See the [example-repo lock
policy](../../../docs/design/common/03-lockfile-concept.md).
