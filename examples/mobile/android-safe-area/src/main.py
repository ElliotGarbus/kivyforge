"""android-safe-area — make the Android safe area visible (Kivy 3.0 / SDL3).

The app paints the **whole** window red, then paints the region the system
actually leaves to the app on top in dark grey. Whatever red you can still see
is the unsafe region: the status bar, the gesture-navigation pill, and the
display cutout. Content is inset to match, so nothing important lands under
them. Rotate the device — the insets change, and the bands move with it.

Why this example is generation 3
--------------------------------
``kivy.mobile`` does not exist in Kivy 2.3.1, so the Android examples on
``kivy_generation = 2`` (hello-android, qr-maven, pyjnius-deviceinfo) cannot
report a safe area at all. This one pins ``kivy_generation = 3``.

Units, which differ per platform
--------------------------------
``get_safe_area()`` returns **pixels** on Android — already Kivy's layout
coordinate system there — but UIKit **points** on iOS, which have to be scaled
by ``get_scale()`` to reach Kivy pixels. Scaling on Android too would inflate
the padding by the display density (typically 2-3.5x). Kivy's own
``kivy/mobile/__init__.py`` currently documents "layout points" for both,
without the per-platform caveat.

API level
---------
Typed ``WindowInsets`` (``systemBars()`` / ``displayCutout()``) needs API 30+.
Below that Kivy returns all-zero insets, and this app says so rather than
silently showing no red.

Run it on the desktop for a quick smoke-test: ``kivy.mobile`` is mobile-only
and raises ``ImportError`` there, so the insets read as zero and the whole
window is "safe".
"""

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

BASE_PADDING = 12  # dp, applied inside the safe area


def _mobile():
    """The ``kivy.mobile`` module, or ``None`` off-device.

    Mobile-only by design: it raises ``ImportError`` on desktop, which is what
    keeps this example runnable there as a smoke-test.
    """
    if platform not in ("ios", "android"):
        return None
    try:
        import kivy.mobile as m
    except ImportError:
        return None
    return m


def safe_area_insets():
    """Safe-area insets as Kivy pixels: ``[left, top, right, bottom]``.

    Android already reports pixels; iOS reports UIKit points, so only iOS is
    scaled. See the module docstring.
    """
    m = _mobile()
    if m is None:
        return [0, 0, 0, 0]
    insets = m.get_safe_area()
    scale = m.get_scale() if platform == "ios" else 1.0
    return [
        insets["left"] * scale,
        insets["top"] * scale,
        insets["right"] * scale,
        insets["bottom"] * scale,
    ]


KV = """
<SafeAreaRoot>:
    orientation: "vertical"
    spacing: "6dp"

    canvas.before:
        # The whole window, including anything the system overlays.
        Color:
            rgba: 0.55, 0.13, 0.15, 1
        Rectangle:
            pos: self.pos
            size: self.size
        # The region the system leaves to the app: inset by the safe area.
        # Kivy padding is [left, top, right, bottom] and y grows upward, so the
        # bottom inset is padding[3] and the top inset is padding[1].
        Color:
            rgba: 0.08, 0.09, 0.12, 1
        Rectangle:
            pos: self.x + self.padding[0], self.y + self.padding[3]
            size:
                self.width - self.padding[0] - self.padding[2], \
                self.height - self.padding[1] - self.padding[3]

    Label:
        size_hint_y: None
        height: "44dp"
        font_size: "20sp"
        bold: True
        color: 0.5, 0.85, 1.0, 1
        text: "Safe area"

    Label:
        font_size: "15sp"
        halign: "left"
        valign: "top"
        text_size: self.size
        text: root.report_text

    Label:
        size_hint_y: None
        height: "48dp"
        font_size: "12sp"
        color: 0.75, 0.75, 0.75, 1
        halign: "center"
        valign: "middle"
        text_size: self.size
        text: "Red = unsafe. Rotate to watch the insets move."

SafeAreaRoot:
"""


class SafeAreaRoot(BoxLayout):
    report_text = StringProperty("")

    def on_kv_post(self, _base_widget):
        # The safe area is not settled at kv_post and changes with orientation,
        # so refresh on the next frame and on every resize.
        Clock.schedule_once(self._refresh, 0)
        Window.bind(on_resize=self._on_resize)

    def _on_resize(self, *_):
        Clock.schedule_once(self._refresh, 0)

    def _refresh(self, *_):
        left, top, right, bottom = safe_area_insets()
        base = dp(BASE_PADDING)
        self.padding = [base + left, base + top, base + right, base + bottom]
        self.report_text = self._report(left, top, right, bottom)

    def _report(self, left, top, right, bottom):
        m = _mobile()
        if m is None:
            return (
                f"platform: {platform}\n"
                "kivy.mobile: unavailable (desktop)\n\n"
                "Insets read as zero, so the whole window is 'safe' and no red\n"
                "is visible. Build for Android to see real values."
            )
        lines = [
            f"platform: {platform}",
            "",
            f"left:   {left:8.1f} px",
            f"top:    {top:8.1f} px",
            f"right:  {right:8.1f} px",
            f"bottom: {bottom:8.1f} px",
            "",
            f"scale (density): {m.get_scale():.2f}",
            f"dpi:             {m.get_dpi():.0f}",
        ]
        if not any((left, top, right, bottom)):
            lines += [
                "",
                "All zero. Either this device is below API 30 (typed",
                "WindowInsets), or nothing is currently overlapping the app.",
            ]
        return "\n".join(lines)


class SafeAreaApp(App):
    def build(self):
        return Builder.load_string(KV)


# kivyforge imports the entry point (not run as __main__), so start at import.
SafeAreaApp().run()
