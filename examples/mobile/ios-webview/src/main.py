"""ios-webview — the web view recipe in the ios-module guide.

kivyforge does not ship the kivy-ios ``ios`` module
(docs/design/dev/ios-module-proposal.md). The one function of that module
with no drop-in replacement is ``ios.IOSWebView().open(url, x, y, w, h)``,
which put a ``WKWebView`` over the Kivy window. The ios-module guide carries
a short recipe for it instead, and this app is the working code it is
condensed from. It calls UIKit and WebKit through Rubicon-ObjC.

It also logs the numbers the guide's unit conversion rests on. Kivy 3's SDL3
window is created high-pixel-density and lays out in **pixels**;
``kivy.mobile`` reports Kivy pixels too (with kivy/kivy#9441; earlier Kivy 3
builds return UIKit points); UIKit frames are points with a top-left origin.
The keyboard height from ``Window`` and from ``kivy.mobile`` is logged side by
side when the URL field is focused.

What the runs settled (docs/design/dev/ios-webview-spike-findings.md):

- The app does not link WebKit, so ``WKWebView`` does not exist until the
  framework is loaded. ``load_library("WebKit")`` loads it through dyld.
- Kivy lays out in pixels: ``Window.size == UIScreen.bounds * nativeScale``.

The first run compared pyobjus with raw ``ctypes``; pyobjus needed ``ctypes``
for loading WebKit and for every ``CGRect``. Rubicon-ObjC needs neither.

Every observation is logged as ``ios-webview: ...`` so the Xcode console can
be grepped. Run it with ``kivyforge run -p ios --simulator`` from this
directory (after ``kivyforge lock -p ios``). Without a simulator window, set
``IOS_WEBVIEW_AUTORUN`` (see ``_schedule_autorun``).

On desktop the buttons are disabled and the layout still renders.
"""

from __future__ import annotations

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
# The web view, through Rubicon-ObjC
# ---------------------------------------------------------------------------


def load_webkit() -> None:
    """Load WebKit so the runtime can find ``WKWebView``.

    The app does not link WebKit, so the class does not exist until the
    framework is loaded. On iOS, ``load_library`` falls back to
    ``/System/Library/Frameworks/WebKit.framework/WebKit``; ``dlopen``
    resolves that from the dyld shared cache on device and simulator alike.
    Loading an already loaded image is a no-op.
    """
    from rubicon.objc.runtime import load_library

    load_library("WebKit")


def set_frame(view, frame_points: tuple) -> None:
    """Place ``view`` at a UIKit frame; call again when the layout changes."""
    from rubicon.objc import CGPoint, CGRect, CGSize

    x, y, w, h = frame_points
    view.frame = CGRect(CGPoint(x, y), CGSize(w, h))


def get_frame(view) -> tuple:
    rect = view.frame
    return (rect.origin.x, rect.origin.y, rect.size.width, rect.size.height)


def open_web_view(url: str, frame_points: tuple):
    """Show ``url`` in a WKWebView over the Kivy window, at a UIKit frame."""
    from rubicon.objc import ObjCClass

    load_webkit()
    WKWebView = ObjCClass("WKWebView")
    NSURL = ObjCClass("NSURL")
    NSURLRequest = ObjCClass("NSURLRequest")
    UIApplication = ObjCClass("UIApplication")

    # sharedApplication, keyWindow, rootViewController and view are all
    # properties, so none is called.
    app = UIApplication.sharedApplication
    window = app.keyWindow or app.windows.firstObject
    root_view = window.rootViewController.view
    log(f"root view={root_view!r}")

    web_view = WKWebView.alloc().init()
    set_frame(web_view, frame_points)
    root_view.addSubview(web_view)
    log(f"frame={get_frame(web_view)}")
    ns_url = NSURL.URLWithString(url)
    if ns_url is None:
        web_view.removeFromSuperview()
        raise ValueError(f"NSURL cannot parse {url!r}")
    web_view.loadRequest(NSURLRequest.requestWithURL(ns_url))
    return web_view


def close_web_view(web_view) -> None:
    web_view.removeFromSuperview()


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
    from rubicon.objc import ObjCClass

    screen = ObjCClass("UIScreen").mainScreen
    bounds = screen.bounds
    log(
        f"UIScreen.bounds={bounds.size.width}x{bounds.size.height} pt "
        f"nativeScale={screen.nativeScale}"
    )
    log(
        "expected: Window.size == UIScreen.bounds * nativeScale if Kivy lays "
        "out in pixels; == UIScreen.bounds if in points"
    )


def log_keyboard(height: float) -> None:
    log(
        f"keyboard: kivy.mobile.get_keyboard_height()={height}, "
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
        on_text_validate: root.open_web_view()

    BoxLayout:
        size_hint_y: None
        height: "44dp"
        spacing: "8dp"
        Button:
            text: "Open"
            disabled: not root.on_ios
            on_release: root.open_web_view()
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
            self.padding = [
                dp(16) + inset["left"],
                dp(16) + inset["top"],
                dp(16) + inset["right"],
                dp(16) + inset["bottom"],
            ]
            subscribe_keyboard_height(
                lambda h: Clock.schedule_once(lambda dt: log_keyboard(h), 0)
            )
        self._schedule_autorun(os.environ.get("IOS_WEBVIEW_AUTORUN", ""))

    def _schedule_autorun(self, steps: str) -> None:
        """Press the buttons from ``IOS_WEBVIEW_AUTORUN``, e.g. ``"open close"``.

        For a simulator with no window to tap in (``xcrun simctl launch`` with
        ``SIMCTL_CHILD_IOS_WEBVIEW_AUTORUN=...``). One step every 3 seconds.
        """
        for n, step in enumerate(steps.split(), start=1):
            action = self.close_web_view if step == "close" else self.open_web_view
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

    def open_web_view(self) -> None:
        self.close_web_view()
        url = normalize_url(self.ids.url.text)
        self.ids.url.text = url
        frame = self._web_area_frame_points()
        try:
            self._web_view = open_web_view(url, frame)
        except Exception:
            log(f"open FAILED\n{traceback.format_exc()}")
            self.status_text = "open failed, see log"
            self._web_view = None
            return
        log(f"web view opened for {url}")
        self.status_text = f"opened {url}"

    def close_web_view(self) -> None:
        if self._web_view is None:
            return
        try:
            close_web_view(self._web_view)
            log("web view closed")
            self.status_text = "closed"
        except Exception:
            log(f"close FAILED\n{traceback.format_exc()}")
            self.status_text = "close failed, see log"
        self._web_view = None


class WebViewSpikeApp(App):
    def build(self) -> WebViewSpikeRoot:
        Window.clearcolor = DARK_BG
        return Builder.load_string(KV)


WebViewSpikeApp().run()
