# Swift bridge — call Swift from Python with an `@objc` shim

This example calls Swift code from a Kivy app on iOS. The Swift code is a
small local package, `swift-shims/`, whose classes are marked `@objc`, so
[pyobjus](https://github.com/kivy/pyobjus) and
[Rubicon-ObjC](https://github.com/beeware/rubicon-objc) can find them by name
and call them. A switch at the top of the screen picks the bridge. The
example covers the four things an app usually needs from Swift:

- an object with state: initialisers, properties and methods;
- collections in both directions, and a method that `throws`;
- `async` work, which pyobjus polls from Kivy's `Clock` and Rubicon-ObjC
  receives through a completion handler;
- a delegate protocol declared in Swift and implemented in Python.

The user guide, [Call Swift from Python](../../../docs/guides/guides/ios/swift.md),
walks through each pattern, the rules pyobjus imposes, and how Rubicon-ObjC
differs.
[`keychain-spm`](../keychain-spm/) shows the same shim wrapping a remote
Swift package.

## What's here

| Path | Purpose |
|------|---------|
| `pyproject.toml` | App config; declares the shim under `[tool.kivy.ios.native.swift_packages]` |
| `swift-shims/Package.swift` | Local package, one Swift target, a dynamic product |
| `swift-shims/Sources/SwiftBridge/Notebook.swift` | `SBNotebook`: initialisers, properties, collections, `throws` |
| `swift-shims/Sources/SwiftBridge/Job.swift` | `SBJob` and `SBWork`: async work that Python polls, and `async` methods with completion handlers |
| `swift-shims/Sources/SwiftBridge/Metronome.swift` | `SBMetronome` and the `SBMetronomeDelegate` protocol |
| `src/objc_convert.py` | `to_py()`: Foundation proxies to Python values for pyobjus; copy it into your app |
| `src/demos.py` | The Python side of each pattern, with pyobjus |
| `src/demos_rubicon.py` | The same demos with Rubicon-ObjC |
| `src/main.py` | The UI: the bridge switch, a button per demo and a log |

## Prerequisites

- macOS with Xcode, and kivyforge installed from this repo
  (`pip install -e ".[dev]"`).
- Network access to `elliotgarbus.github.io` and `pypi.org` the first time
  you lock: Kivy and pyobjus iOS wheels come from the
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

Pick **pyobjus** or **Rubicon-ObjC** at the top; the switch is locked while
the prime count or the metronome runs. Each button writes to the log on
screen, and to the app's console with a `SWIFTBRIDGE` prefix. The table
shows pyobjus; Rubicon-ObjC differences follow it.

| Tap | You see |
|-----|---------|
| **Notebook** | the notebook's notes, `wordCounts()` and `summary()` converted to a Python `list` and `dict`, the result of `applyOptions:`, then `noteAtIndex 10: None` and the reason from `lastError` |
| **Notification settings** | `done, result {'authorizationStatus': 0, 'alertsEnabled': False}`: an Apple `async` API's answer, collected by polling |
| **Count primes** | progress every 10%, then the count. Tap **Cancel primes** while it runs to see `cancelled` |
| **Failing work** | `failed, the work failed on purpose` |
| **Start metronome** | `tick 1` to `tick 6`, called by Swift into the Python delegate, then the summary from the optional stop method |

With **Rubicon-ObjC**, the results match, except:

- **Notebook** reads the reason for `noteAtIndex 10` from the `NSError`, not
  from `lastError`, and shows `isEmpty` as `0`: `py_from_ns()` returns a
  Swift `Bool` inside a collection as an `int`.
- **Notification settings** and **Failing work** call Swift `async` methods
  with a Python completion handler instead of polling a job.
- **Start metronome** stops at six ticks because the Python delegate's
  `metronome:shouldContinueAfter:` returns `False`, not because of
  `maxTicks`. The summary's `reachedLimit` is therefore `0`.

On a desktop the shim is not built, so the buttons are disabled and the app
says so.

## What was verified

On an iOS 27 Simulator: every row above, including cancelling the prime count
and stopping the metronome early. On an iPhone with iOS 27: each button wrote
its results to the log, with no crash. Rubicon-ObjC: every row, including the
prime-count cancel, on an iOS 27 Simulator only; it has not been run on a
device.

## Limits

These come from pyobjus 1.2.5 and shape how the pyobjus side is written.
Rubicon-ObjC has none of them. The guide explains each one.

- A plain Python `dict` argument arrives with its keys and values swapped, so
  `demos.py` passes `objc_dict(...)`.
- A Python delegate method's return value never reaches Swift, so the
  metronome's delegate methods return nothing and the stop condition is a
  property, `maxTicks`.
- An exception that escapes a delegate method ends the app later, so each
  delegate method catches its own.
- A Python list that contains a list can crash the call it is passed to. Pass
  flat lists.
