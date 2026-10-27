# Swift bridge — call Swift from Python with an `@objc` shim

This example calls Swift code from a Kivy app on iOS. The Swift code is a
small local package, `swift-shims/`, whose classes are marked `@objc`, so
[pyobjus](https://github.com/kivy/pyobjus) can find them by name and call
them. The example covers the four things an app usually needs from Swift:

- an object with state: initialisers, properties and methods;
- collections in both directions, and a method that `throws`;
- `async` work, which Python polls from Kivy's `Clock` instead of passing a
  completion handler;
- a delegate protocol declared in Swift and implemented in Python.

The user guide, [Call Swift from Python](../../../docs/guides/guides/ios/swift.md),
walks through each pattern and the rules pyobjus imposes.
[`keychain-spm`](../keychain-spm/) shows the same shim wrapping a remote
Swift package.

## What's here

| Path | Purpose |
|------|---------|
| `pyproject.toml` | App config; declares the shim under `[tool.kivy.ios.native.swift_packages]` |
| `swift-shims/Package.swift` | Local package, one Swift target, a dynamic product |
| `swift-shims/Sources/SwiftBridge/Notebook.swift` | `SBNotebook`: initialisers, properties, collections, `throws` |
| `swift-shims/Sources/SwiftBridge/Job.swift` | `SBJob` and `SBWork`: async work that Python polls |
| `swift-shims/Sources/SwiftBridge/Metronome.swift` | `SBMetronome` and the `SBMetronomeDelegate` protocol |
| `src/objc_convert.py` | `to_py()`: Foundation proxies to Python values; copy it into your app |
| `src/demos.py` | The Python side of each pattern |
| `src/main.py` | The UI: a button per demo and a log |

## Prerequisites

- macOS with Xcode, and kivyforge installed from this repo
  (`pip install -e ".[dev]"`).
- Network access to `elliotgarbus.github.io` the first time you lock: Kivy and
  pyobjus iOS wheels come from the
  [`kivy-mobile-wheels`](https://github.com/ElliotGarbus/kivy-mobile-wheels)
  index.

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
| **Notebook** | the notebook's notes, `wordCounts()` and `summary()` converted to a Python `list` and `dict`, the result of `applyOptions:`, then `noteAtIndex 10: None` and the reason from `lastError` |
| **Notification settings** | `done, result {'authorizationStatus': 0, 'alertsEnabled': False}`: an Apple `async` API's answer, collected by polling |
| **Count primes** | progress every 10%, then the count. Tap **Cancel primes** while it runs to see `cancelled` |
| **Failing work** | `failed, the work failed on purpose` |
| **Start metronome** | `tick 1` to `tick 6`, called by Swift into the Python delegate, then the summary from the optional stop method |

On a desktop the shim is not built, so the buttons are disabled and the app
says so.

## What was verified

On an iOS 27 Simulator: every row above, including cancelling the prime count
and stopping the metronome early. On an iPhone with iOS 27: each button wrote
its results to the log, with no crash.

## Limits

These come from pyobjus 1.2.5 and shape how the shim is written. The guide
explains each one.

- A plain Python `dict` argument arrives with its keys and values swapped, so
  `demos.py` passes `objc_dict(...)`.
- A Python delegate method's return value never reaches Swift, so the
  metronome's delegate methods return nothing and the stop condition is a
  property, `maxTicks`.
- An exception that escapes a delegate method ends the app later, so each
  delegate method catches its own.
- A Python list that contains a list can crash the call it is passed to. Pass
  flat lists.
