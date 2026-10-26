"""android-activity-class: the app's own Java activity as the launcher.

``MainActivity`` (``android/java``) extends ``org.kivy.android.PythonActivity``
and is named by ``[tool.kivy.android].main_activity``. Python reaches it the
way it reaches the default launcher: ``android.mActivity`` is the running
activity, whichever class it is.

Each check prints one ``activityclass:`` line; ``activityclass: ALL_OK`` means
every one passed. The listener checks are the point: the bundled ``android``
package builds its Java proxies from the base class's name, so they are what
would break if that name followed the subclass.
"""

import traceback

from jnius import autoclass
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.label import Label

import android
from android.permissions import Permission, request_permissions

EXPECTED = "org.kivyforge.activityclass.MainActivity"

MainActivity = autoclass(EXPECTED)
LifecycleProvider = autoclass("org.kivyforge.activityclass.LifecycleProvider")


def report(name, ok, detail=""):
    print(f"activityclass: {name} {'OK' if ok else 'FAIL'} {detail}".rstrip())
    return ok


def check(name, fn):
    try:
        return report(name, *fn())
    except Exception:
        report(name, False)
        traceback.print_exc()
        return False


def running_class():
    running = android.mActivity.getClass().getName()
    return running == EXPECTED, running


def oncreate_ran():
    return MainActivity.createdBy == EXPECTED, str(MainActivity.createdBy)


def provider_saw_it():
    return LifecycleProvider.lastCreated == EXPECTED, str(LifecycleProvider.lastCreated)


def bind_and_unbind():
    from android import activity

    def on_new_intent(intent):
        pass

    activity.bind(on_new_intent=on_new_intent)
    activity.unbind(on_new_intent=on_new_intent)
    return True, "on_new_intent"


def dark_mode_listener():
    from android.darkmode import set_dark_mode_listener

    set_dark_mode_listener(lambda is_dark: None)
    set_dark_mode_listener(None)
    return True, ""


class ActivityClassApp(App):
    def build(self):
        self.label = Label(text="Checking...", font_size="18sp")
        return self.label

    def on_start(self):
        self.results = [
            check("running-activity", running_class),
            check("subclass-oncreate", oncreate_ran),
            check("provider-callbacks", provider_saw_it),
            check("activity-bind", bind_and_unbind),
            check("darkmode-listener", dark_mode_listener),
        ]
        try:
            # INTERNET is a normal permission, granted at install, so the
            # request returns at once, with no dialog, through the
            # PermissionsCallback proxy.
            request_permissions([Permission.INTERNET], self.on_permissions)
        except Exception:
            self.results.append(report("request-permissions", False))
            traceback.print_exc()
            self.finish()

    def on_permissions(self, permissions, grants):
        self.results.append(report("request-permissions", all(grants), str(grants)))
        Clock.schedule_once(lambda dt: self.finish())

    def finish(self):
        ok = all(self.results)
        print(f"activityclass: {'ALL_OK' if ok else 'SOME_FAILED'}")
        self.label.text = "All checks passed" if ok else "A check failed: see the log"


# Runs the same way with or without an `if __name__ == "__main__":` guard —
# kivyforge runs entry_point as __main__ on every platform.
ActivityClassApp().run()
