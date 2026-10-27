"""swift-bridge: call Swift from Python through an @objc shim and pyobjus.

The shim, ``swift-shims/``, is a local Swift package with three classes:
``SBNotebook`` (an object with state and collections), ``SBWork``/``SBJob``
(async work that Python polls), and ``SBMetronome`` (which calls a delegate
that Python implements). ``demos.py`` calls each one; this file is the UI.

Off iOS the shim does not exist, so the buttons are disabled and the app only
says so. That keeps the UI runnable on a desktop for a quick look.
"""

from __future__ import annotations

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

DARK_BG = (0.08, 0.09, 0.12, 1)
BASE_PADDING = 16  # dp; matches the KV padding
MAX_LOG_LINES = 200

demos = None
if platform == "ios":
    import demos  # noqa: F811 - needs pyobjus and the shim


def safe_area_insets():
    """Safe-area insets in Kivy pixels: ``[left, top, right, bottom]``."""
    if platform not in ("ios", "android"):
        return [0, 0, 0, 0]
    try:
        from kivy.mobile import get_safe_area
    except ImportError:
        return [0, 0, 0, 0]
    insets = get_safe_area()
    return [insets["left"], insets["top"], insets["right"], insets["bottom"]]


KV = """
<DemoButton@Button>:
    font_size: "14sp"

<BridgeRoot>:
    orientation: "vertical"
    padding: "16dp"
    spacing: "10dp"

    Label:
        size_hint_y: None
        height: "48dp"
        font_size: "15sp"
        color: 0.5, 0.85, 1.0, 1
        halign: "center"
        valign: "middle"
        text_size: self.width, None
        text: root.banner

    GridLayout:
        cols: 2
        spacing: "8dp"
        size_hint_y: None
        height: self.minimum_height
        row_default_height: "44dp"
        row_force_default: True
        disabled: not root.native
        DemoButton:
            text: "Notebook"
            on_release: root.run_notebook()
        DemoButton:
            text: "Notification settings"
            on_release: root.run_settings()
        DemoButton:
            text: "Cancel primes" if root.primes_running else "Count primes"
            on_release: root.toggle_primes()
        DemoButton:
            text: "Failing work"
            on_release: root.run_failing()
        DemoButton:
            text: "Stop metronome" if root.metronome_running else "Start metronome"
            on_release: root.toggle_metronome()
        DemoButton:
            text: "Clear log"
            on_release: root.clear_log()

    ScrollView:
        id: scroller
        do_scroll_x: False
        Label:
            id: log
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            font_size: "12sp"
            halign: "left"
            valign: "top"
            text: root.log_text

BridgeRoot:
"""


class BridgeRoot(BoxLayout):
    native = BooleanProperty(demos is not None)
    banner = StringProperty("")
    log_text = StringProperty("")
    primes_running = BooleanProperty(False)
    metronome_running = BooleanProperty(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines: list[str] = []
        self._primes = None
        self._metronome = None
        if self.native:
            self.banner = (
                "SwiftBridge shim loaded.\nTap a button; results appear below."
            )
            self._metronome = demos.MetronomeDemo(self.log)
            Clock.schedule_interval(self._sync_metronome, 0.2)
        else:
            self.banner = "Not on iOS: the Swift shim is only built into the iOS app."

    def on_kv_post(self, _base_widget) -> None:
        Clock.schedule_once(self._refresh_safe_area, 0)
        Window.bind(
            on_resize=lambda *_: Clock.schedule_once(self._refresh_safe_area, 0)
        )

    def _refresh_safe_area(self, *_) -> None:
        base = dp(BASE_PADDING)
        left, top, right, bottom = safe_area_insets()
        self.padding = [base + left, base + top, base + right, base + bottom]

    def log(self, line: str) -> None:
        print(f"SWIFTBRIDGE {line}")  # also in the device console
        self._lines.append(line)
        del self._lines[:-MAX_LOG_LINES]
        self.log_text = "\n".join(self._lines)
        Clock.schedule_once(lambda _dt: setattr(self.ids.scroller, "scroll_y", 0), 0)

    def clear_log(self) -> None:
        self._lines.clear()
        self.log_text = ""

    def run_notebook(self) -> None:
        self.log("--- notebook")
        demos.notebook_demo(self.log)

    def run_settings(self) -> None:
        self.log("--- notification settings")
        demos.notification_settings(self.log)

    def run_failing(self) -> None:
        self.log("--- failing work")
        demos.failing_work(self.log)

    def toggle_primes(self) -> None:
        if self._primes is not None:
            self._primes.cancel()
            return
        self.log(f"--- count primes below {demos.PRIME_LIMIT:,}")
        self.primes_running = True
        self._primes = demos.count_primes(self.log, on_done=self._primes_done)

    def _primes_done(self, _watcher) -> None:
        self._primes = None
        self.primes_running = False

    def toggle_metronome(self) -> None:
        if not self._metronome.running:
            self.log("--- metronome, 6 ticks")
        self._metronome.toggle()
        self._sync_metronome()

    def _sync_metronome(self, *_) -> None:
        self.metronome_running = self._metronome.running


class SwiftBridgeApp(App):
    def build(self) -> BridgeRoot:
        Window.clearcolor = DARK_BG
        return Builder.load_string(KV)


SwiftBridgeApp().run()
