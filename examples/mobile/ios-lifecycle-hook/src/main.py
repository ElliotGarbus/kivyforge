"""ios-lifecycle-hook — app-delegate code for a kivyforge iOS app.

A local Swift package (``lifecycle-hook/``, Objective-C) runs before Python
and installs the app-delegate methods SDL does not provide. ``lifecycle.py``
turns what it records into Kivy events. This app shows every event as it
arrives, with buttons for the parts that need a request from the app:

  * Register for push: asks for notification permission and an APNs device
    token.
  * Test notification: posts a local notification in 5 seconds. Press Home,
    tap it, and a ``notification_response`` arrives.
  * Refresh task: asks iOS to run the declared BGTask some time later. The
    Simulator refuses this; it needs a device.

Open ``kflifecycle://hello`` (for example with ``xcrun simctl openurl booted
kflifecycle://hello``) to see a ``url`` event, with ``cold`` true when the URL
launched the app.
"""

from __future__ import annotations

import json

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform
from lifecycle import Lifecycle

DARK_BG = (0.08, 0.09, 0.12, 1)
# Listed in BGTaskSchedulerPermittedIdentifiers in pyproject.toml.
REFRESH_TASK = "org.kivy.ios-lifecycle-hook.refresh"
BASE_PADDING = 16  # dp; matches the KV padding, which is the desktop baseline


def safe_area_insets():
    """Device safe-area insets as Kivy pixels: ``[left, top, right, bottom]``."""
    if platform not in ("ios", "android"):
        return [0, 0, 0, 0]
    try:
        from kivy.mobile import get_safe_area
    except ImportError:
        return [0, 0, 0, 0]
    insets = get_safe_area()
    return [insets["left"], insets["top"], insets["right"], insets["bottom"]]


KV = """
<LifecycleRoot>:
    orientation: "vertical"
    padding: "16dp"
    spacing: "10dp"

    Label:
        size_hint_y: None
        height: "40dp"
        font_size: "14sp"
        color: 0.5, 0.85, 1.0, 1
        text_size: self.width, None
        halign: "center"
        text: root.status_text

    BoxLayout:
        size_hint_y: None
        height: "48dp"
        spacing: "8dp"
        Button:
            text: "Register for push"
            on_release: root.register_for_push()
        Button:
            text: "Test notification"
            on_release: root.test_notification()
        Button:
            text: "Refresh task"
            on_release: root.submit_refresh_task()

    ScrollView:
        Label:
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            font_size: "12sp"
            halign: "left"
            valign: "top"
            text: root.log_text

LifecycleRoot:
"""


class LifecycleRoot(BoxLayout):
    status_text = StringProperty("")
    log_text = StringProperty("")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lifecycle = Lifecycle()
        self.status_text = f"LifecycleHook: {self.lifecycle.status}"
        for name in Lifecycle.__events__:
            self.lifecycle.bind(**{name: self._make_logger(name)})

    def _make_logger(self, name):
        def log(_dispatcher, *args) -> None:
            shown = ", ".join(json.dumps(arg) for arg in args)
            self.log_text = f"{name}({shown})\n{self.log_text}"

        return log

    def register_for_push(self) -> None:
        self.lifecycle.register_for_push()

    def test_notification(self) -> None:
        self.lifecycle.schedule_test_notification(5)
        self.log_text = (
            "test notification in 5 s; press Home and tap it\n" + self.log_text
        )

    def submit_refresh_task(self) -> None:
        error = self.lifecycle.submit_refresh_task(REFRESH_TASK)
        result = error or "submitted; iOS decides when it runs"
        self.log_text = f"submit_refresh_task: {result}\n{self.log_text}"

    def on_kv_post(self, _base_widget) -> None:
        # The safe area is not settled at kv_post and changes with
        # orientation, so refresh on the next frame and on every resize.
        Clock.schedule_once(self._refresh_safe_area, 0)
        Window.bind(
            on_resize=lambda *_: Clock.schedule_once(self._refresh_safe_area, 0)
        )

    def _refresh_safe_area(self, *_) -> None:
        base = dp(BASE_PADDING)
        left, top, right, bottom = safe_area_insets()
        self.padding = [base + left, base + top, base + right, base + bottom]


class LifecycleHookApp(App):
    title = "Lifecycle Hook"

    def build(self):
        Window.clearcolor = DARK_BG
        return Builder.load_string(KV)


LifecycleHookApp().run()
