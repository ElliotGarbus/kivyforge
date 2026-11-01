"""rubicon-deviceinfo — calling stock iOS classes from Python with Rubicon-ObjC.

Reads device and OS facts from two stock Apple frameworks through
Rubicon-ObjC's ``ObjCClass`` — no Swift, no SPM, no hand-rolled ctypes:

  UIDevice (UIKit)
      name, model, system name/version, battery level + charging state.

  NSProcessInfo (Foundation)
      OS version string, physical memory, CPU core counts, thermal state.

Rubicon-ObjC exposes Objective-C *properties*, class properties included, as
plain attributes: ``UIDevice.currentDevice``, ``device.systemVersion`` and
``proc.processorCount`` are read without a call, and
``device.batteryMonitoringEnabled = True`` sets one. An ``NSString`` result
formats like a ``str``; ``str()`` makes a real one. Scalars (``BOOL``,
``NSInteger``, ``float``, ``unsigned long long``) come back as Python numbers.

On desktop (no UIKit) the app shows a small Python ``platform`` fallback so
the layout can still be exercised. On the iOS Simulator the native path runs —
only ``batteryLevel`` is unavailable there (reported -1).
"""

from __future__ import annotations

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

DARK_BG = (0.08, 0.09, 0.12, 1)
BASE_PADDING = 20  # dp; matches the KV padding, which is the desktop baseline


def safe_area_insets():
    """Device safe-area insets as Kivy pixels: ``[left, top, right, bottom]``.

    Geometry comes from Kivy core's ``kivy.mobile``, which is mobile-only and
    raises ``ImportError`` on desktop — hence the platform guard and the zero
    fallback, so this example is unchanged when run on a desktop for a quick
    smoke-test.

    Both platforms report Kivy layout pixels, so the insets are used
    unscaled. On iOS that needs a Kivy build with kivy/kivy#9441; earlier
    Kivy 3 builds return UIKit points there.
    """
    if platform not in ("ios", "android"):
        return [0, 0, 0, 0]
    try:
        from kivy.mobile import get_safe_area
    except ImportError:
        return [0, 0, 0, 0]
    insets = get_safe_area()
    return [insets["left"], insets["top"], insets["right"], insets["bottom"]]


_BATTERY_STATE = {0: "unknown", 1: "unplugged", 2: "charging", 3: "full"}
_THERMAL_STATE = {0: "nominal", 1: "fair", 2: "serious", 3: "critical"}


def _format_bytes(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{num} B"


def read_device_info() -> tuple[bool, list[tuple[str, str]]]:
    """Return ``(native, rows)`` where rows is a list of (label, value).

    Uses Rubicon-ObjC on iOS; falls back to the Python ``platform`` module
    everywhere else so the UI still renders.
    """
    try:
        from kivy.utils import platform

        if platform != "ios":
            return False, _desktop_rows()

        from rubicon.objc import ObjCClass

        # currentDevice / processInfo are class *properties*: no call.
        device = ObjCClass("UIDevice").currentDevice
        device.batteryMonitoringEnabled = True  # a settable property
        proc = ObjCClass("NSProcessInfo").processInfo

        # Everything below is an Objective-C *property* too. NSString
        # properties need str() to become a Python str; scalars come back
        # directly.
        battery_level = float(device.batteryLevel)
        battery = (
            "n/a (Simulator)"
            if battery_level < 0
            else f"{battery_level * 100:.0f}%  "
            f"({_BATTERY_STATE.get(int(device.batteryState), 'unknown')})"
        )

        rows = [
            ("Name", str(device.name)),
            ("Model", str(device.model)),
            ("System", f"{device.systemName} {device.systemVersion}"),
            ("OS string", str(proc.operatingSystemVersionString)),
            ("Battery", battery),
            ("Memory", _format_bytes(int(proc.physicalMemory))),
            (
                "CPU cores",
                f"{int(proc.activeProcessorCount)} active / "
                f"{int(proc.processorCount)} total",
            ),
            (
                "Thermal",
                _THERMAL_STATE.get(int(proc.thermalState), "unknown"),
            ),
        ]
        return True, rows
    except Exception as exc:  # pragma: no cover — device-only path
        return False, [("Rubicon-ObjC error", str(exc))]


def _desktop_rows() -> list[tuple[str, str]]:
    import os
    import platform as py_platform

    return [
        ("Name", py_platform.node()),
        ("Model", py_platform.machine()),
        ("System", f"{py_platform.system()} {py_platform.release()}"),
        ("OS string", py_platform.platform()),
        ("Battery", "n/a (desktop)"),
        ("Memory", "n/a (desktop)"),
        ("CPU cores", str(os.cpu_count() or "?")),
        ("Thermal", "n/a (desktop)"),
    ]


KV = """
<InfoRow@BoxLayout>:
    label: ""
    value: ""
    size_hint_y: None
    height: "36dp"
    spacing: "12dp"
    Label:
        size_hint_x: None
        width: "120dp"
        font_size: "14sp"
        color: 0.6, 0.6, 0.6, 1
        halign: "right"
        valign: "middle"
        text_size: self.size
        text: root.label
    Label:
        font_size: "14sp"
        halign: "left"
        valign: "middle"
        text_size: self.size
        text: root.value

<DeviceInfoRoot>:
    orientation: "vertical"
    padding: "20dp"
    spacing: "10dp"

    Label:
        size_hint_y: None
        height: "48dp"
        font_size: "16sp"
        color: 0.5, 0.85, 1.0, 1
        halign: "center"
        valign: "middle"
        text_size: self.size
        text: root.backend_text

    BoxLayout:
        id: rows
        orientation: "vertical"
        spacing: "2dp"

    Button:
        size_hint_y: None
        height: "48dp"
        text: "Refresh"
        on_release: root.refresh()

DeviceInfoRoot:
"""


class DeviceInfoRoot(BoxLayout):
    backend_text = StringProperty("")

    def on_kv_post(self, _base_widget) -> None:
        self.refresh()
        # Inset content past the notch / Dynamic Island and home indicator. The
        # safe area is not settled at kv_post and changes with orientation, so
        # refresh on the next frame and on every resize.
        Clock.schedule_once(self._refresh_safe_area, 0)
        Window.bind(on_resize=self._on_resize)

    def _on_resize(self, *_) -> None:
        Clock.schedule_once(self._refresh_safe_area, 0)

    def _refresh_safe_area(self, *_) -> None:
        base = dp(BASE_PADDING)
        left, top, right, bottom = safe_area_insets()
        self.padding = [base + left, base + top, base + right, base + bottom]

    def refresh(self) -> None:
        from kivy.factory import Factory

        native, rows = read_device_info()
        self.backend_text = (
            "Source: Rubicon-ObjC -> UIDevice / NSProcessInfo"
            if native
            else "Source: desktop fallback (not on iOS)"
        )
        container = self.ids.rows
        container.clear_widgets()
        for label, value in rows:
            row = Factory.InfoRow()
            row.label = label
            row.value = value
            container.add_widget(row)


class DeviceInfoApp(App):
    def build(self) -> DeviceInfoRoot:
        Window.clearcolor = DARK_BG
        return Builder.load_string(KV)


DeviceInfoApp().run()
