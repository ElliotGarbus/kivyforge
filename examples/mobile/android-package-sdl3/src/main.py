"""android-package: the bundled ``android`` package, checked on a device.

kivyforge bundles an ``android`` package so code written for
python-for-android's imports runs unchanged. This app uses each part of it and
logs one ``android-package:`` line per check, so ``adb logcat -s
python.stdout`` shows what worked. The checks that need nobody run at start;
the buttons cover the ones that need a person: a permission dialog, an
activity result, the numeric keyboard and ``App.stop()``.

The same file is the app in ``android-package-sdl3``, which builds it on Kivy
3.0 (SDL3); a test keeps the two copies identical.
"""

import os
import traceback

# Kivy loads its Android audio provider only when asked for it, and that
# provider imports `api_version` from this package.
os.environ.setdefault("KIVY_AUDIO", "android,sdl3,sdl2")

from kivy.app import App  # noqa: E402
from kivy.clock import mainthread  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.button import Button  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.textinput import TextInput  # noqa: E402

import android  # noqa: E402

PICK_REQUEST = 4242


class PackageApp(App):
    def build(self):
        root = BoxLayout(orientation="vertical", padding="16dp", spacing="8dp")
        self.status = Label(text="", font_size="14sp", halign="left", valign="top")
        self.status.bind(size=self.status.setter("text_size"))
        root.add_widget(self.status)
        root.add_widget(
            TextInput(
                hint_text="Numeric keyboard",
                input_type="number",
                multiline=False,
                size_hint_y=None,
                height="48dp",
            )
        )
        for text, action in (
            ("Request permission", self.request_permission),
            ("Pick a file (activity result)", self.pick_file),
            ("App.stop()", lambda *_: self.stop()),
        ):
            root.add_widget(
                Button(text=text, on_release=action, size_hint_y=None, height="48dp")
            )
        return root

    def on_start(self):
        for check in (
            self.check_package,
            self.check_storage,
            self.check_broadcast,
            self.check_dark_mode,
            self.check_activity_result,
            self.check_kivy_providers,
            self.check_plyer,
        ):
            try:
                check()
            except Exception:
                traceback.print_exc()
                self.log(f"{check.__name__} FAILED")

    @mainthread
    def log(self, message):
        print(f"android-package: {message}")
        self.status.text += message + "\n"

    def check_package(self):
        from android.config import BOOTSTRAP

        self.log(f"bootstrap {BOOTSTRAP}, api_version {android.api_version}")
        self.log(f"mActivity {android.mActivity.getClass().getName()}")

    def check_storage(self):
        from android.storage import app_storage_path, primary_external_storage_path

        self.log(f"app_storage_path {app_storage_path()}")
        self.log(f"primary_external_storage_path {primary_external_storage_path()}")

    def check_broadcast(self):
        from android.broadcast import BroadcastReceiver

        def on_battery(context, intent):
            level = intent.getIntExtra("level", -1)
            self.log(f"broadcast battery level {level}")
            self.receiver.stop()

        # BATTERY_CHANGED is sticky: the receiver gets the last one at once.
        self.receiver = BroadcastReceiver(on_battery, actions=["battery_changed"])
        self.receiver.start()

    def check_dark_mode(self):
        from android.darkmode import set_dark_mode_listener

        # pyjnius passes the Java boolean through as 1 or 0.
        set_dark_mode_listener(
            lambda dark: self.log(f"dark mode changed: {bool(dark)}")
        )
        self.log("dark mode listener set")

    def check_activity_result(self):
        from android.activity import bind

        bind(on_activity_result=self.on_activity_result)
        self.log("on_activity_result bound")

    def check_kivy_providers(self):
        from kivy.core.clipboard import Clipboard

        Clipboard.copy("kivyforge")
        self.log(
            f"clipboard {type(Clipboard).__name__} round trip "
            f"{Clipboard.paste() == 'kivyforge'}"
        )
        try:
            from kivy.core.audio import SoundLoader
        except ImportError:
            self.log("audio: this Kivy has no kivy.core.audio")
            return
        providers = [cls.__name__ for cls in SoundLoader._classes]
        self.log(f"audio providers {providers}")

    def check_plyer(self):
        from plyer import storagepath

        self.log(f"plyer application dir {storagepath.get_application_dir()}")

    def request_permission(self, *_):
        from android.permissions import Permission, request_permissions

        def on_result(permissions, grants):
            self.log(f"permission result {list(permissions)} {list(grants)}")

        request_permissions([Permission.POST_NOTIFICATIONS], on_result)

    def pick_file(self, *_):
        from jnius import autoclass

        Intent = autoclass("android.content.Intent")
        intent = Intent(Intent.ACTION_GET_CONTENT)
        intent.setType("*/*")
        android.mActivity.startActivityForResult(intent, PICK_REQUEST)

    def on_activity_result(self, request_code, result_code, intent):
        if request_code == PICK_REQUEST:
            self.log(f"activity result code {result_code}")


# Runs the same way with or without an `if __name__ == "__main__":` guard —
# kivyforge runs entry_point as __main__ on every platform.
PackageApp().run()
