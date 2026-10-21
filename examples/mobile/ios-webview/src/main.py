"""ios-webview — a spike for the web view recipe in the ios-module guide.

kivyforge does not ship the kivy-ios ``ios`` module
(docs/design/dev/ios-module-proposal.md). The one function of that module
with no drop-in replacement is ``ios.IOSWebView().open(url, x, y, w, h)``,
which put a ``WKWebView`` over the Kivy window. The migration guide will
carry a short recipe for it instead. This app exists to run that recipe on
the simulator before the guide claims it works, and to settle two questions
the guide depends on:

1. Can pyobjus pass a ``CGRect`` to ``initWithFrame:``? Structs of doubles
   are pyobjus's known weak spot (kivy/pyobjus#148, for *returned* structs;
   its conversion code says arguments are fine). The "Open (pyobjus)" button
   tries it. "Open (ctypes)" does the same through the Objective-C runtime
   with ``ctypes``, the fallback the guide would carry if pyobjus cannot.

2. Which unit is which. Kivy 3's SDL3 window is created high-pixel-density
   and lays out in **pixels**; ``kivy.mobile`` reports UIKit **points**; UIKit
   frames are points with a top-left origin. The app logs every number it
   uses so the findings can state the conversion with evidence, and logs the
   keyboard height from ``Window`` and from ``kivy.mobile`` side by side when
   the URL field is focused.

What the simulator run (iOS 27.0, pyobjus 1.2.4) settled:

- pyobjus's ``load_framework(INCLUDE.WebKit)`` does nothing on iOS, so
  ``autoclass("WKWebView")`` fails. ``load_webkit()`` uses ``dlopen`` instead.
- pyobjus corrupts the heap when it passes a ``CGRect`` by value
  (kivy/pyobjus#90). Both variants set the frame with ctypes; the pyobjus
  variant hands ctypes its object via ``get_address()``.
- Kivy lays out in pixels: ``Window.size == UIScreen.bounds * nativeScale``.

Every observation is logged as ``ios-webview: ...`` so the Xcode console can
be grepped. Run it with ``kivyforge run -p ios --simulator`` from this
directory (after ``kivyforge lock -p ios``); the prompt that drives the run
is docs/design/dev/ios-webview-spike-prompt.md. Without a simulator window,
set ``IOS_WEBVIEW_AUTORUN`` (see ``_schedule_autorun``).

On desktop the buttons are disabled and the layout still renders.
"""

from __future__ import annotations

import ctypes
import os
import traceback

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

DARK_BG = (0.08, 0.09, 0.12, 1)
DEFAULT_URL = "https://kivy.org"
IS_IOS = platform == "ios"


def log(message: str) -> None:
    Logger.info("ios-webview: %s", message)


def normalize_url(text: str) -> str:
    """Turn what was typed into an absolute URL.

    ``NSURL`` parses ``google.com`` as a relative path, and ``WKWebView``
    loads nothing for it without reporting an error, so a bare host gets
    ``https://``. Backslashes become slashes, as a browser's address bar does.
    """
    text = text.strip().replace("\\", "/")
    if not text:
        return DEFAULT_URL
    scheme, sep, rest = text.partition("://")
    if not sep:
        return "https://" + text
    return scheme.lower() + "://" + rest


# ---------------------------------------------------------------------------
# Geometry: Kivy pixels -> UIKit points
# ---------------------------------------------------------------------------


def ui_scale() -> float:
    """UIKit nativeScale, from kivy.mobile. 1.0 off iOS."""
    if not IS_IOS:
        return 1.0
    from kivy.mobile import get_scale

    return float(get_scale())


def kivy_rect_to_uikit(x: float, y: float, width: float, height: float) -> tuple:
    """Convert a Kivy rectangle (pixels, bottom-left origin) to a UIKit frame
    (points, top-left origin). The inverse of what ios.IOSWebView's callers
    had to do by hand."""
    scale = ui_scale()
    top_from_window_top = Window.height - (y + height)
    return (x / scale, top_from_window_top / scale, width / scale, height / scale)


# ---------------------------------------------------------------------------
# Variant A: pyobjus
# ---------------------------------------------------------------------------


def _get(obj, name):
    """Read an Objective-C property or call a no-argument method.

    pyobjus exposes properties as attributes and methods as callables, and the
    same selector (``rootViewController``, ``view``) is both in Objective-C.
    Accept either so the spike reports which form pyobjus chose rather than
    failing on it.
    """
    value = getattr(obj, name)
    return value() if callable(value) else value


WEBKIT_BINARY = "/System/Library/Frameworks/WebKit.framework/WebKit"


def load_webkit() -> None:
    """Load WebKit so the runtime can find ``WKWebView``.

    The app does not link WebKit, so the class does not exist until the
    framework is loaded. pyobjus's ``load_framework(INCLUDE.WebKit)`` cannot do
    it on iOS: it calls ``NSBundle.bundleWithPath_`` on the macOS path, which
    returns nil on the simulator, and ``bundle.load()`` on nil fails silently.
    ``dlopen`` goes through dyld, which resolves system frameworks on device
    and simulator alike. Loading an already loaded image is a no-op.
    """
    ctypes.CDLL(WEBKIT_BINARY)


def open_with_pyobjus(url: str, frame_points: tuple):
    """Objects through pyobjus, the frame through ctypes.

    pyobjus 1.2.4 copies a struct argument into a ``malloc(0)`` buffer, so a
    32-byte ``CGRect`` overruns it (kivy/pyobjus#90):
    ``initWithFrame_(NSRect(...))`` gave a 0x0 view on one launch and the
    right frame on the next. Object and string arguments are fine. So the view
    is created with a zero frame and placed with ``setFrame:`` sent through
    ``objc_msgSend``, using the pointer from ``get_address()``.
    """
    from pyobjus import autoclass, objc_str

    load_webkit()
    WKWebView = autoclass("WKWebView")
    NSURL = autoclass("NSURL")
    NSURLRequest = autoclass("NSURLRequest")
    UIApplication = autoclass("UIApplication")

    app = UIApplication.sharedApplication()
    window = _get(app, "keyWindow")
    if not window:
        window = _get(_get(app, "windows"), "firstObject")
    root_vc = _get(window, "rootViewController")
    root_view = _get(root_vc, "view")
    log(f"pyobjus: rootViewController={root_vc!r}")

    web_view = WKWebView.alloc().init()
    set_frame(web_view.get_address(), frame_points)
    root_view.addSubview_(web_view)
    log(f"pyobjus: frame={get_frame(web_view.get_address())}")
    ns_url = NSURL.URLWithString_(objc_str(url))
    if not ns_url:
        web_view.removeFromSuperview()
        raise ValueError(f"NSURL cannot parse {url!r}")
    web_view.loadRequest_(NSURLRequest.requestWithURL_(ns_url))
    return web_view


def close_with_pyobjus(web_view) -> None:
    web_view.removeFromSuperview()


# ---------------------------------------------------------------------------
# Variant B: ctypes over the Objective-C runtime
# ---------------------------------------------------------------------------


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


class _ObjC:
    """The few runtime entry points the recipe needs, typed per call."""

    def __init__(self) -> None:
        load_webkit()
        self.lib = ctypes.CDLL(None)
        self.lib.objc_getClass.restype = ctypes.c_void_p
        self.lib.objc_getClass.argtypes = [ctypes.c_char_p]
        self.lib.sel_registerName.restype = ctypes.c_void_p
        self.lib.sel_registerName.argtypes = [ctypes.c_char_p]
        self._msg_send = ctypes.cast(self.lib.objc_msgSend, ctypes.c_void_p).value

    def cls(self, name: bytes):
        return self.lib.objc_getClass(name)

    def sel(self, name: bytes):
        return self.lib.sel_registerName(name)

    def send(
        self, receiver, selector: bytes, *args, argtypes=(), restype=ctypes.c_void_p
    ):
        proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
        return proto(self._msg_send)(receiver, self.sel(selector), *args)

    def ns_string(self, text: str):
        return self.send(
            self.cls(b"NSString"),
            b"stringWithUTF8String:",
            text.encode("utf-8"),
            argtypes=(ctypes.c_char_p,),
        )


_objc: _ObjC | None = None


def _runtime() -> _ObjC:
    global _objc
    if _objc is None:
        _objc = _ObjC()
    return _objc


def set_frame(view, frame_points: tuple) -> None:
    x, y, w, h = frame_points
    _runtime().send(
        view,
        b"setFrame:",
        _CGRect(_CGPoint(x, y), _CGSize(w, h)),
        argtypes=(_CGRect,),
        restype=None,
    )


def get_frame(view) -> tuple:
    rect = _runtime().send(view, b"frame", restype=_CGRect)
    return (rect.origin.x, rect.origin.y, rect.size.width, rect.size.height)


def open_with_ctypes(url: str, frame_points: tuple):
    rt = _runtime()

    app = rt.send(rt.cls(b"UIApplication"), b"sharedApplication")
    window = rt.send(app, b"keyWindow")
    if not window:
        window = rt.send(rt.send(app, b"windows"), b"firstObject")
    root_vc = rt.send(window, b"rootViewController")
    root_view = rt.send(root_vc, b"view")
    log(f"ctypes: rootViewController=0x{root_vc or 0:x}")

    x, y, w, h = frame_points
    frame = _CGRect(_CGPoint(x, y), _CGSize(w, h))
    web_view = rt.send(rt.cls(b"WKWebView"), b"alloc")
    # CGRect by value: four doubles, an arm64 homogeneous aggregate in d0-d3.
    web_view = rt.send(web_view, b"initWithFrame:", frame, argtypes=(_CGRect,))
    rt.send(root_view, b"addSubview:", web_view, argtypes=(ctypes.c_void_p,))
    log(f"ctypes: frame={get_frame(web_view)}")
    ns_url = rt.send(
        rt.cls(b"NSURL"),
        b"URLWithString:",
        rt.ns_string(url),
        argtypes=(ctypes.c_void_p,),
    )
    if not ns_url:
        close_with_ctypes(web_view)
        raise ValueError(f"NSURL cannot parse {url!r}")
    request = rt.send(
        rt.cls(b"NSURLRequest"), b"requestWithURL:", ns_url, argtypes=(ctypes.c_void_p,)
    )
    rt.send(web_view, b"loadRequest:", request, argtypes=(ctypes.c_void_p,))
    return web_view


def close_with_ctypes(web_view) -> None:
    assert _objc is not None
    _objc.send(web_view, b"removeFromSuperview", restype=None)


# ---------------------------------------------------------------------------
# Units evidence
# ---------------------------------------------------------------------------


def log_units() -> None:
    """Log every number the conversion rests on, so the findings can quote them."""
    log(f"Window.size={tuple(Window.size)} Window.dpi={Window.dpi}")
    if not IS_IOS:
        return
    from kivy.mobile import get_dpi, get_keyboard_height, get_safe_area, get_scale

    log(
        f"kivy.mobile: scale={get_scale()} dpi={get_dpi()} "
        f"safe_area={get_safe_area()} keyboard_height={get_keyboard_height()}"
    )
    try:
        from pyobjus import autoclass

        screen = autoclass("UIScreen").mainScreen()
        bounds = _get(screen, "bounds")
        log(
            f"UIScreen.bounds={bounds.size.width}x{bounds.size.height} pt "
            f"nativeScale={_get(screen, 'nativeScale')}"
        )
    except Exception as exc:  # the bounds read is itself a struct-return test
        log(f"UIScreen.bounds via pyobjus failed: {exc!r}")
    log(
        "expected: Window.size == UIScreen.bounds * nativeScale if Kivy lays "
        "out in pixels; == UIScreen.bounds if in points"
    )


def log_keyboard(height_points: float) -> None:
    log(
        f"keyboard: kivy.mobile.get_keyboard_height()={height_points} pt, "
        f"Window.keyboard_height={Window.keyboard_height}, "
        f"scale={ui_scale()}, Window.height={Window.height}"
    )


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

KV = """
<WebViewSpikeRoot>:
    orientation: "vertical"
    padding: "16dp"
    spacing: "8dp"

    Label:
        id: status
        size_hint_y: None
        height: "48dp"
        font_size: "14sp"
        color: 0.5, 0.85, 1.0, 1
        halign: "center"
        valign: "middle"
        text_size: self.size
        text: root.status_text

    TextInput:
        id: url
        size_hint_y: None
        height: "40dp"
        multiline: False
        input_type: "url"
        keyboard_suggestions: False
        text: root.url
        on_text_validate: root.open_web_view("pyobjus")

    BoxLayout:
        size_hint_y: None
        height: "44dp"
        spacing: "8dp"
        Button:
            text: "Open (pyobjus)"
            disabled: not root.on_ios
            on_release: root.open_web_view("pyobjus")
        Button:
            text: "Open (ctypes)"
            disabled: not root.on_ios
            on_release: root.open_web_view("ctypes")
        Button:
            text: "Close"
            disabled: not root.on_ios
            on_release: root.close_web_view()

    # The web view goes over this area. Its Kivy rectangle is logged.
    Widget:
        id: web_area

WebViewSpikeRoot:
"""


class WebViewSpikeRoot(BoxLayout):
    status_text = StringProperty("")
    url = StringProperty(DEFAULT_URL)
    on_ios = BooleanProperty(IS_IOS)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._web_view = None
        self._variant = None

    def on_kv_post(self, _base_widget) -> None:
        self.status_text = (
            "iOS: open the URL in a WKWebView over the area below"
            if IS_IOS
            else "Desktop fallback: the web view is iOS-only"
        )
        Clock.schedule_once(lambda dt: log_units(), 0)
        if IS_IOS:
            from kivy.mobile import get_safe_area, subscribe_keyboard_height

            inset = get_safe_area()
            scale = ui_scale()
            self.padding = [
                dp(16) + inset["left"] * scale,
                dp(16) + inset["top"] * scale,
                dp(16) + inset["right"] * scale,
                dp(16) + inset["bottom"] * scale,
            ]
            subscribe_keyboard_height(
                lambda h: Clock.schedule_once(lambda dt: log_keyboard(h), 0)
            )
        self._schedule_autorun(os.environ.get("IOS_WEBVIEW_AUTORUN", ""))

    def _schedule_autorun(self, steps: str) -> None:
        """Press the buttons from ``IOS_WEBVIEW_AUTORUN``, e.g. ``"pyobjus close"``.

        For a simulator with no window to tap in (``xcrun simctl launch`` with
        ``SIMCTL_CHILD_IOS_WEBVIEW_AUTORUN=...``). One step every 3 seconds.
        """
        for n, step in enumerate(steps.split(), start=1):
            action = (
                self.close_web_view
                if step == "close"
                else (lambda s=step: self.open_web_view(s))
            )
            Clock.schedule_once(lambda dt, a=action: a(), 3 * n)

    def _web_area_frame_points(self) -> tuple:
        area = self.ids.web_area
        inset = dp(4)
        kivy_rect = (
            area.x + inset,
            area.y + inset,
            area.width - 2 * inset,
            area.height - 2 * inset,
        )
        frame = kivy_rect_to_uikit(*kivy_rect)
        log(f"web area: kivy px {kivy_rect} -> uikit pt {frame}")
        return frame

    def open_web_view(self, variant: str) -> None:
        self.close_web_view()
        url = normalize_url(self.ids.url.text)
        self.ids.url.text = url
        frame = self._web_area_frame_points()
        try:
            if variant == "pyobjus":
                self._web_view = open_with_pyobjus(url, frame)
            else:
                self._web_view = open_with_ctypes(url, frame)
        except Exception:
            log(f"{variant}: FAILED\n{traceback.format_exc()}")
            self.status_text = f"{variant}: failed, see log"
            self._web_view = None
            return
        self._variant = variant
        log(f"{variant}: web view opened for {url}")
        self.status_text = f"{variant}: opened {url}"

    def close_web_view(self) -> None:
        if self._web_view is None:
            return
        try:
            if self._variant == "pyobjus":
                close_with_pyobjus(self._web_view)
            else:
                close_with_ctypes(self._web_view)
            log(f"{self._variant}: web view closed")
            self.status_text = f"{self._variant}: closed"
        except Exception:
            log(f"{self._variant}: close FAILED\n{traceback.format_exc()}")
            self.status_text = f"{self._variant}: close failed, see log"
        self._web_view = None
        self._variant = None


class WebViewSpikeApp(App):
    def build(self) -> WebViewSpikeRoot:
        Window.clearcolor = DARK_BG
        return Builder.load_string(KV)


WebViewSpikeApp().run()
