# Follow-up: move the remaining pyobjus examples to Rubicon-ObjC

> **DONE 2026-11-01**, Simulator only. All five examples use Rubicon-ObjC;
> `pyobjus-ball` and `pyobjus-deviceinfo` are now `rubicon-ball` and
> `rubicon-deviceinfo`. `rubicon-ball` took option (b): no ctypes left. The
> new guide is `docs/guides/guides/ios/rubicon.md`; `pyobjus.md` is now "Use
> pyobjus"; `ios-webview` dropped its pyobjus and ctypes variants. Results:
> test-matrix section 7, 2026-11-01. Still open: the device checks
> (`ios-rubicon-examples`, `ios-lifecycle-hook-rubicon`), and whether the
> stale pyobjus framework left by an incremental build is a kivyforge bug
> (`clean` was run before every build here, so this pass did not re-test it).
> The list below is kept as the plan it was.

Raised 2026-10-31 on `swift-bridge-rubicon`, after `swift-bridge` was
restructured around Rubicon-ObjC (test-matrix §7, 2026-10-31 rows). Five
examples still use pyobjus. None tracks its lock, so re-locking them is free.

## Policy

Rubicon-ObjC is **the** Python-to-Objective-C bridge the docs and examples
present. pyobjus stays supported, as an alternative and as a dependency other
packages bring in (plyer's iOS facades import it), but it is never the
default a reader meets first.

In practice:

- Examples use Rubicon only. Their code and READMEs do not offer pyobjus.
- A guide shows Rubicon in the main path. Where pyobjus differs in a way a
  reader with an existing pyobjus app needs, the guide ends with a short
  "Use pyobjus instead" section, as `swift.md` already does.
- Navigation and "Before you begin" links point at the Rubicon page first.

Every item below is unverified until it has a dated `test-matrix.md` §7 row.
Where an example has device results today, the README must not claim them
for the Rubicon version until they are re-run.

## Per example

Ordered easiest first.

### 1. `keychain-spm`

- **pyobjus use:** `autoclass("KeychainBridge")`; three class methods with
  `String`/`Bool` signatures; `_objc_str()` helper for the `NSString` result.
- **Change:** `ObjCClass("KeychainBridge")`, `str()` for the result, drop
  `_objc_str()`. Dependency `pyobjus` becomes `rubicon-objc`.
- **Also edit:** `README.md` (diagram, file table, prerequisites say "Kivy +
  pyobjus wheels"), `pyproject.toml` comments, comments in
  `swift-shims/Package.swift` and `KeychainBridge.swift` that say "so pyobjus
  can call it". `swift-bridge/README.md` links here.
- **Guides:** `swift-packages.md` (line 20, line 91 point at pyobjus for the
  shim), `pyobjus.md` (uses this example's selector for its mapping example).
- **Verify:** Simulator; device if it was previously device-checked.

### 2. `ios-lifecycle-hook`

- **pyobjus use:** `autoclass("LifecycleHook")`; five class methods; events
  arrive as one JSON string; `_objc_str()` helper.
- **Change:** as for `keychain-spm`. The Objective-C package and the JSON
  queue stay; Python starts too late for either to move.
- **Also edit:** `README.md` prerequisites (line 34), `pyproject.toml`
  dependency comment, `LifecycleHook.h` doc comment (`autoclass`).
- **Guides:** `lifecycle-hooks.md` "Before you begin" links `pyobjus.md`;
  point it at the new Rubicon page (see Cross-cutting).
- **Verify:** Simulator rows of the README's "Try it" table. The README's
  "What was verified" (push token, notification taps, cold launch, refresh
  task on an iOS 27 iPhone) needs a new device pass or a note that it was
  pyobjus.

### 3. `pyobjus-deviceinfo`

- **pyobjus use:** `autoclass("UIDevice")`, `autoclass("NSProcessInfo")`,
  properties read as attributes, one setter, `_nsstr()` helper.
- **Change:** Rubicon reads properties as attributes too, so this is close
  to mechanical. The docstring's explanation of pyobjus property handling
  goes.
- **Decide:** rename (`rubicon-deviceinfo`?). A rename changes the
  directory, `name`, `display_name`, `bundle_id` and `.gitignore`.
- **Also edit:** `examples/run-examples.sh` default list,
  top-level `README.md` (lines 397-400), `pyjnius-deviceinfo/README.md` and
  its `main.py` docstring (call it the iOS counterpart by name).
- **Guides:** `pyobjus.md` is built on this example (`sources:` front
  matter, the platform-check snippet).

### 4. `pyobjus-ball`

- **pyobjus use:** none at runtime. It declares the dependency but every
  native call is ctypes over `objc_msgSend`, because pyobjus cannot decode
  `CMAcceleration` (struct of doubles, kivy/pyobjus#148) and raised spurious
  `AttributeError` on `UIScreen`.
- **Change:** two options. (a) Keep it ctypes-only and just drop the
  dependency and the pyobjus framing. (b) Rewrite the ctypes wrapper in
  Rubicon, which builds struct types from the method's type encoding and
  should return `CMAcceleration` directly. (b) removes about 60 lines of
  `objc_msgSend` casts but is unverified on iOS.
- **Decide:** (a) or (b), and the rename (as for deviceinfo).
- **Also edit:** `run-examples.sh`, top-level `README.md` (line 397).

### 5. `ios-webview`

- **pyobjus use:** the spike compares a pyobjus variant with a pure-ctypes
  variant. pyobjus needed ctypes for WebKit loading (`load_framework` is a
  no-op on iOS, kivy/pyobjus#158) and for `setFrame:` (`CGRect` by value
  corrupts the heap, kivy/pyobjus#90), plus a `_get()` helper because
  pyobjus exposes some selectors as properties and some as methods.
- **Change:** replace variant A with Rubicon. To check: Rubicon passes
  `CGRect` by value natively (would drop the `setFrame:` workaround);
  whether `rubicon.objc.runtime.load_library("WebKit")` finds the framework
  on iOS, or the `ctypes.CDLL` load stays; `_get()` should go, since Rubicon
  resolves properties and methods itself.
- **Decide:** keep variant B (ctypes) as the comparison, or drop the
  two-variant shape now that it was a spike.
- **Guides:** `ios-module.md` carries this example's code as its web-view
  recipe (lines 81-125) and mentions the `Got dlopen error on Foundation`
  log line and the **Open (pyobjus)** button. Its table also lists
  `send_email` and the file chooser through pyobjus.
- **Design docs:** `ios-webview-spike-findings.md` stays as history; add an
  addendum rather than editing the findings.

## Cross-cutting

- **A new Rubicon guide becomes the primary page.** "Call iOS APIs with
  Rubicon-ObjC": adding the dependency, the platform-check import, calling
  system classes (built on the renamed deviceinfo example) and an `@objc`
  shim, and Rubicon's own pitfalls on iOS. `swift.md`'s "Add Rubicon-ObjC"
  section is the starting point; `swift.md` then links to the new page
  instead of carrying the setup itself.
- **`pyobjus.md` becomes the alternative.** Retitle it along the lines of
  "Use pyobjus", open with when you would (an existing pyobjus app, plyer's
  iOS facades) and a link to the Rubicon page, and keep its defects table:
  that is the reason the page still earns its place. Its `sources:` front
  matter points at `pyobjus-deviceinfo`, which will no longer use pyobjus;
  either cite the defect findings instead or keep one small pyobjus snippet
  that is not tied to an example.
- **`mkdocs.yml` nav.** Today "Call iOS APIs with pyobjus" is the last iOS
  entry (line 105), after `swift.md`. Put the Rubicon page where a reader
  meets it before `swift-packages.md`, `swift.md` and `lifecycle-hooks.md`;
  move the pyobjus page after them.
- **Re-point inbound links to the Rubicon page.** `migrate.md:54`,
  `run.md:91`, `ios-module.md` (lines 25-26, 217), `lifecycle-hooks.md:25`,
  `swift-packages.md` (lines 20, 91). `ios-module.md`'s table keeps pyobjus
  only where it is plyer's requirement (the file chooser row), worded as
  plyer's dependency rather than a recommendation.
- **Top-level `README.md`.** The examples list (lines 397-400) describes
  both pyobjus examples as calling iOS "via pyobjus"; re-describe after the
  renames. If the README has a bridge recommendation anywhere, make it
  Rubicon.
- **Wheels and index text.** rubicon-objc is pure Python from PyPI and needs
  no index. `README.md:140-144` and `runtimes-and-wheels.md:63` list pyobjus
  among the first-party iOS wheels, which stays true; add a line that
  Rubicon comes from PyPI so a reader does not conclude the bridge needs the
  index. `kivyforge/cli/init_writer.py:257` (`init`'s comment "first-party
  iOS wheels for kivy and pyobjus") and the resolver hint at
  `kivyforge/platforms/ios/lock/resolver.py:361` stay as they are: they
  describe what the index serves, not what to use. Check that any `init`
  test pinning that comment still passes if it is reworded.
- **Stale framework in incremental builds.** The swift-bridge restructure
  found that an incremental `build -p ios` after removing pyobjus left
  `Frameworks/pyobjus.pyobjus.framework` in the `.app` (test-matrix §7,
  2026-10-31). Run `kivyforge clean` before each re-verification, and decide
  whether that leftover is a kivyforge bug to fix separately.
- **CHANGELOG.** One `[Unreleased]` entry: Rubicon-ObjC is now the
  documented bridge, pyobjus remains supported, and the example renames,
  with the note that a renamed example installs as a new app (new
  `bundle_id`).
- **Hardware checklist.** None of these examples has an entry in
  `hardware-checklist.toml`. Add device items for `ios-lifecycle-hook` (push,
  background task) and `keychain-spm` alongside `ios-swift-bridge-rubicon`.
