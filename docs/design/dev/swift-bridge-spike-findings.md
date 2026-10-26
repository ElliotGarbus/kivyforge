# Findings — calling Swift from Python through an `@objc` shim and pyobjus

> 2026-10-26, macOS host, iOS Simulator and an iPhone 18 Pro Max; both gave
> the same result on every check. Groundwork for issue #181, which asks for a
> tutorial on calling Swift from Python. `examples/mobile/keychain-spm` proves
> only class methods that take and return strings and booleans. The question:
> what else can a pyobjus caller reach through an `@objc` shim, namely
> instance methods, collections, an `async` API and a delegate written in
> Python, and where does it break?

**Short answer: nearly everything a tutorial needs works, with one rule per
gap.** Instance methods, properties, `[String]`, `[Int]` and nested
`[String: Any]` returns, a Python list argument, a `throws` method and an
`async` API reached by polling all worked. Swift called a Python delegate
from a main-thread `Timer`, from `DispatchQueue.main` and from a background
thread. Three pyobjus defects shape the tutorial's rules: a plain Python
`dict` argument arrives with keys and values swapped, a delegate method's
return value never reaches Swift, and an exception raised in a delegate
method is never cleared and later crashes the app.

## Defects found

All three are in pyobjus, not kivyforge. `kivy/pyobjus` master (`cd4a5e3`) has
the same code as the wheel tested, and none of the three has an upstream
issue. Upstream PRs, checked 2026-10-26 against every open PR and those merged
since #149:

| Defect | Upstream fix |
|---|---|
| 1, dict swap | None. #173 and #174 edit `pyobjus_conversions.pxi`, but not the `dict` branch. |
| 2, return dropped | [kivy/pyobjus#155](https://github.com/kivy/pyobjus/pull/155), open, CI green, conflicts with master. It writes the return value onto the invocation for `@`, the integer kinds, `B`, `c`/`C`, `f` and `d`, which covers the Swift `Bool` the spike returned. |
| 3, exception kept | None. #155 makes `protocol_forwardInvocation` `void` but leaves the Python call unguarded; its generated C still adds a traceback and returns with the exception set, and Cython warns that the function's exception check cannot be honoured. |

Defects 2 and 3 are in the same function, so a fix for 3 belongs on top of
#155, not beside it.

1. **A Python `dict` passed where Objective-C expects an object swaps keys and
   values.** `convert_py_to_nsobject` (`pyobjus_conversions.pxi`) builds the
   argument list for `initWithObjectsAndKeys_` as key, value, key, value, but
   that initialiser takes the *object* first. `{"name": "kivy", "n": 3}`
   arrived in Swift as `{"kivy": "name", 3: "n"}`. A shim that types the
   parameter `[String: Any]` traps on the bridging cast (`Could not cast
   value of type '__NSCFBoolean' to 'NSString'` in the first run, which
   killed the app). Reproduced on macOS with a desktop build of pyobjus, so
   it is not specific to iOS. **Workaround:** `pyobjus.objc_dict(d)`, which
   builds the dictionary correctly (check 2e').
2. **A delegate method's return value is dropped.** `protocol_forwardInvocation`
   calls the Python method and never sets the invocation's return value, so
   Swift reads zero. `tickerShouldContinue_` returned `True` in Python and
   Swift saw `false` three times out of three. Protocol methods that return
   something, such as `shouldX` or a data-source count, cannot be written in
   Python. The shim has to implement them in Swift until
   [kivy/pyobjus#155](https://github.com/kivy/pyobjus/pull/155) ships.
3. **An exception in a delegate method is never cleared.** The generated C
   for `protocol_forwardInvocation` calls `__Pyx_AddTraceback` and returns
   with the exception still set; it never prints or clears it. What follows
   depends on what Python runs next:
   - **Another callback into the same delegate fails.** The next
     `methodSignatureForSelector:` returned nil, and the app terminated with
     `NSInvalidArgumentException: -[__main__.RaisingDelegate@0x... tickerDidReportValue:]:
     unrecognized selector sent to instance`.
   - **Otherwise the exception surfaces in unrelated Python code.** When the
     exception was raised in the last callback of a run, a `TypeError` from
     the delegate surfaced in Kivy's main loop (`self.handle_exception(e)`).
     The bootstrap then exited with `failed to run entry module "main"`.

   **Rule:** wrap the body of every delegate method in `try`/`except`.

## Environment

| | |
|---|---|
| Host | macOS 26.6.2, Xcode 27.0 (27A266a), Apple Swift 6.4 |
| Simulator | iPhone Air, iOS 27.0 |
| Device | iPhone 18 Pro Max (`iPhone19,3`), iOS 27.0.1 (24A446), debug build, automatic signing for team `R5PKSQLUZY` |
| kivyforge | branch `ios-python-315-final` at `0bae27a1`, `.venv` editable install |
| App | scratch project, not in the repo: Kivy `3.0.0.dev202610251128`, pyobjus `1.2.5.dev202610250845`, CPython 3.15.0, all from kivy-mobile-wheels; `deployment_target = "16.0"` |
| Shim | local `path` package `SpikeBridge`, one Swift target, `.dynamic` product, depending on KeychainAccess 4.2.2 (`84e54672`) |

The `pyproject.toml` is `keychain-spm`'s, with the shim renamed:

```toml
[tool.kivy.ios.native.swift_packages]
KeychainAccess = { url = "https://github.com/kishikawakatsumi/KeychainAccess", requirement = { from = "4.2.2" }, products = ["KeychainAccess"], link = false, embed = false }
SpikeBridge = { path = "swift-shims", products = ["SpikeBridge"] }
```

## Method

The shim exposes three classes, each with an explicit Objective-C name:

- **`KFSecretStore`** is the keychain bridge, made an instance with state. It
  has `init` and `initWithService:`, a `let` and a `var` property, methods
  that return `[String]`, `[Int]` and a nested `[String: Any]`, methods that
  take `[NSNumber]`, `[String: Any]` and `NSDictionary`, and a `throws`
  method exported as `checkedStringForKey:error:`.
- **`KFAsyncJob`** starts Swift `async` work in a detached `Task` and
  publishes `state`, `result`, `errorMessage` and `isFinished` behind an
  `NSLock`. It has four jobs: a 0.5 s sleep,
  `UNUserNotificationCenter.notificationSettings()` (a real Apple `async`
  API that needs no prompt), a throwing task and a cancelled task. It also
  has one `@objc func fetchGreeting() async -> String`, to see what pyobjus
  makes of the completion-handler selector Swift generates.
- **`KFTicker`** holds a `weak var delegate: KFTickerDelegate?`. The
  protocol has two required methods (taking an object and an `Int`, and an
  object and a dictionary) and two optional ones (taking a `Double`, and
  returning `Bool`). The ticker calls them from a `Timer`, from
  `DispatchQueue.main.asyncAfter` or from `DispatchQueue.global()`, and
  records what `responds(to:)` said and what the `Bool` method returned.

`src/main.py` runs each check at launch and writes
`~/Documents/spike-results.json`, which the host reads back with
`xcrun simctl get_app_container booted org.kivy.swift-bridge-spike data`, or
from a device with `xcrun devicectl device copy from`. Python's `print` also reaches the unified log as `(Python) SPIKE ...` lines.
The async and delegate checks are polled from `Clock.schedule_interval`
every 0.05 s.

## Results

The table is the Simulator run. The device run matched it row for row: the
same two failures, and the raising delegate ended the app with the same
`unrecognized selector` `NSInvalidArgumentException`. Timings differed only
slightly: on the device the sleep job finished in 0.54 s, and
`notificationSettings()` again answered on the first poll.

| # | Check | Result | Detail |
|---|---|:---:|---|
| 1a | `alloc().init()` + instance method | PASS | `storeString_forKey_` gave `True`; `stringForKey_` gave an `NSTaggedPointerString` |
| 1b | `alloc().initWithService_(...)` | PASS | |
| 1c | state persists across calls | PASS | `writeCount` is a plain `int` |
| 1d | read/write property | PASS | `setLabel_("x")` and `obj.label = "x"` both work |
| 1e | `String?` returning nil | PASS | `None` |
| 2a | `[String]` return | PASS | `Swift.__SwiftDeferredNSArray`; converts to `['k1', 'k2', 'k3']` |
| 2b | `[Int]` return | PASS | `[0, 1, 4, 9]` |
| 2c | nested `[String: Any]` return | PASS | `_TtGCs26_SwiftDeferredNSDictionary...`; every value converted, including `Bool`, `Double` and nested containers |
| 2d | Python `list` as an `[NSNumber]` argument | PASS | `sumOf_([1, 2, 3, 4])` gave `10` |
| 2e | Python `dict` as an `NSDictionary` argument | **FAIL** | keys and values swapped (defect 1) |
| 2e' | `objc_dict(d)` as a `[String: Any]` argument | PASS | `True` arrives as `__NSCFBoolean` |
| 2f | `throws`, called with `None` for `error:` | PASS | value on success, `None` on failure; the `NSError` itself is not retrieved |
| 2g | `async` method's `...WithCompletionHandler_` | n/a | the selector is listed; calling it with a lambda raised `ObjcException: Not enough parameters`, as expected: pyobjus cannot build a block |
| 3 | async jobs, polled | PASS | sleep: done in 0.52 s over 10 polls, result computed on a background thread; `notificationSettings()`: `authorizationStatus=0` on the first poll; throw: `failed`, `'deliberate failure'`; cancel: `failed`, `'cancelled'` |
| 4 | delegate, main-thread `Timer` | PASS* | ticks 1-3, `Double` and dictionary arguments converted, Python ran on the main thread |
| 4 | delegate, `DispatchQueue.main` | PASS* | as above |
| 4 | delegate, background thread | PASS* | as above, but Python ran **on the background thread** |
| 4 | delegate's `Bool` return | **FAIL** | Swift saw `false` every time (defect 2) |
| 4a | `ticker.delegate = py_obj` | PASS | property assignment converts too, like `setDelegate_` |
| 4b | delegate with no Python reference, after `gc.collect()` | PASS | Swift's `weak` reference still set |
| 4 | delegate method raises | **FAIL** | app terminated (defect 3) |

\* Every row except the `Bool` return.

## What the results mean for a shim author

**Instance objects work as in Objective-C.** Call `Cls.alloc().init()` or
`Cls.alloc().initWithX_(...)`. A Swift `let` or `var` marked `@objc` reads
as a plain attribute. A Swift `Int` or `Bool` arrives as a Python `int` or
`bool`. A Swift `String` arrives as an `NSString` proxy that still needs
`UTF8String()`.

**Collections come back as proxies, so the tutorial needs a converter.** Two
things in the spike's converter are easy to get wrong:

- `value.isKindOfClass_(NSArray)` is `False` for every value when `NSArray`
  is the `autoclass` proxy. Pass the class object instead:
  `autoclass("NSArray").oclass()`.
- On Swift's bridged arrays, `count` comes back as an attribute holding an
  `int`, so `value.count()` raises `TypeError: 'int' object is not
  callable`. On Foundation's own `__NSArrayI`, in the desktop repro below,
  `count()` is a method. The converter has to accept both:
  `n = value.count; n = n if isinstance(n, int) else n()`.

Swift's own bridged containers (`__SwiftDeferredNSArray`,
`_SwiftDeferredNSDictionary`) behave as `NSArray` and `NSDictionary` and
need no special handling. Going the other way, a Python `list` converts
correctly, but a Python `dict` must go through `objc_dict` (defect 1).

**`throws` can stay.** Swift exports it as Objective-C's `NSError **`
convention, and pyobjus accepts `None` for the `error:` argument. The caller
gets `None` on failure but no reason. A shim that needs to report why should
return the message some other way, such as through a property, as
`KFAsyncJob` does.

**`async` and completion handlers need a polled job object.** pyobjus cannot
pass a Python callable as a block (2g). A `Task` that writes its result into
lock-protected properties, read from `Clock.schedule_interval`, worked for a
real Apple `async` API, for errors and for cancellation. Polling costs one
Objective-C call per tick per job.

**Delegates work if they only receive.** pyobjus finds a Swift
`@objc protocol` by name with `objc_getProtocol`, so a Swift-declared
protocol needs no entry in pyobjus' precompiled `protocols.py`. Optional
methods answer `responds(to:)` correctly. The tutorial needs these rules:

- **Return nothing.** Anything a protocol method returns, the shim has to
  supply itself (defect 2).
- **Catch every exception** in the method body (defect 3).
- **Expect the caller's thread.** A Swift background-thread callback runs
  Python on that thread, holding the GIL, with no crash. Code that touches
  widgets must hop to Kivy's thread, for example with Kivy's `@mainthread`.
  This was not exercised here. Alternatively, the shim can dispatch to
  `DispatchQueue.main` before it calls the delegate.
- **Expect the delegate to live forever.** pyobjus keeps every delegate it
  creates in `delegate_register`, keyed by the Python object, so a `weak`
  Swift reference never goes nil and neither object is released. Create one
  delegate object and reuse it.

**The main run loop is serviced while Kivy runs.** A `Timer` scheduled on the
main thread and blocks sent to `DispatchQueue.main` both fired on time during
Kivy's main loop. A shim can therefore deliver to the main thread with no
extra arrangement.

## Not verified

- **Retrieving the `NSError`** from a `throws` method, by passing a
  reference instead of `None`.
- **Kivy's `@mainthread`** used from a background-thread delegate.
- **Struct arguments to delegate methods.** `forwardInvocation` reads each
  argument into an `id`-sized buffer, so anything over 8 bytes is suspect.
  This has the same shape as the `CGRect` defect in
  [`pyobjus.md`](../../guides/guides/ios/pyobjus.md), but was not tested.
- **Release builds**, with `strip_source` and byte-compiled code.

## Reproduce

The scratch project is not kept. To rebuild it, copy
`examples/mobile/keychain-spm`, then rename the shim package and product
to `SpikeBridge`, the bundle ID to `org.kivy.swift-bridge-spike` and the
project to `swift-bridge-spike`. Add the three classes described in
§"Method" and run:

```bash
kivyforge lock -p ios
kivyforge build -p ios --simulator
kivyforge run -p ios --simulator --no-build
xcrun simctl get_app_container booted org.kivy.swift-bridge-spike data
```

The results are in `Documents/spike-results.json` under the printed
directory. On a device, build with `kivyforge build -p ios --device
--team-id <TEAM>`, run with `kivyforge run -p ios --device --no-build
--destination <UDID>`, and copy the results off with:

```bash
xcrun devicectl device copy from --device <UDID> --domain-type appDataContainer --domain-identifier org.kivy.swift-bridge-spike --source Documents/spike-results.json --destination spike-results.json
```

A first install attempt failed with `com.apple.dt.CoreDeviceError error
4016`. That was a locked phone; it installed once unlocked. The defect 1 reproduction needs only a desktop pyobjus:

```python
from pyobjus import autoclass
d = autoclass("NSMutableDictionary").alloc().init()
d.setDictionary_({"name": "kivy", "n": 3})
keys = d.allKeys()
print([keys.objectAtIndex_(i).description().UTF8String() for i in range(keys.count())])
# [b'3', b'kivy'] -- the values, not the keys
```
