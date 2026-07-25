"""pyjnius device-info demo — read Android APIs from Python.

Featured: pyjnius ``autoclass`` reaching ``android.os.Build``, the battery
level via ``BatteryManager``, and the display metrics — the Android analog of
the iOS ``pyobjus-deviceinfo`` example. All device access is pure Python; the
pyjnius bridge is delivered as a prebuilt Android wheel.
"""

from kivy.app import App
from kivy.lang import Builder
from kivy.utils import platform

KV = """
ScrollView:
    GridLayout:
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


# kivyforge *imports* the entry-point module (it is not run as __main__), so
# the app must start at import time — no `if __name__ == "__main__"` guard.
# (Migrating from buildozer, where main.py runs as __main__? Drop the guard.)
DeviceInfoApp().run()
