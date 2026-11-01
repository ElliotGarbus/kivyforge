"""rubicon-ball — an interactive kivyforge 3.0 example.

Demonstrates calling native iOS APIs from Python with Rubicon-ObjC.

Two native APIs are exercised:

  CMMotionManager (CoreMotion)
      Accelerometer data to steer the ball. ``acceleration`` returns a C
      struct of three doubles, ``CMAcceleration``; Rubicon-ObjC returns struct
      results as ``ctypes`` structures, and registering our own structure for
      its type encoding gives the fields their names.

  UIScreen (UIKit)
      Read and write screen brightness from a slider, as a plain property.

On the Simulator (or any environment where CoreMotion is unavailable) the app
falls back to touch/drag steering so the layout can still be exercised.
"""

from __future__ import annotations

import ctypes
from random import random

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.utils import platform

DARK_BG = (0.08, 0.09, 0.12, 1)
BASE_PADDING = 16  # dp; matches the KV padding, which is the desktop baseline


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


KV = """
<BallWidget>:
    size_hint: None, None
    size: "64dp", "64dp"
    canvas:
        Color:
            hsv: root.hue, 0.9, 1.0
        Ellipse:
            pos: self.pos
            size: self.size

<BallRoot>:
    orientation: "vertical"
    padding: "16dp"
    spacing: "8dp"

    # Mode / status banner
    Label:
        size_hint_y: None
        height: "36dp"
        font_size: "14sp"
        color: 0.5, 0.85, 1.0, 1
        text: root.status_text

    # Brightness row — hidden when native APIs unavailable
    BoxLayout:
        size_hint_y: None
        height: "44dp"
        spacing: "12dp"
        opacity: 1 if root.has_native else 0
        disabled: not root.has_native
        Label:
            size_hint_x: None
            width: "110dp"
            font_size: "13sp"
            halign: "right"
            valign: "middle"
            text_size: self.size
            text: "Brightness"
        Slider:
            id: bright_slider
            min: 0.1
            max: 1.0
            value: 0.75
            on_value: root.set_brightness(self.value)

    # Play field — also handles fallback touch steering
    Widget:
        id: field
        on_touch_move: root.on_field_touch(args[1])
        BallWidget:
            id: ball
            hue: root.ball_hue
            center: field.center

    # Bounce counter
    Label:
        size_hint_y: None
        height: "28dp"
        font_size: "13sp"
        color: 0.6, 0.6, 0.6, 1
        text: f"Bounces: {root.bounces}"

BallRoot:
"""


class BallWidget(Widget):
    hue = NumericProperty(0.55)


class CMAcceleration(ctypes.Structure):
    """Mirror of CoreMotion's ``CMAcceleration`` struct (three doubles)."""

    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("z", ctypes.c_double),
    ]


class _Accelerometer:
    """CMMotionManager through Rubicon-ObjC."""

    def __init__(self) -> None:
        from rubicon.objc import ObjCClass
        from rubicon.objc.types import register_encoding

        # CMAcceleration is an anonymous C struct, so its type encoding is
        # "{?=ddd}". Without a registered type, Rubicon-ObjC builds one with
        # fields named field_0, field_1, field_2; this one names them x, y, z.
        # CMRotationRate shares the encoding and the layout.
        register_encoding(b"{?=ddd}", CMAcceleration)

        self._mm = ObjCClass("CMMotionManager").alloc().init()
        self._available = bool(self._mm.isAccelerometerAvailable)
        if self._available:
            self._mm.startAccelerometerUpdates()

    @property
    def available(self) -> bool:
        return self._available

    @property
    def values(self) -> tuple[float, float]:
        """Return ``(x, y)`` tilt in *g* (positive x = tilt right)."""
        if not self._available:
            return 0.0, 0.0
        data = self._mm.accelerometerData
        if data is None:
            return 0.0, 0.0
        acc = data.acceleration
        return float(acc.x), float(acc.y)

    def stop(self) -> None:
        if self._available:
            self._mm.stopAccelerometerUpdates()


class _Screen:
    """UIScreen.mainScreen brightness, read and written as a property."""

    def __init__(self) -> None:
        from rubicon.objc import ObjCClass

        self._screen = ObjCClass("UIScreen").mainScreen

    @property
    def brightness(self) -> float:
        return float(self._screen.brightness)

    @brightness.setter
    def brightness(self, value: float) -> None:
        self._screen.brightness = float(value)


class BallRoot(BoxLayout):
    ball_hue = NumericProperty(0.55)
    bounces = NumericProperty(0)
    has_native = NumericProperty(0)  # bool cast to number for KV opacity
    status_text = StringProperty("Initialising…")

    # Physics constants
    _ACCEL_SCALE = 350.0  # px/s² per g of tilt
    _MAX_SPEED = 700.0  # px/s

    # Initial velocity so the ball moves immediately at startup
    _vx: float = 220.0
    _vy: float = 160.0

    _accel: _Accelerometer | None = None
    _screen: _Screen | None = None

    def on_kv_post(self, _base_widget) -> None:
        try:
            accel = _Accelerometer() if platform == "ios" else None
            if accel is not None and accel.available:
                self._accel = accel
                self._screen = _Screen()
                self.has_native = 1
                self.ids.bright_slider.value = self._screen.brightness
                self.status_text = "Tilt to steer · slide to adjust brightness"
            else:
                self.status_text = "Accelerometer unavailable — drag to steer"
        except Exception as exc:  # pragma: no cover — device-only path
            self.status_text = f"Native init error: {exc}"

        # Inset the play field past the notch / Dynamic Island and home
        # indicator — the ball bounces off the padded edge, so it stays inside
        # the region the system actually leaves to the app. The safe area is
        # not settled at kv_post and changes with orientation, so refresh on
        # the next frame and on every resize.
        Clock.schedule_once(self._refresh_safe_area, 0)
        Window.bind(on_resize=self._on_resize)

        Clock.schedule_interval(self._update, 1.0 / 60.0)

    def _on_resize(self, *_) -> None:
        Clock.schedule_once(self._refresh_safe_area, 0)

    def _refresh_safe_area(self, *_) -> None:
        base = dp(BASE_PADDING)
        left, top, right, bottom = safe_area_insets()
        self.padding = [base + left, base + top, base + right, base + bottom]

    def __del__(self) -> None:
        if self._accel:
            self._accel.stop()

    # ------------------------------------------------------------------ #
    # Native API calls                                                     #
    # ------------------------------------------------------------------ #

    def set_brightness(self, value: float) -> None:
        """Write screen brightness via UIScreen (functional on iOS 16+)."""
        if self._screen is not None:
            self._screen.brightness = value

    # ------------------------------------------------------------------ #
    # Touch fallback (when accelerometer is absent)                        #
    # ------------------------------------------------------------------ #

    def on_field_touch(self, touch) -> None:
        """Give the ball a velocity impulse toward the touch point."""
        if self._accel:
            return
        ball = self.ids.ball
        dx = touch.x - ball.center_x
        dy = touch.y - ball.center_y
        self._vx = dx * 0.5
        self._vy = dy * 0.5

    # ------------------------------------------------------------------ #
    # Game loop                                                            #
    # ------------------------------------------------------------------ #

    def _update(self, dt: float) -> None:
        if self._accel:
            ax, ay = self._accel.values
            # Accumulate velocity from tilt (acceleration model).
            # Velocity is NOT overwritten each frame — this is what lets
            # bounces work: a reversed component stays reversed until tilt
            # in the opposite direction overcomes it.
            self._vx += ax * self._ACCEL_SCALE * dt
            self._vy += ay * self._ACCEL_SCALE * dt
            # Clamp to max speed while preserving direction.
            spd = (self._vx**2 + self._vy**2) ** 0.5
            if spd > self._MAX_SPEED:
                f = self._MAX_SPEED / spd
                self._vx *= f
                self._vy *= f

        field = self.ids.field
        ball = self.ids.ball

        new_x = ball.x + self._vx * dt
        new_y = ball.y + self._vy * dt

        bounced = False

        if new_x < field.x:
            new_x = field.x
            self._vx = abs(self._vx)
            bounced = True
        elif new_x + ball.width > field.right:
            new_x = field.right - ball.width
            self._vx = -abs(self._vx)
            bounced = True

        if new_y < field.y:
            new_y = field.y
            self._vy = abs(self._vy)
            bounced = True
        elif new_y + ball.height > field.top:
            new_y = field.top - ball.height
            self._vy = -abs(self._vy)
            bounced = True

        ball.pos = (new_x, new_y)

        if bounced:
            self.bounces += 1
            self.ball_hue = random()


class BallApp(App):
    def build(self) -> BallRoot:
        Window.clearcolor = DARK_BG
        return Builder.load_string(KV)


BallApp().run()
