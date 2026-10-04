"""android-services: start and stop two services from a Kivy app.

The calls are the ones python-for-android documents for its services, with
kivyforge's class names: ``autoclass("org.kivy.android.Service<Name>")``, then
the static ``start`` and ``stop``. ``Sync`` is a foreground service and is
started with the five-argument ``start``, whose title and text replace the
notification configured in pyproject.toml.
"""

from jnius import autoclass
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label

import android
from android.permissions import Permission, request_permissions

Worker = autoclass("org.kivy.android.ServiceWorker")
Sync = autoclass("org.kivy.android.ServiceSync")


class ServicesApp(App):
    def build(self):
        root = BoxLayout(orientation="vertical", padding="24dp", spacing="12dp")
        self.status = Label(text="Services stopped", font_size="18sp")
        root.add_widget(self.status)
        root.add_widget(Button(text="Start services", on_release=self.start))
        root.add_widget(Button(text="Stop services", on_release=self.stop_services))
        return root

    def on_start(self):
        # Android 13+ hides a foreground service's notification without it.
        if android.api_version >= 33:
            request_permissions([Permission.POST_NOTIFICATIONS])

    def start(self, *_):
        Worker.start(android.mActivity, "from the app")
        Sync.start(
            android.mActivity, "", "Syncing", "Started from main.py", "from the app"
        )
        self.status.text = "Services started"

    def stop_services(self, *_):
        Worker.stop(android.mActivity)
        Sync.stop(android.mActivity)
        self.status.text = "Services stopped"


# Runs the same way with or without an `if __name__ == "__main__":` guard —
# kivyforge runs entry_point as __main__ on every platform.
ServicesApp().run()
