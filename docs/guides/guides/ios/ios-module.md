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
- For the web view, add `rubicon-objc` to your dependencies and re-lock. See
  [Call iOS APIs with Rubicon-ObjC](rubicon.md).

## What replaces each name

| kivy-ios `ios` | Replacement | Note |
|---|---|---|
| `get_scale()` | `kivy.mobile.get_scale()` | same value |
| `get_dpi()` | `kivy.mobile.get_dpi()` | float, and an estimate (`163 × scale`, `132 × scale` on iPad) rather than a per-model table, which Kivy dropped because it "topped out at iPhone 13" (kivy#9331); this is also what `Metrics.dpi` reports on Kivy 3 |
| `get_safe_area()` | `kivy.mobile.get_safe_area()`, or bind `Window.safe_area` | same dict and keys, but in Kivy **pixels**: the old function returned UIKit points, so drop any multiplication by the scale (see [Points and pixels](#points-and-pixels)) |
| `get_kheight()` | `kivy.mobile.get_keyboard_height()`, or bind `Window.keyboard_height` | same unit, Kivy **pixels**. Kivy removed `get_kheight` itself as "internal convention, never documented as public API" (kivy#9331) |
| `IOSKeyboard`, `iOSKeyboard` | `kivy.mobile.subscribe_keyboard_height(callback)` | Kivy's `Window` already subscribes; most apps need nothing |
| `open_url(url)`, `IosBrowser` | `webbrowser.open(url)` | the standard library registers the iOS backend itself; works on every platform |
| `IOSWebView().open(url, x, y, width, height)`, `open_url_wbv(...)` | `WKWebView` through Rubicon-ObjC, with WebKit loaded first ([recipe below](#show-a-web-view), condensed from the `ios-webview` example) | add `rubicon-objc` to `[project].dependencies`. The frame is UIKit points with a top-left origin, as before: from a Kivy rectangle, divide by `get_scale()` and take `y` from the top |
| `send_email(...)` | plyer's `email` facade (`mailto:`, any default mail app) for subject and body; `UIActivityViewController` through Rubicon-ObjC for a file | the old function worked only where the Apple Mail app has an account |
| the file chooser | plyer's `filechooser` facade (plyer needs [pyobjus](pyobjus.md) for it), or `PHPickerViewController` through Rubicon-ObjC | the old module never exposed one to Python |
| `import ios` in cross-platform code | `from kivy.utils import platform`, then `if platform in ("ios", "android"): import kivy.mobile` | `kivy.mobile` raises `ImportError` on desktop by design |

[plyer](https://github.com/kivy/plyer)'s iOS facades don't import `ios`, so they
need nothing from it. kivyforge hasn't run them against Kivy 3 yet, so test the
ones you use.

## Points and pixels

Kivy 3 lays out in **pixels** on iOS. On an iPhone Air simulator (scale 3) the
Kivy window was 1260 × 2736 and `UIScreen.bounds` was 420 × 912 points, so one
point is three Kivy pixels. UIKit, and so the web view below, works in
**points**.

`kivy.mobile.get_keyboard_height()` and `kivy.mobile.get_safe_area()`, and
`Window.keyboard_height` and `Window.safe_area`, which come from them, are in
Kivy pixels, so use them as Kivy sizes directly:

```python
from kivy.utils import platform

if platform == "ios":
    import kivy.mobile as mobile

    keyboard = mobile.get_keyboard_height()  # was ios.get_kheight()
    insets = mobile.get_safe_area()  # was ios.get_safe_area(), in points
```

This needs a Kivy build that includes
[kivy/kivy#9441](https://github.com/kivy/kivy/pull/9441). Earlier Kivy 3
builds return UIKit points for both, a third of the right size on a scale-3
device (the measurements are in
`docs/design/dev/ios-webview-spike-findings.md`).

The old `get_kheight()` already returned pixels, so code moving from `ios`
changes nothing for the keyboard. The old `get_safe_area()` returned points, so
remove any multiplication by `get_scale()` you applied to it.

## Show a web view

The web view is the one function with no drop-in replacement. The recipe
calls UIKit and WebKit through [Rubicon-ObjC](rubicon.md):

```python
from rubicon.objc import CGPoint, CGRect, CGSize, ObjCClass
from rubicon.objc.runtime import load_library

# The app does not link WebKit, so WKWebView does not exist until the
# framework is loaded.
load_library("WebKit")

WKWebView = ObjCClass("WKWebView")
NSURL = ObjCClass("NSURL")
NSURLRequest = ObjCClass("NSURLRequest")
UIApplication = ObjCClass("UIApplication")


def set_frame(web_view, x, y, width, height):
    web_view.frame = CGRect(CGPoint(x, y), CGSize(width, height))


def open_web_view(url, x, y, width, height):
    """Show *url* in a WKWebView over the Kivy window.

    x, y, width and height are UIKit points with the origin at the top left,
    the same units and origin the old ios.IOSWebView took. From a Kivy
    rectangle (pixels, bottom-left origin): divide by kivy.mobile.get_scale()
    and use (Window.height - top_edge) / scale for y. Keep the returned
    object and call .removeFromSuperview() to close it.
    """
    # sharedApplication, keyWindow, rootViewController and view are
    # properties, so none is called.
    app = UIApplication.sharedApplication
    window = app.keyWindow or app.windows.firstObject
    root_view = window.rootViewController.view

    web_view = WKWebView.alloc().init()
    set_frame(web_view, x, y, width, height)
    root_view.addSubview(web_view)

    if "://" not in url:
        url = "https://" + url  # NSURL reads a bare host as a relative path
    ns_url = NSURL.URLWithString(url)
    if ns_url is None:
        web_view.removeFromSuperview()
        raise ValueError(f"not a URL: {url!r}")
    web_view.loadRequest(NSURLRequest.requestWithURL(ns_url))
    return web_view
```

Call `open_web_view` from a button handler and keep what it returns. Calling
`.removeFromSuperview()` on that object closes the view. That replaces the old
module's hard-coded "X" button, so draw your own close button in Kivy.

Three things to know:

- **The web view does not follow rotation.** UIKit places it once, at the frame
  you gave. If your app can rotate, or its layout otherwise changes, recompute
  the frame and call `set_frame` again.
- **UIKit calls belong on the main thread**, which is where Kivy runs your
  event handlers and `Clock` callbacks. From a worker thread, hand the call over
  with `Clock.schedule_once`.
- **A URL without a scheme loads nothing, and says nothing.** The recipe adds
  `https://` for that reason, and raises `ValueError` when `NSURL` can't parse
  the string.

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

In the app, type a URL and tap **Open**. The web page appears over the
Kivy area, and the log shows `ios-webview: frame=...` with the frame it
set. Tap **Close** and the view goes away.

Xcode 27 doesn't ship Simulator.app. `kivyforge run -p ios --simulator` still
boots the simulator and installs the app, and Xcode shows the screen in **Device
Hub**.

## What's next

- [Call iOS APIs with Rubicon-ObjC](rubicon.md).
- [Handle mobile screen geometry](../cross-platform/mobile-geometry.md).
- [Migrate from buildozer, p4a, or kivy-ios](../cross-platform/migrate.md).
