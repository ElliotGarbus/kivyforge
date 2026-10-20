# Findings — `WKWebView` recipe spike (Mac, 2026-10-19)

Results of [`ios-webview-spike-prompt.md`](ios-webview-spike-prompt.md),
run with `examples/mobile/ios-webview`. Taps by the owner in Device Hub;
unattended passes through the app's `IOS_WEBVIEW_AUTORUN` hook (below).

## Environment

| | |
|---|---|
| Host | macOS 26.6.2, `arm64` |
| Xcode | 27.0 (27A266a). Ships **Device Hub**, not Simulator.app (see Defect 4) |
| Simulator | iPhone Air, iOS 27.0 (24A434) |
| kivyforge | branch `lock-inputs` at `60e7602e`, plus the `main.py` fixes below |
| Python | 3.15.0b4 (iOS XCframework) |
| Kivy | 3.0.0.dev202610051055 (SDL3) |
| pyobjus | 1.2.4 (from `pylock.ios.toml`) |

## Defects

### 1. pyobjus `load_framework(INCLUDE.WebKit)` loads nothing on iOS

The first tap on **Open (pyobjus)**, verbatim:

```text
[INFO   ] [ios-webview ] pyobjus: FAILED
Traceback (most recent call last):
  File ".../ios-webview.app/app/main.py", line 361, in open_web_view
    self._web_view = open_with_pyobjus(url, frame)
  File ".../ios-webview.app/app/main.py", line 102, in open_with_pyobjus
    WKWebView = autoclass("WKWebView")
  File "pyobjus/pyobjus.pyx", line 763, in pyobjus.autoclass
  File "pyobjus/pyobjus.pyx", line 103, in pyobjus.MetaObjcClass.__new__
  File "pyobjus/pyobjus.pyx", line 134, in pyobjus.MetaObjcClass.resolve_class
pyobjus.ObjcException: Unable to find class b'WKWebView'
```

`load_framework` is `NSBundle.bundleWithPath_(path).load()`.
`INCLUDE.WebKit` is the macOS path `/System/Library/Frameworks/WebKit.framework`.
On the simulator `bundleWithPath_` returns nil for it, and calling `load()` on
nil does nothing and raises nothing. The ctypes variant worked only because
it `dlopen`s the WebKit binary itself. `dlopen` goes through dyld, which
resolves system frameworks on the simulator, and should on a device as well
(not tested).

**Fix:** `load_webkit()` = `ctypes.CDLL("/System/Library/Frameworks/WebKit.framework/WebKit")`,
shared by both variants. The startup line `Got dlopen error on Foundation:
dlopen(.../Foundation.framework/Versions/Current/Foundation ...)` comes from
pyobjus's own module, which uses the same macOS layout. It is harmless: the
classes come from the already-loaded image, and `UIScreen` works right after.

### 2. pyobjus does not pass floating-point arguments reliably

With WebKit loaded, `WKWebView.alloc().initWithFrame_(NSRect(NSPoint(x, y), NSSize(w, h)))`
reported success but showed nothing. Reading the frame back through pyobjus:

```text
[INFO   ] [ios-webview ] pyobjus DEBUG frame=20.0,176.0,0.0,0.0
```

The origin arrived and the size was zero. On the next launch the same call gave
the right frame (`initWithFrame_ gave frame=(20.0, 176.0, 380.0, 716.0)`). An
Auto Layout workaround then failed the other way:
`constraintEqualToAnchor_constant_(anchor, 20.0)` received `0.0` for the
constant (`after constraints frame=(0.0, 0.0, 380.0, 716.0)`), while
`constraintEqualToConstant_` (a single double) worked. On arm64 that looks
like floating-point registers not being set up for every argument. Object,
string and integer arguments, and struct *returns* (`UIScreen.bounds`, `frame`),
were correct every time.

**Fix:** the pyobjus variant creates the view with `init()` and sets the frame
with `setFrame:` through `objc_msgSend`, using the object's pointer from
`get_address()`. Read back after that: `pyobjus: frame=(20.0, 244.0, 380.0, 614.0)`,
on every launch.

### 3. A URL without a scheme loads nothing, silently

Typing `google.com` gave a blank web view. The log shows what reached `NSURL`:
`Google.com` (iOS auto-capitalised it) and `HtTTPS:\\google.com`. `NSURL`
parses a string with no scheme as a relative path, and `WKWebView` loads
nothing for it without an error. Not a recipe defect, but every app that takes
typed input hits it.

**Fix:** `normalize_url()` adds `https://` when there is no scheme, turns
backslashes into slashes and lowercases the scheme. An unparseable URL (nil
`NSURL`) now raises and shows "failed, see log". After the fix the owner
confirmed `https://Google.com` loads through both variants. The field's
`input_type: "url"` did **not** stop auto-capitalisation (still `Google.com`);
hostnames are case-insensitive, so this is cosmetic.

### 4. Xcode 27 has no Simulator.app

`open -a Simulator` fails, and `Xcode.app/Contents/Developer/Applications` does
not exist. `simctl` still boots, installs and launches, so `kivyforge run -p ios
--simulator` works, but there is no window to tap. The screen is shown by
**Device Hub** (`Xcode.app/Contents/Applications/DeviceHub.app`). Not a
kivyforge defect; the prompt's "Tap ..." steps and any doc that says "open
Simulator" need the new name.

## Units

```text
[INFO   ] [ios-webview ] Window.size=(1260.0, 2736.0) Window.dpi=96.0
[INFO   ] [ios-webview ] kivy.mobile: scale=3.0 dpi=489.0 safe_area={'top': 68.0, 'left': 0.0, 'bottom': 34.0, 'right': 0.0} keyboard_height=0.0
[INFO   ] [ios-webview ] UIScreen.bounds=420.0x912.0 pt nativeScale=3.0
```

`1260 = 420 * 3` and `2736 = 912 * 3`: **Kivy lays out in pixels** on iOS, and
`kivy.mobile`'s values are points that need `* get_scale()`. This matches
kivyforge's `mobile-geometry` guide; `kivy/mobile/__init__.py`'s docstring is
the one that is wrong. The web-view frame confirms it from the other side:
`web area: kivy px (60.0, 162.0, 1140.0, 1842.0) -> uikit pt (20.0, 244.0, 380.0, 614.0)`
puts the view exactly over the Kivy area (owner-confirmed, and in screenshots
taken during the run).

## Keyboard — a Kivy defect (units only)

Rechecked 2026-10-20 against Kivy master (`bdac6a6`), whose
`kivy/mobile/__init__.py`, `kivy/mobile/_platform/ios.py` and `Window`
keyboard code are identical to the wheel this run used
(3.0.0.dev202610051055, `git-56baa54`).

**Units: confirmed.** With the keyboard on screen, logged by the app's own
Kivy log:

```text
keyboard: kivy.mobile.get_keyboard_height()=347.0 pt, Window.keyboard_height=347.0, scale=3.0, Window.height=2736.0
```

A simulator screenshot taken at the same time is 1260 x 2736, the same as
`Window.size`, and the keyboard covers its bottom ~1040 px: 347 pt x 3. So
`Window.keyboard_height` is the keyboard height in UIKit points, while the
iOS window is laid out in pixels (`SDL_WINDOW_HIGH_PIXEL_DENSITY`; touch
positions are multiplied by the pixel density in `window_sdl3.py`). Every
consumer is short by the scale factor: `softinput_mode` `pan` and
`below_target` move content 347 px instead of 1041, and `scale` shrinks the
viewport by a third of the keyboard. The cause is `kivy.mobile`'s iOS
backend, whose docstring says points "equal Kivy layout coordinates on iOS
(nativeScale applies only to rasterization, not layout)"; under SDL3 they do
not. `get_safe_area()` has the same mismatch, so `Window.safe_area` is in
points too. The Android backend returns pixels for both, which do match
Kivy's layout there, so this is iOS-only.

**Not a defect: "mostly zero".** The first version of this section reported
`Window.keyboard_height` as 0 in 9 of 12 readings. That came from the app's
logging, not from Kivy. `Window.keyboard_height` is an `AliasProperty` whose
getter returns the same live `get_keyboard_height()`, and the log line
printed the height passed to the subscription callback next to
`Window.keyboard_height` read one frame later. A line like `289.0 pt ...
Window.keyboard_height=0.0` is the keyboard reporting 289 and then, before
the next frame, 0. Whenever the keyboard stayed up, the two agreed (347 and
347).

To report upstream; not patched here. The fix belongs in
`kivy/mobile/_platform/ios.py` (return pixels, multiplying by `get_scale()`,
as Android does) or in `Window` when it reads it. Until then, the guide's
`get_kheight` row should use `kivy.mobile.get_keyboard_height() * get_scale()`.

## Rotation

With a web view open, rotating the simulator moved nothing. The app is
portrait-only (`orientation = ["portrait"]`), so the window did not rotate
either. That fits the guide's statement that the web view does not follow
layout changes unless the app resizes it, but it does not test that statement
directly; a landscape-capable app would.

## Which variant the guide carries

Neither as originally written. Both need the WebKit load fix, and pyobjus
cannot pass the frame. The recipe the guide should print is the pyobjus
variant in `examples/mobile/ios-webview/src/main.py`: pyobjus for objects and
strings, plus about 25 lines of ctypes for `load_webkit()` and `setFrame:`.
The pure-ctypes variant also works, but it is longer and harder to read for
no gain. Properties: `_get` was needed for `keyWindow`, `rootViewController`
and `view`, because pyobjus returned each as a callable in some cases and a
value in others. The recipe should keep that helper or call them as methods.

## Unattended runs

Without Simulator.app there was nothing to tap at first, so the app gained
`IOS_WEBVIEW_AUTORUN`: a space-separated list of `pyobjus`, `ctypes` and
`close`, one step every 3 seconds.

```bash
SIMCTL_CHILD_IOS_WEBVIEW_AUTORUN="pyobjus close ctypes close pyobjus" \
  xcrun simctl launch --console-pty <udid> org.kivy.ios-webview
```

That sequence logged no failures, and each Open read back
`frame=(20.0, 244.0, 380.0, 614.0)`.

## Keep the example?

Keep it as a permanent example. It is the only thing in the repo that
exercises pyobjus's two failure modes above, and the guide's Verify section can
point at it. Its docstring now records what this run settled.
