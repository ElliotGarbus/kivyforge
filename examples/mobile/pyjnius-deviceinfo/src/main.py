"""pyjnius device-info demo — read Android APIs from Python.

Featured: pyjnius ``autoclass`` reaching ``android.os.Build``, the battery
level via ``BatteryManager``, and the display metrics — the Android analog of
the iOS ``pyobjus-deviceinfo`` example. All device access is pure Python; the
pyjnius bridge is delivered as a prebuilt Android wheel.
"""

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.utils import platform

BASE_PADDING = 16  # dp; matches the KV padding, which is the desktop baseline


def safe_area_insets():
    """Device safe-area insets as Kivy pixels: ``[left, top, right, bottom]``.

    Geometry comes from Kivy core's ``kivy.mobile``, which is mobile-only and
    raises ``ImportError`` on desktop — hence the platform guard and the zero
    fallback, so this example is unchanged when run on a desktop for a quick
    smoke-test. ``get_safe_area()`` reports **layout points** on both iOS and
    Android; ``get_scale()`` converts those to Kivy window pixels.

    On Android this keeps the info rows clear of the status bar and the
    gesture-navigation pill.
    """
    if platform not in ("ios", "android"):
        return [0, 0, 0, 0]
    try:
        from kivy.mobile import get_safe_area, get_scale
    except ImportError:
        return [0, 0, 0, 0]
    insets = get_safe_area()  # layout points
    scale = get_scale()  # -> Kivy window pixels
    return [
        insets["left"] * scale,
        insets["top"] * scale,
        insets["right"] * scale,
        insets["bottom"] * scale,
    ]


KV = """
ScrollView:
    GridLayout:
        id: content
        cols: 1
        padding: '16dp'
        spacing: '8dp'
        size_hint_y: None
        height: self.minimum_height
        Label:
            text: 'Android Device Info'
            font_size: '24sp'
            bold: True
            size_hint_y: None
            height: '48dp'
        Label:
            id: info
            text: app.info_text
            halign: 'left'
            valign: 'top'
            font_size: '15sp'
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
"""


def _device_info() -> str:
    if platform != "android":
        return "Not running on Android (device APIs unavailable)."

    from jnius import autoclass

    Build = autoclass("android.os.Build")
    VERSION = autoclass("android.os.Build$VERSION")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Intent = autoclass("android.content.Intent")
    IntentFilter = autoclass("android.content.IntentFilter")
    BatteryManager = autoclass("android.os.BatteryManager")

    activity = PythonActivity.mActivity

    # Battery: read the sticky ACTION_BATTERY_CHANGED broadcast.
    ifilter = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
    battery = activity.registerReceiver(None, ifilter)
    level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
    scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
    pct = int(100 * level / scale) if scale > 0 else -1

    # Display metrics.
    dm = activity.getResources().getDisplayMetrics()

    lines = [
        f"Manufacturer: {Build.MANUFACTURER}",
        f"Model:        {Build.MODEL}",
        f"Device:       {Build.DEVICE}",
        f"Android:      {VERSION.RELEASE} (API {VERSION.SDK_INT})",
        f"ABIs:         {', '.join(Build.SUPPORTED_ABIS)}",
        f"Battery:      {pct}%",
        f"Screen:       {dm.widthPixels}x{dm.heightPixels} @ {dm.densityDpi} dpi",
    ]
    print("DEVICEINFO_OK " + " | ".join(lines), flush=True)
    return "\n".join(lines)


class DeviceInfoApp(App):
    def build(self):
        self.info_text = _device_info()
        return Builder.load_string(KV)

    def on_start(self):
        # The scrolling content carries the padding (the root ScrollView does
        # not), and it is an anonymous KV widget, so this is driven from the
        # App. The safe area is not settled at on_start and changes with
        # orientation, so refresh on the next frame and on every resize.
        Clock.schedule_once(self._refresh_safe_area, 0)
        Window.bind(on_resize=self._on_resize)

    def _on_resize(self, *_):
        Clock.schedule_once(self._refresh_safe_area, 0)

    def _refresh_safe_area(self, *_):
        base = dp(BASE_PADDING)
        left, top, right, bottom = safe_area_insets()
        self.root.ids.content.padding = [
            base + left,
            base + top,
            base + right,
            base + bottom,
        ]


# kivyforge *imports* the entry-point module (it is not run as __main__), so
# the app must start at import time — no `if __name__ == "__main__"` guard.
# (Migrating from buildozer, where main.py runs as __main__? Drop the guard.)
DeviceInfoApp().run()
