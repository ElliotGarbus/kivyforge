---
title: Replace the kivy-ios ios module
sources:
  - docs/design/dev/ios-module-proposal.md
  - docs/design/dev/ios-webview-spike-findings.md
  - kivyforge/platforms/ios/legacy_module.py
  - examples/mobile/ios-webview/src/main.py
---

# Replace the kivy-ios ios module

Apps built with kivy-ios can `import ios`, a compiled module that gives them the
screen scale, DPI, safe-area insets, keyboard height, a web browser, a web view
overlay and a mail composer. kivyforge does not provide it. Kivy 3 and the
standard library already cover the same ground, on iOS and on every other
platform, so this page maps each name to its replacement and shows how to put a
web view on screen.

Moving an app from kivy-ios to kivyforge already means moving to Kivy 3, which
is built on SDL3, so this is a small part of a change you are making anyway.

## Before you begin

- [Configure your iOS app](configure.md). Kivy 3 is required on iOS.
- For the web view, add `pyobjus` to your dependencies and re-lock. See
  [Call iOS APIs with pyobjus](pyobjus.md).

## What replaces each name

| kivy-ios `ios` | Replacement | Note |
|---|---|---|
| `get_scale()` | `kivy.mobile.get_scale()` | same value |
| `get_dpi()` | `kivy.mobile.get_dpi()` | float, and an estimate (`163 × scale`, `132 × scale` on iPad) rather than a per-model table, which Kivy dropped because it "topped out at iPhone 13" (kivy#9331); this is also what `Metrics.dpi` reports on Kivy 3 |
| `get_safe_area()` | `kivy.mobile.get_safe_area()`, or bind `Window.safe_area` | same dict, same keys, same unit (UIKit points). Multiply by `get_scale()` for Kivy pixels, as the [mobile geometry guide](../cross-platform/mobile-geometry.md) shows; the old function needed the same |
| `get_kheight()` | `kivy.mobile.get_keyboard_height() * kivy.mobile.get_scale()` | the old function returned **pixels** (it multiplied by the scale internally); `kivy.mobile` returns **points**, so the caller multiplies. Do not read `Window.keyboard_height` for this on iOS yet: measured, it is the unscaled points value and reads 0 most of the time the keyboard is up (see [Points and pixels](#points-and-pixels)); a Kivy defect to report. Kivy removed `get_kheight` itself as "internal convention, never documented as public API" (kivy#9331) |
| `IOSKeyboard`, `iOSKeyboard` | `kivy.mobile.subscribe_keyboard_height(callback)` | Kivy's `Window` already subscribes; most apps need nothing |
| `open_url(url)`, `IosBrowser` | `webbrowser.open(url)` | the standard library registers the iOS backend itself; works on every platform |
| `IOSWebView().open(url, x, y, width, height)`, `open_url_wbv(...)` | `WKWebView` through `pyobjus`, with WebKit loaded and the frame set through ctypes ([recipe below](#show-a-web-view), condensed from the spike's working code) | add `pyobjus` to `[project].dependencies`. The frame is UIKit points with a top-left origin, as before: from a Kivy rectangle, divide by `get_scale()` and take `y` from the top |
| `send_email(...)` | plyer's `email` facade (`mailto:`, any default mail app) for subject and body; `UIActivityViewController` through `pyobjus` for a file | the old function worked only where the Apple Mail app has an account |
| the file chooser | plyer's `filechooser` facade (needs `pyobjus`), or `PHPickerViewController` through `pyobjus` | the old module never exposed one to Python |
| `import ios` in cross-platform code | `from kivy.utils import platform`, then `if platform in ("ios", "android"): import kivy.mobile` | `kivy.mobile` raises `ImportError` on desktop by design |

[plyer](https://github.com/kivy/plyer)'s iOS facades don't import `ios`, so they
need nothing from it. kivyforge hasn't run them against Kivy 3 yet, so test the
ones you use.

## Points and pixels

`kivy.mobile` returns UIKit **points**. Kivy 3 lays out in **pixels** on iOS.
Multiply everything `kivy.mobile` returns by `kivy.mobile.get_scale()` before you
use it as a Kivy size:

```python
from kivy.utils import platform

if platform == "ios":
    import kivy.mobile as mobile

    scale = mobile.get_scale()
    keyboard = mobile.get_keyboard_height() * scale  # was ios.get_kheight()
    insets = {side: value * scale for side, value in mobile.get_safe_area().items()}
```

On an iPhone Air simulator (scale 3) the Kivy window was 1260 × 2736 and
`UIScreen.bounds` was 420 × 912 points, so one point is three Kivy pixels. The
old `get_kheight()` multiplied by the scale for you, and `get_safe_area()` never
did, so code moving from `ios` keeps its multiplication for the keyboard and
adds one for the safe area.

Do not use `Window.keyboard_height` on iOS until Kivy fixes it. It returns the
points value without the multiplication, and it was `0` in 9 of 12 readings
taken while `kivy.mobile` reported a keyboard (the measurements are in
`docs/design/dev/ios-webview-spike-findings.md`). Read
`kivy.mobile.get_keyboard_height()` directly, as above.

## Show a web view

The web view is the one function with no drop-in replacement. The recipe uses
[pyobjus](pyobjus.md) for the objects and about twenty-five lines of
[ctypes](https://docs.python.org/3/library/ctypes.html) for the two things
pyobjus gets wrong on iOS. Both are commented in the code:

```python
import ctypes

from pyobjus import autoclass, objc_str

# The app does not link WebKit, so WKWebView does not exist until the
# framework is loaded. pyobjus's load_framework() is a silent no-op on iOS
# (it uses the macOS bundle path), so load the binary through dyld instead.
ctypes.CDLL("/System/Library/Frameworks/WebKit.framework/WebKit")

WKWebView = autoclass("WKWebView")
NSURL = autoclass("NSURL")
NSURLRequest = autoclass("NSURLRequest")
UIApplication = autoclass("UIApplication")


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


def _get(obj, name):
    """pyobjus returns a property such as keyWindow or view sometimes as a
    value and sometimes as a callable; accept either."""
    value = getattr(obj, name)
    return value() if callable(value) else value


def _set_frame(view, x, y, width, height):
    """pyobjus 1.2.4 passes CGRect and CGFloat arguments unreliably on arm64,
    so the frame is sent through objc_msgSend directly."""
    lib = ctypes.CDLL(None)
    lib.sel_registerName.restype = ctypes.c_void_p
    lib.sel_registerName.argtypes = [ctypes.c_char_p]
    send = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, _CGRect)(
        ctypes.cast(lib.objc_msgSend, ctypes.c_void_p).value
    )
    rect = _CGRect(_CGPoint(x, y), _CGSize(width, height))
    send(view.get_address(), lib.sel_registerName(b"setFrame:"), rect)


def open_web_view(url, x, y, width, height):
    """Show *url* in a WKWebView over the Kivy window.

    x, y, width and height are UIKit points with the origin at the top left,
    the same units and origin the old ios.IOSWebView took. From a Kivy
    rectangle (pixels, bottom-left origin): divide by kivy.mobile.get_scale()
    and use (Window.height - top_edge) / scale for y. Keep the returned
    object and call .removeFromSuperview() to close it.
    """
    app = UIApplication.sharedApplication()
    window = _get(app, "keyWindow")
    if not window:
        window = _get(_get(app, "windows"), "firstObject")
    root_view = _get(_get(window, "rootViewController"), "view")

    web_view = WKWebView.alloc().init()
    _set_frame(web_view, x, y, width, height)
    root_view.addSubview_(web_view)

    if "://" not in url:
        url = "https://" + url  # NSURL reads a bare host as a relative path
    ns_url = NSURL.URLWithString_(objc_str(url))
    if not ns_url:
        web_view.removeFromSuperview()
        raise ValueError(f"not a URL: {url!r}")
    web_view.loadRequest_(NSURLRequest.requestWithURL_(ns_url))
    return web_view
```

Call `open_web_view` from a button handler and keep what it returns. Calling
`.removeFromSuperview()` on that object closes the view. That replaces the old
module's hard-coded "X" button, so draw your own close button in Kivy.

Three things to know:

- **The web view does not follow rotation.** UIKit places it once, at the frame
  you gave. If your app can rotate, or its layout otherwise changes, recompute
  the frame and call `_set_frame` again.
- **UIKit calls belong on the main thread**, which is where Kivy runs your
  event handlers and `Clock` callbacks. From a worker thread, hand the call over
  with `Clock.schedule_once`.
- **A URL without a scheme loads nothing, and says nothing.** The recipe adds
  `https://` for that reason, and raises `ValueError` when `NSURL` can't parse
  the string.

At startup the app logs a `Got dlopen error on Foundation` line from pyobjus.
It's harmless: the classes come from the image that's already loaded.

## kivyforge warns when an app still imports `ios`

`kivyforge build -p ios` and `kivyforge doctor -p ios` scan every `.py` file
under your `app_dir` for `import ios` and `from ios import ...`, indented or
not, and warn with `KF-IOS-LEGACY-IOS-MODULE`:

```text
[build] warning: src/main.py:3 imports the kivy-ios `ios` module, which kivyforge does not provide
```

It is a warning, so the build goes on: an import guarded by `if platform ==
"ios":` may be fine. Under `--json` it appears in `diagnostics` on an `ok: true`
run. The warning is quiet when your `app_dir` has its own `ios.py` or `ios/`
package. Dependencies aren't scanned.

## Verify

The `ios-webview` example in the kivyforge repository holds the working code the
recipe is condensed from, and logs each step with an `ios-webview:` prefix:

```bash
cd examples/mobile/ios-webview
kivyforge lock -p ios
kivyforge run -p ios --simulator
```

In the app, type a URL and tap **Open (pyobjus)**. The web page appears over the
Kivy area, and the log shows `ios-webview: pyobjus: frame=...` with the frame it
set. Tap **Close** and the view goes away.

Xcode 27 doesn't ship Simulator.app. `kivyforge run -p ios --simulator` still
boots the simulator and installs the app, and Xcode shows the screen in **Device
Hub**.

## What's next

- [Call iOS APIs with pyobjus](pyobjus.md).
- [Handle mobile screen geometry](../cross-platform/mobile-geometry.md).
- [Migrate from buildozer, p4a, or kivy-ios](../cross-platform/migrate.md).
