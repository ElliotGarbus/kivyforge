# Agent prompt — spike the `WKWebView` recipe for the ios-module guide (Mac)

> **Run this on the Mac**, from the repo root on `lock-inputs` (or wherever
> `examples/mobile/ios-webview` has landed). Written 2026-10-19 from the
> Windows host, where none of it can run — it needs the iOS simulator.
>
> Point the agent at this file, or copy the "Prompt" section. Results go in
> `docs/design/dev/ios-webview-spike-findings.md` (shape: environment table,
> per-step commands and verbatim log lines, defects first).

## Background — what this decides

[`ios-module-proposal.md`](ios-module-proposal.md) decided that kivyforge
does not provide the kivy-ios `ios` module; a migration guide maps each old
name to Kivy 3 and the standard library. Every mapping is a one-liner except
the web view: `ios.IOSWebView().open(url, x, y, w, h)` put a `WKWebView` over
the Kivy window, and the guide will carry a short pyobjus recipe instead.
Nothing in that recipe has run. The guide cannot be written until it has.

`examples/mobile/ios-webview` is the spike app. It opens a `WKWebView` over
the lower part of its window two ways, and logs every number it uses as
`ios-webview: ...` lines:

- **Open (pyobjus)** — the recipe as the guide would print it:
  `WKWebView.alloc().initWithFrame_(NSRect(...))`. The open question is
  whether pyobjus passes a `CGRect` argument correctly. pyobjus's conversion
  code says struct *arguments* are fine ("no problems with structs, only
  unions"); its known weakness is struct *returns* of doubles
  (kivy/pyobjus#148, why `pyobjus-ball` uses ctypes).
- **Open (ctypes)** — the same calls through `objc_msgSend` with ctypes,
  passing `CGRect` by value. The fallback the guide carries if pyobjus
  cannot.
- **Close** — `removeFromSuperview`, which is what the guide tells apps to
  do instead of the old module's hard-coded "X" button.

It also answers a units question the guide's `get_kheight` row depends on.
Kivy 3's SDL3 window is created `SDL_WINDOW_HIGH_PIXEL_DENSITY` and lays out
in pixels; `kivy.mobile` reports UIKit points; `Window.keyboard_height` reads
`kivy.mobile.get_keyboard_height()` **unscaled** (`kivy/core/window/__init__.py`,
`_get_kheight`). If the window is in pixels, `Window.keyboard_height` is low
by the scale factor on iOS, which would be a Kivy bug to report upstream. The
app logs `Window.size`, `UIScreen.bounds`, `nativeScale`, and the keyboard
height from both sources when the URL field is focused.

---

## Prompt

You are running the `ios-webview` spike on the iOS simulator and recording
what happens. Do not fix the recipe silently: if a variant fails, record the
traceback and move on, then propose the fix in the findings. The findings are
the deliverable; a passing run with no numbers is not.

### Step 0 — environment

```bash
git pull
xcodebuild -version
.venv/bin/kivyforge --version
xcrun simctl list devices available | grep -i iphone | head
```

Record the Xcode version, the simulator model and iOS version you use, and
the kivyforge commit. Prefer a notched model (iPhone 15 or later) so the
safe-area numbers are non-zero.

### Step 1 — lock and run

```bash
cd examples/mobile/ios-webview
../../../.venv/bin/kivyforge lock -p ios
../../../.venv/bin/kivyforge doctor -p ios
../../../.venv/bin/kivyforge run -p ios --simulator
```

Expected: the app launches and shows a status line, a URL field with
`https://kivy.org`, three buttons, and an empty dark area below them. The
log (the `run` console, or `xcrun simctl spawn booted log stream --predicate
'eventMessage CONTAINS "ios-webview"'` in a second terminal) shows the
`Window.size`, `kivy.mobile` and `UIScreen.bounds` lines.

**Record verbatim:** every `ios-webview:` line from launch. Do not round.

### Step 2 — units

From the Step 1 lines, state which holds:

- `Window.size == UIScreen.bounds * nativeScale` → Kivy lays out in
  **pixels** on iOS and `kivy.mobile`'s points need `* get_scale()` for
  layout. This is what kivyforge's `mobile-geometry` guide and examples
  assume.
- `Window.size == UIScreen.bounds` → Kivy lays out in **points**, as
  `kivy/mobile/__init__.py`'s docstring says, and the guide's units advice
  must flip.

If `UIScreen.bounds via pyobjus failed` is logged, that is itself a result
(a struct return through pyobjus); read the bounds another way (the ctypes
variant's `_ObjC.send` with `restype=_CGRect`) or from the simulator model's
known point size, and say which you used.

### Step 3 — the pyobjus variant

Tap **Open (pyobjus)**. Expected: a web view showing kivy.org fills the dark
area (not the whole screen, and not offset into the buttons), with a 4 dp
margin. Tap **Close**: it disappears and Kivy's widgets respond again.

Record: the `web area: kivy px ... -> uikit pt ...` line, the
`pyobjus: rootViewController=...` line, `pyobjus: web view opened` or the
`FAILED` traceback, and a screenshot (`xcrun simctl io booted screenshot
webview-pyobjus.png`). If the frame is wrong (wrong place or size), say by
what factor; that is the units answer from a second angle.

If pyobjus raises on `_get(window, "rootViewController")` or `_get(root_vc,
"view")`, note which form worked when you adjust (attribute vs call); the
guide needs the exact spelling.

### Step 4 — the ctypes variant

Tap **Open (ctypes)**, then **Close**. Same records as Step 3, with a
screenshot `webview-ctypes.png`. If pyobjus passed and ctypes passed, the
guide uses pyobjus. If only ctypes passed, the guide carries ctypes and says
why. If neither passed, stop and report; the fallback is a Swift package.

### Step 5 — keyboard units

Tap into the URL field so the keyboard appears, then dismiss it. Record the
`keyboard:` lines (both sources, scale, `Window.height`). State whether
`Window.keyboard_height` equals `kivy.mobile.get_keyboard_height()` (points,
unscaled) and whether that is consistent with Step 2's answer. If the window
is in pixels and `Window.keyboard_height` is in points, write that up as a
Kivy defect with the numbers; do not patch Kivy here.

### Step 6 — rotation (optional, two minutes)

With a web view open, rotate the simulator (Cmd-Left). Record whether the
web view moves, resizes, or stays. The guide says it does not follow rotation
unless the app resizes it; confirm or correct.

### Deliverable

`docs/design/dev/ios-webview-spike-findings.md`:

1. Environment table (Mac, Xcode, simulator model and iOS, kivyforge commit,
   pyobjus version from the lock).
2. Defects first: anything that failed, with the verbatim traceback.
3. The units answer (Step 2) with the lines that prove it, and the keyboard
   answer (Step 5).
4. Which variant the guide should carry, and the exact code that worked if
   it differs from `src/main.py` (property spelling, framework constant,
   anything).
5. The screenshots, referenced by file name, placed next to the findings.

Then add one row to `docs/design/dev/test-matrix.md` §7 for the run, and
mention in the findings whether `examples/mobile/ios-webview` should stay as
a permanent example (the guide's Verify section could point at it) or be
deleted once the guide carries the recipe.
