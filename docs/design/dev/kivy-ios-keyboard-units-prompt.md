# Agent prompt — fix iOS keyboard height (and safe area) units in Kivy

> **Run this in a checkout of [kivy/kivy](https://github.com/kivy/kivy)**,
> on a branch from `master`. Written 2026-10-20 from kivyforge, where the
> defect was found and measured
> ([`ios-webview-spike-findings.md`](ios-webview-spike-findings.md),
> "Keyboard — a Kivy defect"). Line numbers below are from Kivy master
> `bdac6a6` (2026-10-20); check them against your checkout.
>
> The deliverable is a Kivy pull request. The simulator check needs a Mac with
> Xcode and an iOS simulator; the unit tests do not.

---

## Prompt

You are fixing a units bug in Kivy 3's iOS support. On iOS,
`Window.keyboard_height` and `Window.safe_area` are reported in UIKit
**points**, but Kivy lays out in **pixels** there, so both are too small by the
screen's scale factor (3x on current iPhones). Kivy's own documentation already
says these values are in layout coordinates; the iOS backend does not deliver
that. Android does.

Do not start by changing code. Read the evidence and the code paths below,
reproduce the mismatch, then fix it.

### The evidence

Measured on an iPhone Air simulator (iOS 27.0, `nativeScale` 3.0) with a Kivy
3.0.0.dev wheel whose `kivy/mobile` and `Window` keyboard code is identical to
master `bdac6a6`:

- `Window.size` was `(1260.0, 2736.0)`; `UIScreen.mainScreen.bounds` was
  `420 x 912` points. So the window is in pixels: bounds x 3.
- With the software keyboard on screen, `kivy.mobile.get_keyboard_height()`
  and `Window.keyboard_height` both returned `347.0`. A simulator screenshot
  taken at the same moment is `1260 x 2736` (the same as `Window.size`), and
  the keyboard covers its bottom ~1040 px: `347 x 3 = 1041`.
- `kivy.mobile.get_safe_area()` returned `{'top': 68.0, 'left': 0.0,
  'bottom': 34.0, 'right': 0.0}`: the iPhone Air's insets in points. Padding a
  layout by these values put content under the status bar; padding by them
  x 3 placed it correctly.

### Why it happens

1. The iOS window is created high-density, so Kivy's layout unit is the pixel:
   `kivy/core/window/_window_sdl3.pyx` line 190 sets
   `SDL_WINDOW_HIGH_PIXEL_DENSITY`, and `kivy/core/window/window_sdl3.py`
   (`_update_density`, line 367; touch conversion around line 472) multiplies
   positions by `SDL_GetWindowPixelDensity`.
2. `kivy/mobile/_platform/ios.py` returns UIKit points and says so on purpose.
   Its module docstring (lines 1-10): "All values are returned in UIKit
   *points*, which equal Kivy layout coordinates on iOS (``nativeScale``
   applies only to rasterization, not layout)." Under SDL3 with high pixel
   density, that last claim is false. `get_keyboard_height()` (line 326)
   returns the keyboard frame height in points; `get_safe_area()` (line 184)
   returns `safeAreaInsets` in points.
3. The public contract says layout units. `kivy/mobile/__init__.py` lines
   44-50: `get_keyboard_height()` is "in layout points" and `get_safe_area()`
   is "in layout points". `Window.safe_area`'s docstring
   (`kivy/core/window/__init__.py` line 758) says "All values are in the same
   coordinate system as Kivy layout (UIKit points on iOS)": the parenthesis is
   the wrong part.
4. Android is already correct: `kivy/mobile/_platform/android.py`
   `get_keyboard_height()` (line 392) and `get_safe_area()` (line 413) return
   pixels, which is Kivy's layout unit there.
5. `Window` passes the iOS value through unscaled:
   `_get_kheight` (`kivy/core/window/__init__.py` line 711) returns
   `get_keyboard_height()`, and `_refresh_safe_area` (line 686) assigns
   `get_safe_area()` to `Window.safe_area`.

### What breaks for users

Every consumer of the keyboard height gets a third of the real value on a 3x
iPhone:

- `softinput_mode = "pan"` and `"below_target"`: `update_viewport`
  (line 1817) moves content up `_kheight`, so a focused `TextInput` near the
  bottom stays behind the keyboard.
- `softinput_mode = "scale"` shrinks the viewport by a third of the keyboard;
  `"resize"` (`_get_system_size`, line 791) reports a window too tall.
- Apps padding by `Window.safe_area` draw under the status bar and home
  indicator.

### "Mostly zero" is not a bug — do not chase it

An earlier report also said `Window.keyboard_height` read 0 while
`kivy.mobile` reported a keyboard. That was the reporter's logging: it printed
the height passed to a `subscribe_keyboard_height` callback next to
`Window.keyboard_height` read one frame later, after the keyboard had reported
0 again. `keyboard_height` is an `AliasProperty` whose getter reads the same
live module value. Leave it alone.

### Step 1 — reproduce

On the simulator, run a minimal Kivy 3 app that logs, once the keyboard is up
(focus a `TextInput`, wait a second):

```python
from kivy.core.window import Window
from kivy.mobile import get_keyboard_height, get_safe_area, get_scale
print(Window.size, get_scale(), get_keyboard_height(),
      Window.keyboard_height, get_safe_area())
```

and take `xcrun simctl io booted screenshot kb.png`. Confirm that
`Window.keyboard_height * scale` is the keyboard's height in the screenshot's
pixels. If the simulator shows no software keyboard, a hardware keyboard is
connected: toggle the software keyboard in the simulator's window (Xcode 27:
Device Hub; earlier: Simulator, I/O > Keyboard).

### Step 2 — fix

Fix it in the iOS backend, so `kivy.mobile` keeps one contract across
platforms (layout units) and `Window` needs no platform branch:

- `get_keyboard_height()` and the value passed to `subscribe_keyboard_height`
  callbacks return the height in Kivy layout pixels.
- `get_safe_area()` returns insets in Kivy layout pixels.
- Correct the docstrings that say points equal layout coordinates on iOS:
  `ios.py`'s module docstring and per-function docstrings, and
  `Window.safe_area`'s "(UIKit points on iOS)".

**Choose the factor carefully.** It must be the ratio between UIKit points and
Kivy's window pixels, which is SDL's window pixel density, not necessarily
`UIScreen.nativeScale`. They match on the device measured above (3.0 and 3.0)
but differ on some models (for example, `scale` 3.0 vs `nativeScale` ~2.61 on
an iPhone 8 Plus). Find which one SDL3 uses for the iOS drawable
(`SDL_GetWindowPixelDensity`, or the `UIView`'s `contentScaleFactor`), and
derive the factor from the same source so they cannot drift. Reading
`contentScaleFactor` from the SDL view, or `Window.size[1]` over the window's
bounds height, are both defensible; `get_scale()` alone is not unless you show
it is what SDL uses. Say in the PR which you chose and why.

Keep the keyboard observer's behaviour otherwise the same: same
notifications, 0.0 on hide, callbacks isolated from each other's exceptions.

### Step 3 — tests

`kivy/tests/test_mobile.py` loads `ios.py` in isolation (`_load("ios")`,
class `TestIosPlatform`) without a UIKit runtime. Add tests that drive the
conversion without the Objective-C runtime: for example, factor the
points-to-pixels step into a small function and test it, or patch the
module's scale source and the stored keyboard height. At minimum:

- a keyboard height of 347 pt at factor 3 reads as 1041 from
  `get_keyboard_height()` and is passed as 1041 to subscribers;
- a hide still reads 0.0;
- safe-area insets are scaled on all four sides;
- the Android tests are unchanged and still pass.

Run the full `kivy/tests/test_mobile.py` and `test_window_base.py`.

### Step 4 — verify on the simulator

Repeat Step 1 with the fix. Record verbatim: `Window.size`, the factor,
`get_keyboard_height()`, `Window.keyboard_height`, `get_safe_area()`, and the
keyboard's height measured in the screenshot. Then set
`Window.softinput_mode = "below_target"` with a `TextInput` near the bottom of
the screen, focus it, and screenshot: the field must sit just above the
keyboard. Include both screenshots in the PR.

### Step 5 — the pull request

- Title along the lines of "iOS: report keyboard height and safe area in
  layout pixels".
- Body: the evidence above, the cause, the factor you chose and why, and the
  before/after numbers from Steps 1 and 4.
- **Call it out as a behaviour change.** Apps that worked around the bug by
  multiplying `kivy.mobile` values by `get_scale()` on iOS will now
  double-scale. Kivy 3 is pre-release, so fixing the contract is right, but
  the PR and the changelog must say so in one sentence that a user can act on:
  "On iOS, `kivy.mobile.get_keyboard_height()`, `get_safe_area()` and
  `Window.keyboard_height`/`Window.safe_area` are now in layout pixels; remove
  any `* get_scale()` you added for iOS."

### Do not

- Change Android behaviour or the Android tests' expectations.
- Scale inside `Window._get_kheight` or `_refresh_safe_area` instead of the
  backend. That leaves `kivy.mobile`'s public functions violating their own
  documented contract.
- Touch the 0.5 s `trigger_keyboard_height` debounce; it is unrelated.

---

## After the Kivy fix lands (kivyforge side)

kivyforge currently works around this by multiplying `kivy.mobile`'s iOS
values by `get_scale()`. When a Kivy wheel with the fix is published to the
kivy-mobile-wheels index, remove the iOS workaround everywhere it appears, in
the same change that bumps the locked Kivy for the on-device gate examples.
`git grep "get_scale()" -- examples docs` lists the candidates (on 2026-10-20:
the `mobile-geometry` guide and ten examples); not every hit is the
workaround, since Android values were already pixels, so read each one. Also
update the `get_kheight` row of `ios-module-proposal.md` and the ios-module
guide. Re-run the affected iOS examples on the simulator and record the run in
`test-matrix.md` §7.
