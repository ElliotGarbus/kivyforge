# The kivy-ios `ios` module on kivyforge: migrate, do not shim

**Status:** proposed 2026-10-19. This is the third draft of the same day. The
first proposed a bundled `ios` compatibility package; review dropped
`send_email` from it, then dropped the package. The reasoning for both is kept
below ([Alternatives considered](#alternatives-considered)) and the package
design is in the [appendix](#appendix-the-shim-as-drafted), so it can be
revived if demand appears.

**Origin:** [issue #109](https://github.com/ElliotGarbus/kivyforge/issues/109).
A user building iOS apps with Kivy 3 on kivyforge asked for the `ios` module
that kivy-ios apps import. Their app runs on Kivy 3 without it, but depends on
"most of the functions on `ios`": safe area, web browser, web view, file chooser.
The owner replied that `ios` would be added as a shim and that the docs have a
gap. This note revises the first half of that reply and keeps the second.

It is the iOS counterpart of
[`android-compat-package-proposal.md`](android-compat-package-proposal.md)
(issue #72), and reaches the opposite conclusion for reasons that are specific
to iOS: nothing on the platform needs the module any more, and everything it
did is now in Kivy or the standard library, cross-platform.

## Summary

- **Kivy 3 does not need `ios`.** Its metrics, keyboard height and safe area
  come from `kivy.mobile`, which ships in the Kivy iOS wheel (E1, E3). Kivy
  2.3.1 does import `ios`, but kivyforge does not support Kivy 2.x on iOS (E8).
- **Nothing else needs it either.** None of plyer's 24 iOS facades imports
  `ios` (E5), and the public footprint outside the reporter is one app (E6).
  This is where iOS differs from Android, where Kivy 2.3.1 crashes without
  `android` and plyer imports it everywhere.
- **Every function has a cross-platform replacement.** Four are `kivy.mobile`,
  which also serves Android; one is the standard library's `webbrowser`; the
  web view is fifteen lines of `pyobjus`; the file chooser was never reachable
  from Python and plyer's facade already does the job; mail compose has no
  evidence of use and an aged wrapper (E2, E4, E5).
- **The module's own history says not to own one.** The kivy and kivy-ios
  trackers show it breaking against iOS 16, iOS 18 and an App Store rule,
  with fixes months to a year and a half behind, and Kivy and kivy-ios
  drifting out of step over its API; Kivy moved the geometry into
  `kivy.mobile` to end exactly that (E10).
- **Kivy 3 is already the break.** An app arriving from kivy-ios moves to
  SDL3 and to `kivy.mobile` anyway, and `kivy.mobile` reports UIKit points
  where Kivy lays out in pixels, so its keyboard and safe-area padding is
  re-derived either way (E3). One break, now, is kinder than a shim followed
  by a second break.
- **Decision:** no `ios` module. Ship a migration guide that maps each old
  name to its replacement, and a build-time warning that points at the guide
  when an app still imports `ios`. Reply on the issue with the reasoning.
- **Ship a clear error for Kivy 2.x on iOS first, on its own** (stage 0,
  already in progress).

## Evidence

Everything below was checked on 2026-10-19 unless stated. "Verified" means
read from source or observed; see [What was not verified](#what-was-not-verified).

### E1. Kivy 3 never imports `ios`

Checked in a local Kivy checkout at `bf398019a` (2026-07-31), one commit after
the `71407bc1` pin (2026-07-30) that the kivy-mobile-wheels iOS wheel is built
from (`recipes/PINNED_REFS.toml`, `[ios.kivy]`).

- Searched every `.py` and `.pyx` under `kivy/` for `import ios` and
  `from ios`. **No match.** `kivy/metrics.py` and `kivy/core/window/__init__.py`
  import `get_safe_area`, `get_keyboard_height` and `subscribe_keyboard_height`
  from `kivy.mobile`; `Window.keyboard_height`'s docstring says the iOS value
  "is now sourced from `kivy.mobile`".
- `kivy.mobile.__init__` dispatches on `kivy.utils.platform == 'ios'` to
  `kivy.mobile._platform.ios`, which reads UIKit through `ctypes` and the
  Objective-C runtime "without adding any compiled extension dependency".

The Android proposal's E1 established the same for `android` at the same pin.

### E2. What kivy-ios's `ios` module is

Source: `kivy_ios/recipes/ios/` on kivy-ios `master` at `c722935c`
(2026-10-16). The recipe is a `CythonRecipe` producing `ios.so`, linked against
`MessageUI`, `CoreMotion`, `UIKit`, `WebKit` and `Photos`. The last substantive
changes to the directory were an `openURL` fix (2026-06-05), an iOS 10+ `openURL`
refactor (2026-04-23), and the DPI table (2022-05-13). Kivy's own kivy-ios recipe
depends on it (`_base_depends = ["ios", "pyobjus", "python"]`), which is why
every kivy-ios app has it.

| File | Lines | What it provides |
|---|---|---|
| `ios.pyx` | 258 | The Python API below. At import time it also does `from pyobjus import autoclass, selector, protocol`, builds an `IOSKeyboard` observer with hand-written type encodings, and registers a `webbrowser` backend named `ios`. |
| `ios_utils.m` | 173 | `nativeScale`; a DPI table keyed by `utsname.machine` for iPhone 1 through iPhone 14 and iPad 1 through iPad 11, with a `163 × scale` / `132 × scale` fallback; `safeAreaInsets` of the delegate's window |
| `ios_mail.m` | 108 | `MFMailComposeViewController` with subject, body, one attachment and a delegate that maps the result to a status string. The controller is a current API; the wrapper is not: it presents and dismisses with `presentModalViewController:animated:` and `dismissModalViewControllerAnimated:`, both deprecated since iOS 6, finds the view controller by walking `keyWindow.subviews[0].nextResponder` (`keyWindow` deprecated since iOS 13), never releases the delegate it allocates, and releases the controller while UIKit still presents it. `canSendMail` is true only when the Apple Mail app has an account, so on a phone whose user lives in Gmail or Outlook, and on every simulator, the function reports `"cannotsend"`. |
| `ios_browser.m` | 46 | `openURL:options:completionHandler:`; a `WKWebView` added as a subview of the root view controller's view at a caller-supplied frame, with a 40×40 "X" button whose action is the web view's own `removeFromSuperview` |
| `ios_filechooser.m` | 44 | An Objective-C class `NativeImagePicker` with `getFileName:` and `writeToPNG:`. **No Python binding:** nothing in `ios.pyx` or `ios_wrapper.h` refers to it, so `import ios` never exposed a file chooser. It was reachable only through `pyobjus`'s `autoclass`, and the one plyer facade that could have used it does not (E5). |

Public names in `ios.pyx`, with the C they wrap:

| Name | Signature | Returns |
|---|---|---|
| `get_scale()` | — | `nativeScale`, float |
| `get_dpi()` | — | table lookup or estimate, truncated to int |
| `get_safe_area()` | — | the C struct, which Cython returns as a dict `{"top", "bottom", "right", "left"}` of floats |
| `get_kheight()` | — | `IOSKeyboard.kheight`: `get_scale() × keyboard frame height`, so **pixels**, Kivy's layout unit on iOS (E3) |
| `open_url(url)` | `str` | `None` |
| `IosBrowser` | `.open(url, new=0, autoraise=True)`, `.open_new`, `.open_new_tab` | registered with `webbrowser.register('ios', IosBrowser, None, preferred=True)` |
| `IOSWebView().open(url, x, y, width, height)` and `open_url_wbv(...)` | ints, UIKit coordinates (top-left origin, points) | `None` |
| `send_email(subject, text, mimetype=None, filename=None, filename_alias=None, callback=None)` | `callback(status)` with `"cancelled"`, `"saved"`, `"sent"`, `"failed"`, `"unknown"`, `"cannotsend"` | `1` when the composer was presented; `0` otherwise, after calling `callback("failed")` (no view controller) or `callback("cannotsend")` (no mail account). With `callback=None` those two paths raise `TypeError`. |
| `IOSKeyboard`, `iOSKeyboard` | class and its module-level instance | internal to `get_kheight` |
| `__version__` | — | `(1, 1, 0)` |

### E3. What `kivy.mobile` provides on iOS

From `kivy/mobile/__init__.py` and `kivy/mobile/_platform/ios.py` at E1's commit:

| `kivy.mobile` | Value | Old `ios` equivalent |
|---|---|---|
| `get_scale()` | `nativeScale` of the key window's screen, float; `2.0` on failure | `get_scale()`, same source |
| `get_dpi()` | `163 × scale`, or `132 × scale` when `UIDevice.model` contains "iPad"; float | `get_dpi()`'s fallback branch; the table is gone |
| `get_safe_area()` | `{"top", "left", "bottom", "right"}` of the key window's `safeAreaInsets`, points; all zero on failure | `get_safe_area()`, same keys and source |
| `get_keyboard_height()` | the `UIKeyboardWillChangeFrameNotification` frame height, **points**; `0.0` after `UIKeyboardWillHideNotification` | `get_kheight()`, which multiplied by scale |
| `subscribe_keyboard_height(callback)` | callback on each change | `IOSKeyboard`, which called `Window.trigger_keyboard_height()` |
| `get_density()`, `get_fontscale()` | alias of scale; `1.0` | none |

**Units.** The docstring says values are "UIKit *points*, which equal Kivy
layout coordinates on iOS". The second half is not what kivyforge has
observed. Kivy 3 creates its SDL3 window with `SDL_WINDOW_HIGH_PIXEL_DENSITY`
and takes its size from `SDL_GetWindowSizeInPixels` (`_window_sdl3.pyx`), and
scales touches by the pixel density (`window_sdl3.py`), so Kivy lays out in
**pixels** on iOS, as Kivy 2 did. kivyforge's
[mobile geometry guide](../../guides/guides/cross-platform/mobile-geometry.md)
and its `pyobjus-ball`, `pyobjus-deviceinfo` and `mobile-geometry` examples,
validated on the simulator, all multiply `kivy.mobile`'s insets by
`get_scale()` for that reason. The old `ios.get_kheight()` multiplied by the
scale for the same reason (E2). Two consequences:

- Code moving from `ios` keeps its `× get_scale()` for the keyboard and adds
  one for the safe area; the mapping below says so.
- Kivy's own `Window.keyboard_height` returns `get_keyboard_height()`
  unscaled (`core/window/__init__.py`, `_get_kheight`). **Measured** by the
  spike on 2026-10-19 (`ios-webview-spike-findings.md`): with the keyboard
  up, `kivy.mobile` reported 347 pt and `Window.keyboard_height` read 347,
  in a window 2736 px tall at scale 3, so it is low by the scale factor; and
  it read 0 in 9 of 12 readings while `kivy.mobile` reported a keyboard. Two
  Kivy defects to report upstream; the guide steers around them by using
  `kivy.mobile.get_keyboard_height() * get_scale()` directly.

**Measured** by the same run: `Window.size` was `(1260, 2736)` and
`UIScreen.bounds` `420 × 912` pt at `nativeScale` 3, so the window is in
pixels, and `get_safe_area()` returned a top inset of 68 pt on an iPhone Air
simulator, so the key-window lookup worked there (E10's check).

The same seven names exist on Android, backed by pyjnius, so an app that
reads `kivy.mobile` needs no platform fork between the two.

### E4. What the standard library provides

CPython's `webbrowser.py` (read from the 3.13 stdlib staged by a desktop
example) registers, when `sys.platform == "ios"`, an `IOSBrowser` as the
preferred backend. It builds an `NSURL` and sends `UIApplication`
`openURL:options:completionHandler:`, the non-deprecated form, through
`_ios_support.objc`, a `ctypes` handle on `libobjc` (the same in CPython
`main`, checked 2026-10-19). That detail matters: Apple made the old
`openURL:` return false on iOS 18, which is what broke kivy-ios's `open_url`
for a year and a half (E10). So on kivyforge's Python 3.15,
`webbrowser.open(url)` does what `ios.open_url` did, on every platform and on
current iOS, and the old module's `webbrowser.register('ios', ...)` is
redundant. The owner said as much in the issue.

### E5. What plyer needs on iOS

`plyer/platforms/ios/` on plyer's default branch at `4853b3a` (2026-10-04): 24
facades. **None imports `ios`.** 21 import `pyobjus`; the others are pure
Python (`maps.py` opens URLs with `webbrowser`). Of the features the reporter
named:

- `filechooser.py` presents a `UIImagePickerController` through `pyobjus`
  (`autoclass`, `protocol` for the delegate, `load_framework` for Photos). It
  does not use kivy-ios's `NativeImagePicker`.
- `email.py` opens a `mailto:` URL, which reaches whatever mail app the user
  made the default. No attachment, no completion callback. The modern way to
  hand a file to any mail client (and Messages, AirDrop, Files) is the share
  sheet, `UIActivityViewController`, reachable through `pyobjus`.

So plyer's iOS facades work on kivyforge when `pyobjus` is in the lock, with or
without an `ios` module. Whether they work against Kivy 3's SDL3 window was not
run (the facades read `keyWindow.rootViewController`, which should be SDL's);
see [What was not verified](#what-was-not-verified).

### E6. What the community uses

- The reporter (issue #109): "untils like `get_safe_area`, webbrowser, webview,
  filechoser, etc.. my app depends on most of the functions on `ios` package."
- GitHub code search (default branches; at most 30 results per query, so counts
  are lower bounds): `"import ios" "get_safe_area"` found one app
  (`waverian/benchmarkapp`); `"ios.IOSWebView"` found one, a vendored plyer fork
  with a `social.py` facade; `"from ios import"` returned 30 hits, all unrelated
  projects with a module of the same name; `"ios.get_kheight"` returned only
  copies of Kivy 2.x's `core/window/__init__.py`; `"ios.send_email"` returned
  five hits, all Django projects with an unrelated `ios` module. The public
  footprint is small and the strongest evidence is the reporter's own app,
  which does not name mail.
- Kivy 2.3.1 calls `ios.get_dpi()`, `ios.get_scale()` and `ios.get_kheight()`
  (`metrics.py`, `Window.keyboard_height`), which is why every kivy-ios app had
  the module. Out of scope for kivyforge (E8).

### E7. What kivyforge's docs say today

- `docs/design/platforms/ios/07-recipe-triage.md` lists the `ios` recipe under
  **Deleted recipes**, with the replacements this note reaches. That decision
  stands; what was missing is a user-facing page that says so, with the units
  change and a web view recipe.
- `03-artifact-distribution-ios.md` still names "the iOS support package" among
  the wheels kivyforge consumes. No such package exists; stale wording from
  before `kivy.mobile`.
- The user guides (`docs/guides/guides/ios/`, `cross-platform/migrate.md`,
  `cross-platform/mobile-geometry.md`) never mention the `ios` module, so a
  kivy-ios user has nothing that says it is gone or what replaces it. The
  migration guide's iOS section is one paragraph about recipes.

### E8. Kivy 2.x on iOS is unsupported, and nothing says so

kivyforge supports Kivy 3 only on iOS (`kivy-mobile-wheels/README.md`, "Kivy
2.3.1 on iOS is deliberately out of scope"). The index serves no 2.x iOS wheel,
so a `kivy<3` requirement makes `lock -p ios` fail inside pip's resolver, with
pip's message rather than kivyforge's. `platforms/ios/lock/` has no Kivy
version check (searched for "kivy"). The owner noted this in the issue and said
a clear error would be added. It is in progress as stage 0.

### E9. The web view in `pyobjus`

The one function with no drop-in replacement is the web view overlay. The
spike `examples/mobile/ios-webview`, driven by
[`ios-webview-spike-prompt.md`](ios-webview-spike-prompt.md), ran on an
iPhone Air simulator (iOS 27.0, Xcode 27.0, pyobjus 1.2.4) on 2026-10-19;
[`ios-webview-spike-findings.md`](ios-webview-spike-findings.md) has the
verbatim log. The recipe as first sketched, pure pyobjus, failed twice over:

- **`pyobjus.dylib_manager.load_framework` is a silent no-op on iOS.** It
  calls `NSBundle.bundleWithPath_` with the macOS framework path, gets nil,
  and `load()` on nil raises nothing. `autoclass("WKWebView")` then fails
  with `Unable to find class b'WKWebView'`. Loading the framework binary
  with `ctypes.CDLL` (dyld) works on the simulator and should on a device.
- **pyobjus 1.2.4 passes floating-point arguments unreliably on arm64.**
  `initWithFrame_(NSRect(...))` produced a 0×0 view on one launch and the
  right frame on the next; a `CGFloat` constraint constant arrived as 0.0.
  Object, string and integer arguments, and struct *returns*, were correct
  every time. Setting the frame with `setFrame:` through `objc_msgSend`
  (ctypes, using `get_address()` for the pyobjus object) worked on every
  launch.

What worked, and what the guide carries: pyobjus for objects and strings,
plus about twenty-five lines of ctypes to load WebKit and set the frame. A
pure-ctypes variant also worked but is longer for no gain. Properties:
`keyWindow`, `rootViewController` and `view` came back from pyobjus
sometimes as values and sometimes as callables, so the recipe reads them
through a small helper that accepts either. The run also confirmed the
units in E3 from the other side: a Kivy rectangle of
`(60, 162, 1140, 1842)` px mapped to `(20, 244, 380, 614)` pt put the view
exactly over the Kivy area, and `Close` (`removeFromSuperview`) removed it.
A typed URL without a scheme loads nothing silently (`NSURL` parses it as a
relative path); the recipe adds `https://`.

### E10. What the kivy and kivy-ios trackers show

Searched both repositories' issues and pull requests on 2026-10-19 for the
module's name and each of its functions. Nine threads are about the module,
2016 to 2026:

| Thread | What happened | What it tells us |
|---|---|---|
| [kivy-ios#194](https://github.com/kivy/kivy-ios/pull/194) (2016) | `get_kheight` added for `softinput_mode`. Users then hit `'module' object has no attribute 'get_kheight'` because their Kivy and kivy-ios had moved separately. | Version skew between Kivy and a packaging-side module was the chronic failure mode. |
| [kivy-ios#389](https://github.com/kivy/kivy-ios/issues/389) (2019) | Apple rejected apps (ITMS-90809): `ios.pyx`'s web view used `UIWebView`. Replaced with `WKWebView`. | The web view overlay is App Store compliance surface for whoever ships it. |
| [kivy-ios#404](https://github.com/kivy/kivy-ios/pull/404) (2019) | `get_safe_area` added "for adding paddings in kv user interfaces on notched devices". | The need `Window.safe_area` now serves. |
| [kivy-ios#790](https://github.com/kivy/kivy-ios/pull/790) (2023) | `get_safe_area` crashed on iOS 16 reading `windows[0]`. Fixed by using the app delegate's window. | The key-window lookup is fragile across iOS releases (note below). |
| [kivy-ios#953](https://github.com/kivy/kivy-ios/issues/953) (opened 2024-12, fixed 2026-04 and 2026-06) | On iOS 18 Apple's `openURL:` returns false, so `ios.open_url`, and `webbrowser.open` through the `ios` backend, did nothing. Users pasted pyobjus workarounds of varying quality for seventeen months. | The module rotted against the OS and the fix lagged. CPython's backend sends the modern selector (E4). |
| [kivy-ios#313](https://github.com/kivy/kivy-ios/issues/313) (2018), [#948](https://github.com/kivy/kivy-ios/issues/948) (2024) | Apps crashed on a bytes-versus-str platform check in pyobjus; `ios.pyx` failed to build under Cython 3. | A compiled module is a build liability. Not kivyforge's problem, by design. |
| [kivy#9327](https://github.com/kivy/kivy/issues/9327), [#9331](https://github.com/kivy/kivy/pull/9331) (2026) | `kivy.mobile` introduced so that build tools are "collectors of files, not owners of runtimes". `get_kheight()` removed as "internal convention, never documented as public API". The DPI table dropped because it "topped out at iPhone 13 / 2021 iPad". | Kivy has already ruled on two of the names. A kivyforge shim would recreate the skew surface that issue was opened to end. |

Two things to carry forward:

- **A check on `kivy.mobile`.** Its iOS `_key_window` uses `keyWindow`, then
  `windows.firstObject`: the pair that failed in #790. It is wrapped in
  `try`/`except`, so the failure mode is all-zero safe-area insets rather
  than a crash, which on a notched phone is a silent regression. The
  verification plan has one simulator check for it; if it returns zeros,
  the fix is upstream, using the delegate's window as #790 did.
- **The guard pattern in the wild** is `if platform == 'ios': import ios`
  (seen in #953). The build-time warning's scan matches indented imports, so
  it catches that form.

## What was not verified

- The web view spike has run on the simulator (E9), not on a device. The
  `dlopen` of WebKit and the frame call are expected to behave the same on a
  device; not shown.
- The condensed recipe below is the spike's working code shortened for the
  guide; the guide's own copy must be run once before it is published.
- plyer's iOS facades were read, not run, on kivyforge.
- Whether a Kivy 3 app's `keyWindow.rootViewController.view` behaves the same
  under SDL3's UIKit view controller as it did under SDL2's. Both are SDL's
  `SDL_uikitviewcontroller`; the SDL3 one was not inspected.
- The reporter's app was not seen; "most of the functions" is their summary.
- GitHub code search is incomplete; counts are lower bounds.
- The Kivy 2.x lock failure (E8) is inferred from the index's contents, not
  reproduced on a Mac.

## Decisions (2026-10-19)

1. **No `ios` module.** kivyforge does not provide, vendor or stub the kivy-ios
   `ios` module. The replacements are in Kivy 3 and the standard library, they
   are cross-platform, and Kivy 3 is already the point where this code changes.
2. **A migration guide** maps every public name of the old module to its
   replacement, states the units change, and gives a `pyobjus` web view
   recipe. It is the deliverable the issue asked for, under a different name.
3. **A build-time signpost.** `kivyforge build -p ios` and `doctor -p ios`
   warn when a file under `app_dir` imports `ios`, naming the file and the
   guide, so the failure explains itself before the app reaches the simulator.
   A warning, not an error: the app may guard the import and run fine.
4. **Kivy 2.x on iOS gets its own error first** (stage 0; in progress).
5. **Reply on the issue** with the reasoning and the mapping for the four
   features the reporter named, since the earlier comment promised a shim.
6. **Mail compose is not provided and not recommended.** The guide points at
   plyer's `email` for subject and body and at the share sheet for a file.
7. **Not decided here:** whether kivyforge should add `pyobjus` to every iOS
   lock, as it adds pyjnius to every Android lock. The web view recipe and
   plyer both need it, so the question is live; it is a separate note.

## Alternatives considered

### A bundled compatibility package (the first draft)

Rejected 2026-10-19. The design is in the [appendix](#appendix-the-shim-as-drafted).

- It solves a problem the platform does not have. On Android the package was
  forced by Kivy 2.3.1's crashes and plyer's imports; on iOS neither applies,
  and the known demand is one app mid-port to Kivy 3 (E5, E6).
- "Runs unchanged" would be thin. A shim could reproduce `get_kheight()`
  (points × scale) and `get_safe_area()`, but not `get_dpi()`'s device table,
  and the web view and browser are the parts that rotted (E10). The app still
  moves to SDL3 and still adds `pyobjus` for anything beyond the shim. It
  would save a handful of renamed calls.
- It points people the wrong way. `ios.get_safe_area()` is iOS-only by name;
  `kivy.mobile.get_safe_area()` is the same call on Android. Keeping the old
  names alive keeps apps writing a platform fork that Kivy 3 removed.
- Its upkeep is real, not hypothetical. E10 lists what the module needed in
  kivy-ios: a store-rule rewrite, an iOS 16 crash fix, an iOS 18 fix that took
  seventeen months, and a decade of version skew. Owning a copy means owning
  that.
- Its cost is in delivery, not code. The Python would be about 180 lines; the
  plumbing is a new bundle directory, a run-script and `PYTHONPATH`
  change, byte-compile and strip handling, two conflict codes with their lock
  and build checks, an example and a CI gate, all kept for as long as
  kivyforge exists. The guide is needed under every option, so all of that is
  additional.

### A deprecated shim pointing at the guide

Rejected the same day. It pays nearly the whole delivery cost of the package,
because the plumbing is the expensive part, and then promises a second break
when it is removed. If the module is going away, the right moment is now, while
the Kivy 3 port is open on the user's desk. A `DeprecationWarning` at import is
also the least visible signal available on a phone; the build-time warning
(decision 3) reaches the developer on the Mac, before the app is installed.

### A one-file `ios.py` that raises `ImportError` with a pointer

Considered as the signpost instead of the build warning, dropped into
`pip-deps` at collect time. It needs no conflict checks, since a user's own
module sits ahead of `pip-deps` and wins. It was not chosen because it fires at
runtime on the device, after a build the warning could have annotated; because
it would be the one file kivyforge writes into a directory that is otherwise
pip's output, per slice; and because the common guarded form,
`try: import ios except ImportError:`, swallows it. It remains the cheapest
fallback if the static scan turns out to miss cases that matter.

## The migration guide

`docs/guides/guides/ios/ios-module.md`, "Replace the kivy-ios ios module", in
the voice of the other guides (what it is, before you begin, the mapping, each
non-trivial replacement, verify, what's next). Its `sources:` front matter
lists this note. Added to `mkdocs.yml` under iOS, and linked from
`cross-platform/migrate.md`'s iOS section, `cross-platform/mobile-geometry.md`
and `07-recipe-triage.md`.

### The mapping

| kivy-ios `ios` | Replacement | Note |
|---|---|---|
| `get_scale()` | `kivy.mobile.get_scale()` | same value |
| `get_dpi()` | `kivy.mobile.get_dpi()` | float, and an estimate (`163 × scale`, `132 × scale` on iPad) rather than a per-model table, which Kivy dropped because it "topped out at iPhone 13" (kivy#9331); this is also what `Metrics.dpi` reports on Kivy 3 |
| `get_safe_area()` | `kivy.mobile.get_safe_area()`, or bind `Window.safe_area` | same dict, same keys, same unit (UIKit points). Multiply by `get_scale()` for Kivy pixels, as the mobile geometry guide shows; the old function needed the same |
| `get_kheight()` | `kivy.mobile.get_keyboard_height() * kivy.mobile.get_scale()` | the old function returned **pixels** (it multiplied by the scale internally); `kivy.mobile` returns **points**, so the caller multiplies. Do not read `Window.keyboard_height` for this on iOS yet: measured, it is the unscaled points value and reads 0 most of the time the keyboard is up (E3); a Kivy defect to report. Kivy removed `get_kheight` itself as "internal convention, never documented as public API" (kivy#9331) |
| `IOSKeyboard`, `iOSKeyboard` | `kivy.mobile.subscribe_keyboard_height(callback)` | Kivy's `Window` already subscribes; most apps need nothing |
| `open_url(url)`, `IosBrowser` | `webbrowser.open(url)` | the standard library registers the iOS backend itself; works on every platform |
| `IOSWebView().open(url, x, y, width, height)`, `open_url_wbv(...)` | `WKWebView` through `pyobjus`, with WebKit loaded and the frame set through ctypes (recipe below, verified in the spike) | add `pyobjus` to `[project].dependencies`. The frame is UIKit points with a top-left origin, as before: from a Kivy rectangle, divide by `get_scale()` and take `y` from the top |
| `send_email(...)` | plyer's `email` facade (`mailto:`, any default mail app) for subject and body; `UIActivityViewController` through `pyobjus` for a file | the old function worked only where the Apple Mail app has an account |
| the file chooser | plyer's `filechooser` facade (needs `pyobjus`), or `PHPickerViewController` through `pyobjus` | the old module never exposed one to Python |
| `import ios` in cross-platform code | `from kivy.utils import platform`, then `if platform in ("ios", "android"): import kivy.mobile` | `kivy.mobile` raises `ImportError` on desktop by design |

### The web view recipe

The spike's working code (`examples/mobile/ios-webview/src/main.py`, the
pyobjus variant), condensed for the guide. The two ctypes pieces are there
because of the two pyobjus defects in E9; the comments say which.

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

Closing it from Python replaces the old module's hard-coded "X" button, which
is why the guide prefers this over reproducing the overlay exactly. The guide
also says the view does not follow rotation unless the app resizes it (the
spike app is portrait-only, so this was not exercised), and that UIKit calls
must come from the main thread, where Kivy runs.

## The signpost

- **What it scans.** Every `.py` under `app_dir`, for a line matching
  `^\s*(import|from)\s+ios(\s|\.|$)`. A match inside a string or comment is a
  false positive the warning tolerates; it is a warning.
- **When it is quiet.** When `app_dir` itself contains `ios.py` or an `ios/`
  package, the import is the app's own module and nothing is said.
- **Where it runs.** `doctor -p ios` as a WARN check next to
  `check_app_native_binaries` (also an `app_dir` scan), and `build -p ios` as a
  warning diagnostic on an `ok: true` run, so `--json` consumers see it under
  `diagnostics`. One code, `KF-IOS-LEGACY-IOS-MODULE`, in
  `kivyforge/report/diagnostics.py`. Message: `<file>:<line>` imports the
  kivy-ios `ios` module, which kivyforge does not provide; see the guide. The
  message carries the guide's path; the code is the contract.
- **Not scanned:** dependencies. A third-party package importing `ios` was not
  found (E5, E6); if one appears, the runtime `ImportError` still names the
  module, and the guide is one search away.
- **Tests:** hermetic, in `tests/platforms/ios/test_doctor.py` and the build
  tests: a match, a guarded match (still warns), the app's own `ios.py`
  (quiet), and the human and `--json` output.

## Docs changes

- The guide above, in `mkdocs.yml`.
- `cross-platform/migrate.md`: the iOS section gains a paragraph that the
  `ios` module is not provided, with the link and the units note.
- `cross-platform/mobile-geometry.md`: one line that `kivy.mobile` replaces
  `ios.get_safe_area()` and `ios.get_kheight()`, with the link.
- `07-recipe-triage.md`: the `ios` row links to the guide. `03-artifact-distribution-ios.md`:
  remove "the iOS support package" from the wheel list.
- `guides/ios/pyobjus.md`: note that plyer's iOS facades need `pyobjus`.
- `CHANGELOG.md` under `[Unreleased]`: the warning, with its code, and the
  guide; no migration note is needed because no behaviour changes.

## Verification plan

- Hermetic tests for the signpost (above).
- **Done 2026-10-19:** the spike, `examples/mobile/ios-webview`, on the
  simulator, following
  [`ios-webview-spike-prompt.md`](ios-webview-spike-prompt.md); findings in
  [`ios-webview-spike-findings.md`](ios-webview-spike-findings.md), row in
  `test-matrix.md` §7. It settled the variant (pyobjus plus ctypes for the
  load and the frame), the units (pixels), and the `Window.keyboard_height`
  defect (E3, E9). The example stays as a permanent one: it is the only code
  in the repo that exercises both pyobjus failure modes, and the guide's
  Verify section can point at it. Not a CI gate.
- **Done, same run:** `kivy.mobile.get_safe_area()["top"]` was 68 pt on an
  iPhone Air simulator, so the key-window lookup (E10) worked there. A
  device and a landscape app remain unchecked.
- The guide's own copy of the recipe, run once on the simulator before the
  guide is published (it is the spike's code condensed, not the spike's code).
- A plyer smoke on the simulator, once: `pyobjus` in the lock, import
  `plyer.platforms.ios.filechooser` and open the picker. It turns E5's reading
  into an observation and tells the guide what to say about the file chooser.

## Staged path

### Stage 0: a clear error for Kivy 2.x on iOS (in progress, own session)

`KF-IOS-KIVY-UNSUPPORTED`, exit 1, from `lock -p ios` when the `kivy`
requirement admits no 3.x release or the resolved version is below
`3.0.0.dev0`, and from `build -p ios` on such a lock. Tests, a line in the
iOS configure guide and the migration guide, a changelog entry.

### Stage 1: the guide and the signpost (this repo)

1. Done 2026-10-19: the spike ran, the findings are in
   `ios-webview-spike-findings.md`, and E3, E9, the mapping and the recipe
   above are corrected from them.
2. Write the guide and the doc changes above.
3. The signpost check, its code, and its tests.
4. `CHANGELOG.md`.
5. Reply on #109 (decision 5) and close it when the guide is published.

### Stage 2: only if demand appears

If several apps turn out to need the old names, the appendix is the design,
and [Alternatives considered](#alternatives-considered) lists what delivering
it costs. The bar is real apps, not the possibility of them.

## Risks and open questions

1. **The owner's earlier comment promised a shim.** The issue reply (decision
   5) owns the change of direction and gives the reporter the four mappings
   they need; their port is one import change, deleting browser code, the web
   view recipe, and plyer for the file chooser, which they already use.
2. **The recipe rests on two pyobjus defects staying as they are** (E9):
   `load_framework` doing nothing on iOS, and floating-point arguments
   arriving wrong. Both are worked around with ctypes, which keeps working
   whether or not pyobjus is fixed. Both should be reported to kivy/pyobjus
   with the spike's log lines; the pyobjus iOS pin in kivy-mobile-wheels is
   from 2025-12 and has no upstream iOS CI.
   **Also upstream:** `Window.keyboard_height` on iOS is unscaled and mostly
   0 (E3), to report to kivy/kivy with the findings' numbers. Until it is
   fixed the guide tells apps to read `kivy.mobile` directly.
3. **The units note already posted on #109 is inverted.** The reply said
   `get_kheight` moves to points and that dividing by the scale must stop;
   E3 shows Kivy lays out in pixels and the caller multiplies instead. A
   correcting comment is needed, and the guide must not repeat the error.
4. **`pyobjus` is not in every iOS lock.** The web view and plyer need it; the
   guide says to add it. Whether kivyforge should add it for everyone is
   decision 7's open question.
5. **The static scan has false positives and misses dependencies.** Accepted
   for a warning. The `ImportError` stub is the fallback if misses matter.
6. **plyer under SDL3** is unmeasured. The smoke test answers it; the guide
   should not claim the file chooser works until it has run.

## Related, not decided here

- **`pyobjus` in every iOS lock** (decision 7).
- **plyer on Kivy 3 iOS.** A findings doc after the smoke test.
- **Docs that say "open Simulator".** Xcode 27 ships Device Hub instead of
  Simulator.app (findings, defect 4); `kivyforge run -p ios --simulator`
  still works. Any guide wording that names Simulator.app wants the new name.
- **Sharing a file from a Kivy app** (the share sheet through `pyobjus`) is
  the answer this note gives to mail-with-attachment, and it deserves a short
  example under `examples/mobile/` once `pyobjus` has been exercised there.
- **Per-package index pinning**, carried over from the Android proposal's list.

## References

- Issue #109; issue #72 and
  [`android-compat-package-proposal.md`](android-compat-package-proposal.md)
- kivy-ios: `kivy_ios/recipes/ios/` at `c722935c` (2026-10-16);
  `kivy_ios/recipes/kivy/__init__.py` (`_base_depends`)
- Kivy: `kivy/mobile/__init__.py`, `kivy/mobile/_platform/ios.py`,
  `kivy/core/window/__init__.py` at `bf398019a`; kivy/kivy#9331 (`kivy.mobile`)
- CPython `Lib/webbrowser.py` ("Platform support for iOS"), `Lib/_ios_support.py`
- Tracker threads (E10): kivy-ios#194, #313, #389, #404, #790, #948, #953;
  kivy#9327, #9331
- plyer: `plyer/platforms/ios/` at `4853b3a`
- kivyforge: `platforms/ios/templates/kivyforge_bootstrap.m`,
  `platforms/ios/buildsettings.py`, `platforms/ios/doctor.py`
  (`check_app_native_binaries`), `platforms/android/stage/conflicts.py`
- `docs/design/platforms/ios/07-recipe-triage.md`,
  `03-artifact-distribution-ios.md`, `01-pyproject-ios.md` §"dynamic loading"
- kivy-mobile-wheels: `README.md`, `recipes/PINNED_REFS.toml`

## Appendix: the shim as drafted

The first draft of this note, kept in outline so it can be revived without
redoing the analysis.

- **Shape.** A pure-Python `ios` package under
  `kivyforge/platforms/ios/templates/ios_pkg/`, about 180 lines: `__init__.py`
  with the delegating names, `_objc.py` as a `ctypes` seam over the
  Objective-C runtime (its own copy of what `kivy.mobile._platform.ios` has
  privately), `_webview.py`. `get_scale`, `get_dpi`, `get_safe_area` and
  `get_kheight` delegate to `kivy.mobile`; `open_url` and `IosBrowser` to
  `webbrowser`; `IOSWebView` reimplements the overlay with `ctypes`;
  `send_email` a stub that raises, naming the replacements; `__version__`
  `(2, 0, 0)`. No `pyobjus` dependency; `kivy.mobile` imported inside the
  functions. `__all__` pinned by a test.
- **Units.** Points throughout, so `get_kheight()` unscaled and `get_dpi()`
  the estimate. The one behaviour change, and the reason the shim could not
  claim compatibility.
- **Delivery.** Staged into `<app>-ios/bootstrap/` on every build; rsynced
  into the bundle by the Build Python run script next to `pip-deps`;
  byte-compiled and stripped under `build_settings`; `PYTHONPATH` becomes
  `stdlib:lib-dynload:bootstrap:app`. Conflicts are errors:
  `KF-IOS-DEPENDENCY-CONFLICT` at lock and build for a distribution providing
  a top-level `ios`, `KF-IOS-APP-CONFLICT` at build for `ios.py`, `ios/` or
  `ios.*.so` in `app_dir`, sharing a generalised `conflicts.py` with Android.
- **Open technical point.** Passing `CGRect` by value through `ctypes` to
  `initWithFrame:` (an arm64 HFA, expected to work through libffi); a
  simulator spike was the first implementation step, with `pyobjus` at call
  time as the fallback.
- **Gate.** An `examples/mobile/ios-package` example in the `ios_simulator`
  CI job logging one line per check; no device gate once mail was dropped.
