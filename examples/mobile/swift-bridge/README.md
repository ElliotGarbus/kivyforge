# Swift bridge — call Swift from Python with an `@objc` shim

This example calls Swift code from a Kivy app on iOS. The Swift code is a
small local package, `swift-shims/`, whose classes are marked `@objc`, so
[Rubicon-ObjC](https://github.com/beeware/rubicon-objc) can find them by name
and call them. The example covers the four things an app usually needs from
Swift:

- an object with state: initialisers, properties and methods;
- collections in both directions, and a method that `throws`;
- `async` work, through a Python completion handler, or through a job that
  Python polls from Kivy's `Clock` when the work reports progress and can be
  cancelled;
- a delegate protocol declared in Swift and implemented in Python, including
  a method whose return value Swift reads.

The user guide, [Call Swift from Python](../../../docs/guides/guides/ios/swift.md),
walks through each pattern and the rules for each, and says what changes if
your app calls the shim with pyobjus instead.
[`keychain-spm`](../keychain-spm/) shows a shim like this one wrapping a
remote Swift package.

## What's here

| Path | Purpose |
|------|---------|
| `pyproject.toml` | App config; declares the shim under `[tool.kivy.ios.native.swift_packages]` |
| `swift-shims/Package.swift` | Local package, one Swift target, a dynamic product |
| `swift-shims/Sources/SwiftBridge/Notebook.swift` | `SBNotebook`: initialisers, properties, collections, `throws` |
| `swift-shims/Sources/SwiftBridge/Job.swift` | `SBWork`: `async` methods with completion handlers, and `SBJob` for work that Python polls |
| `swift-shims/Sources/SwiftBridge/Metronome.swift` | `SBMetronome` and the `SBMetronomeDelegate` protocol |
| `src/demos.py` | The Python side of each pattern |
| `src/main.py` | The UI: a button per demo and a log |

## Prerequisites

- macOS with Xcode, and kivyforge installed from this repo
  (`pip install -e ".[dev]"`).
- Network access to `elliotgarbus.github.io` and `pypi.org` the first time
  you lock: Kivy's iOS wheels come from the
  [`kivy-mobile-wheels`](https://github.com/ElliotGarbus/kivy-mobile-wheels)
  index, and Rubicon-ObjC's pure-Python wheel from PyPI.

## Lock, build, run

```bash
cd examples/mobile/swift-bridge
kivyforge lock -p ios
kivyforge build -p ios --simulator
kivyforge run -p ios --simulator
```

For a phone, set `[tool.kivy.ios.signing].team_id` (or pass `--team-id` to
`build`) and use `--device`.

## Try it

Each button writes to the log on screen, and to the app's console with a
`SWIFTBRIDGE` prefix.

| Tap | You see |
|-----|---------|
| **Notebook** | the notebook's notes, `wordCounts()` and `summary()` converted to a Python `list` and `dict`, the result of `applyOptions:` called with a plain `dict`, then `noteAtIndex 10: None` and the reason from the `NSError` |
| **Notification settings** | `done, result {'authorizationStatus': 0, 'alertsEnabled': 0}`: an Apple `async` API's answer, delivered to a Python completion handler |
| **Count primes** | progress every 10%, then the count. Tap **Cancel primes** while it runs to see `cancelled` |
| **Failing work** | `failed, the work failed on purpose`: the error argument of a throwing `async` method's completion handler |
| **Start metronome** | `tick 1` to `tick 6`, called by Swift into the Python delegate, then the summary from the optional stop method. Swift stops because the delegate's `metronome:shouldContinueAfter:` returns `False` |

`summary()` and the notification settings show a Swift `Bool` as `0` or `1`:
`py_from_ns()` converts a `Bool` inside a collection to an `int`.

On a desktop the shim is not built, so the buttons are disabled and the app
says so.

## What was verified

On an iOS 27 Simulator, from a clean build: every row above, including
cancelling the prime count and stopping the metronome early by hand. It has
not been run on a device yet; the `ios-swift-bridge-rubicon` item in
[`hardware-checklist.toml`](../../../docs/design/dev/hardware-checklist.toml)
is that check.
