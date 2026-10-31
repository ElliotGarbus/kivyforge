---
title: Call Swift from Python
sources:
  - docs/design/dev/swift-bridge-spike-findings.md
  - examples/mobile/swift-bridge/pyproject.toml
  - examples/mobile/swift-bridge/swift-shims/Sources/SwiftBridge/Notebook.swift
  - examples/mobile/swift-bridge/swift-shims/Sources/SwiftBridge/Job.swift
  - examples/mobile/swift-bridge/swift-shims/Sources/SwiftBridge/Metronome.swift
  - examples/mobile/swift-bridge/src/objc_convert.py
  - examples/mobile/swift-bridge/src/demos.py
  - examples/mobile/swift-bridge/src/demos_rubicon.py
---

# Call Swift from Python

Python on iOS reaches native code through
[pyobjus](https://github.com/kivy/pyobjus), which talks to the Objective-C
runtime. Swift code is visible there only when it is marked `@objc`, and only
in the shapes Objective-C understands. To call Swift, you write a small Swift
package of `@objc` classes, called a *shim*, that exposes exactly what your
app needs, and call it from Python by class name.

This page shows you how to write the shim and how to call it. It covers
objects with state, collections, methods that throw, `async` work and
delegates, and the rules pyobjus sets for each. The same shim can also be
called with [Rubicon-ObjC](#call-the-shim-with-rubicon-objc), which avoids
most of those rules.

## Before you begin

- [Add a Swift package](swift-packages.md) explains how packages are
  declared. A shim is a local `path` package.
- [Call iOS APIs with pyobjus](pyobjus.md): add `pyobjus` to your
  dependencies.
- Have the `swift-bridge` example from the kivyforge repository at hand
  (`examples/mobile/swift-bridge`). Every snippet on this page comes from it.

## Add a shim package

1. Create a package directory in your project, for example `swift-shims/`,
   with a `Package.swift` that declares a dynamic library:

    ```swift
    // swift-tools-version:5.9
    import PackageDescription

    let package = Package(
        name: "SwiftBridge",
        platforms: [.iOS(.v16)],
        products: [
            .library(name: "SwiftBridge", type: .dynamic, targets: ["SwiftBridge"]),
        ],
        targets: [
            .target(name: "SwiftBridge"),
        ]
    )
    ```

    The product must be dynamic. Your app target contains no Swift that
    refers to the shim, because Python looks its classes up at runtime, so
    the shim must be embedded as a framework that loads at launch.

2. Put your Swift files in `swift-shims/Sources/SwiftBridge/`.

3. Declare the package:

    ```toml
    [tool.kivy.ios.native.swift_packages]
    SwiftBridge = { path = "swift-shims", products = ["SwiftBridge"] }
    ```

    A local package is linked and embedded by default. If the shim wraps a
    remote package, declare that one too, with `link = false, embed = false`;
    [Add a Swift package](swift-packages.md#add-a-local-shim-to-call-swift-from-python)
    explains why.

4. Lock the project:

    ```bash
    kivyforge lock -p ios
    ```

## Write Swift that pyobjus can call

Follow these rules for every class and method Python calls:

- **Subclass `NSObject` and give the class an explicit Objective-C name**,
  such as `@objc(SBNotebook)`. Without one, Swift generates a mangled name.
  A short prefix keeps your names apart from Apple's.
- **Give each method an explicit selector**, such as `@objc(addNote:)`. You
  then know exactly what Python calls it: each colon becomes an underscore,
  so `addNote:` is `addNote_` and `noteAtIndex:error:` is
  `noteAtIndex_error_`.
- **Use types Objective-C can represent**: `String`, `Int`, `Double`, `Bool`,
  arrays and dictionaries of those, and `NSObject` subclasses. Convert
  anything else inside the shim. A struct, an enum with associated values, a
  generic or a tuple cannot be `@objc`.

```swift
@objc(SBNotebook)
public final class Notebook: NSObject {
    @objc public let title: String
    @objc public var author = "anonymous"
    @objc public private(set) var notes: [String] = []

    @objc(initWithTitle:)
    public init(title: String) {
        self.title = title
        super.init()
    }

    @objc(addNote:)
    public func add(_ text: String) -> Int {
        notes.append(text)
        return notes.count
    }
}
```

## Call the shim from Python

Look the class up with `autoclass` by its Objective-C name, then create an
instance with `alloc()` and an initialiser. An `@objc` property is a plain
attribute, and a `var` can be assigned:

```python
from pyobjus import autoclass

Notebook = autoclass("SBNotebook")

notebook = Notebook.alloc().initWithTitle_("Groceries")
notebook.author = "Kivy"
count = notebook.addNote_("apples and pears")
```

Import pyobjus only on iOS. The example does it in `main.py`:

```python
from kivy.utils import platform

demos = None
if platform == "ios":
    import demos  # imports pyobjus and looks up the shim's classes
```

## Convert what Swift returns

A Swift `Int`, `Double` or `Bool` arrives as a Python `int`, `float` or
`bool`, and `nil` arrives as `None`. Everything else arrives as a proxy for
an Objective-C object:

| Swift returns | Python receives |
|---|---|
| `String` | an `NSString` proxy |
| `[String]`, `[Int]`, ... | an `NSArray` proxy |
| `[String: Any]`, `[String: Int]`, ... | an `NSDictionary` proxy |
| an `NSObject` subclass | a proxy you can call methods on |

Copy `src/objc_convert.py` from the example into your app. Its `nsstr()`
converts an `NSString`, and `to_py()` converts a whole tree of strings,
numbers, arrays and dictionaries:

```python
from objc_convert import nsstr, to_py

print(nsstr(notebook.title))       # 'Groceries'
print(to_py(notebook.notes))       # ['apples and pears']
print(to_py(notebook.summary()))   # {'count': 1, 'latest': [...], 'totals': {...}, ...}
```

If you write your own converter, two things in it are easy to get wrong:

- `isKindOfClass_` needs the class object, not the `autoclass` proxy. Use
  `autoclass("NSArray").oclass()`. Passing the proxy returns `False` for
  every value.
- On Swift's arrays, `count` is an attribute holding an `int`, but on
  Foundation's own arrays it is a method. Accept both.

## Pass collections to Swift

A flat Python `list` of strings or numbers converts to an `NSArray`, and
Swift receives it as `[String]` or `[NSNumber]`:

```python
notebook.addNotes_(["more apples", "bread"])
```

Pass a dictionary through `objc_dict()`. A plain Python `dict` reaches Swift
with its keys and values swapped, which crashes a Swift method that expects
`[String: Any]`:

```python
from pyobjus import objc_dict

notebook.applyOptions_(objc_dict({"author": "Swift", "keepLast": 2}))
```

`objc_dict()` needs string keys. Keep what you pass flat: a Python list that
contains another list can crash the call. For nested data, pass a JSON string
and decode it in Swift with `JSONSerialization` or `Codable`.

## Call a method that throws

Swift exports a throwing method with an extra `error:` argument. Pass `None`
for it. The method returns `None` when it throws:

```swift
@objc(noteAtIndex:error:)
public func note(at index: Int) throws -> String
```

```python
note = notebook.noteAtIndex_error_(10, None)
if note is None:
    print("failed:", nsstr(notebook.lastError))
```

pyobjus does not give you the `NSError`, so if Python needs the reason, the
shim must keep it somewhere Python can read, like `lastError` in the example.
Return an object type, such as `String`, so that `None` means failure.

## Run async work and poll for the result

pyobjus cannot pass a Python function to Swift as a closure. A Swift `async`
method, or an API that takes a completion handler, therefore cannot call
back into Python. Swift exports an `async` method as a
`...WithCompletionHandler:` selector, and calling it from Python fails.
(Rubicon-ObjC can pass one: see
[Call an `async` method with a completion handler](#call-an-async-method-with-a-completion-handler).)

Instead, have the shim start the work and return an object that holds the
outcome, and poll that object from Kivy's `Clock`. The example's `SBJob`
does this for any `async` work:

```swift
@objc(SBJob)
public final class Job: NSObject {
    // state, isFinished, progress, result and errorMessage are @objc
    // properties behind an NSLock, because the work runs on another thread.

    init(_ work: @escaping (Job) async throws -> Any?) {
        super.init()
        task = Task.detached { [self] in
            do {
                finish("done", result: try await work(self), error: nil)
            } catch is CancellationError {
                finish("cancelled", result: nil, error: nil)
            } catch {
                finish("failed", result: nil, error: error.localizedDescription)
            }
        }
    }

    @objc public func cancel() { task?.cancel() }
}

@objc(SBWork)
public final class Work: NSObject {
    @objc public static func notificationSettings() -> Job {
        Job { _ in
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            return ["authorizationStatus": settings.authorizationStatus.rawValue]
        }
    }
}
```

On the Python side, poll until the job finishes, then read the result:

```python
from kivy.clock import Clock


class JobWatcher:
    _active = set()

    def __init__(self, job, on_result):
        self.job = job
        self.on_result = on_result
        JobWatcher._active.add(self)
        Clock.schedule_interval(self._poll, 0.1)

    def _poll(self, _dt):
        if not self.job.isFinished:
            return True  # keep polling
        JobWatcher._active.discard(self)
        if nsstr(self.job.state) == "done":
            self.on_result(to_py(self.job.result))
        return False  # stop polling


JobWatcher(Work.notificationSettings(), print)
```

!!! warning "Keep the watcher alive"
    Kivy's `Clock` holds a bound method only weakly. If nothing else refers
    to the watcher, it is garbage-collected and polling stops without an
    error. `_active` holds each watcher until its job finishes.

Polling costs one call into Swift per job per tick. For long work, report
progress the same way: the example's prime counter sets `progress`, and
Python shows it on each poll.

## Implement a Swift delegate in Python

1. Declare the protocol in Swift with an explicit name, and give the class
   that calls it a `weak` delegate property:

    ```swift
    @objc(SBMetronomeDelegate)
    public protocol MetronomeDelegate: NSObjectProtocol {
        @objc(metronome:didTick:)
        func metronome(_ metronome: Metronome, didTick count: Int)

        @objc(metronome:didStopWithSummary:)
        optional func metronome(_ metronome: Metronome, didStopWithSummary summary: [String: Any])
    }

    @objc(SBMetronome)
    public final class Metronome: NSObject {
        @objc public weak var delegate: MetronomeDelegate?
        // ...
    }
    ```

2. In Python, mark each method with `@protocol` and the protocol's name.
   pyobjus finds a protocol declared in Swift by name, so it needs no entry
   in pyobjus' own protocol table:

    ```python
    import traceback

    from pyobjus import protocol


    class MetronomeListener:
        @protocol("SBMetronomeDelegate")
        def metronome_didTick_(self, metronome, count):
            try:
                print("tick", count)
            except Exception:
                traceback.print_exc()

        @protocol("SBMetronomeDelegate")
        def metronome_didStopWithSummary_(self, metronome, summary):
            try:
                print("stopped", to_py(summary))
            except Exception:
                traceback.print_exc()
    ```

3. Assign the Python object to the delegate property:

    ```python
    listener = MetronomeListener()
    metronome = autoclass("SBMetronome").alloc().init()
    metronome.delegate = listener
    metronome.start()
    ```

Write every delegate method to these rules:

- **Return nothing.** pyobjus 1.2.5 drops a delegate method's return value,
  so Swift reads `false`, `0` or `nil`. If Swift needs an answer from the
  app, such as whether to continue, make it a property the app sets. The
  metronome stops after `maxTicks`, which Python sets.
- **Catch every exception inside the method.** An exception that escapes a
  delegate method is never cleared: the next call into the same delegate
  fails and ends the app, or the error surfaces later in unrelated code.
- **Expect to run on the caller's thread.** If Swift calls the delegate from
  a background thread, your Python method runs on that thread. Code that
  changes widgets must run on Kivy's thread. The simplest fix is in the shim:
  call the delegate from the main thread, with a main-thread `Timer` as the
  metronome does or with `DispatchQueue.main.async { ... }`.
- **Create one delegate object and reuse it.** pyobjus keeps every Python
  object it has turned into a delegate alive for the life of the app, so a
  `weak` Swift reference to it never becomes `nil`. A new delegate per call
  leaks.

The main thread's run loop runs while Kivy runs, so a `Timer` or
`DispatchQueue.main` in the shim fires on time.

## Call the shim with Rubicon-ObjC

[Rubicon-ObjC](https://github.com/beeware/rubicon-objc), BeeWare's bridge to
the Objective-C runtime, calls the same shim with no change to the Swift. It
is pure Python on top of `ctypes`, and it does several things pyobjus 1.2.5
cannot: it passes a Python function where Swift expects a completion
handler, returns a delegate method's value to Swift, hands you the `NSError`
from a throwing method, and converts a plain `dict` or a nested list
correctly.

The example has both. `src/demos_rubicon.py` runs the same demos as
`src/demos.py`, and the buttons at the top of the screen switch between
them. Both bridges can live in one app.

### Add Rubicon-ObjC

Add it to your dependencies:

```toml
[project]
dependencies = [
    "kivy>=3.0.0.dev0,<4",
    "rubicon-objc>=0.5.7",
]
```

Rubicon-ObjC is one `py3-none-any` wheel, so `kivyforge lock -p ios` takes
it from PyPI for every iOS slice, with no mobile wheel index. Version 0.5.7
is the one tested here, and it supports CPython 3.15. As with pyobjus,
import it only on iOS, where the shim exists.

### Call methods and properties

Look the class up with `ObjCClass` by its Objective-C name. The first part
of a selector is the method name and each later part is a keyword argument,
so `initWithTitle:` is `initWithTitle(...)` and `noteAtIndex:error:` is
`noteAtIndex(..., error=...)`:

```python
from rubicon.objc import ObjCClass

Notebook = ObjCClass("SBNotebook")

notebook = Notebook.alloc().initWithTitle("Groceries")
notebook.author = "Kivy"
count = notebook.addNote("apples and pears")
```

### Convert what Swift returns

A returned `NSString` formats and compares like a `str`, but is not one;
call `str()` when you need a real `str`. An `NSArray` or `NSDictionary`
behaves like a read-only list or dictionary. `py_from_ns()` converts a whole
tree, so you do not need the example's `objc_convert.py`:

```python
from rubicon.objc import py_from_ns

print(notebook.title)                   # Groceries
print(py_from_ns(notebook.summary()))   # {'count': 1, 'isEmpty': 0, ...}
```

A Swift `Bool` inside a collection comes back as `0` or `1`, not `False` or
`True`. Wrap it in `bool()` where the type matters. A `Bool` returned
directly from a method or property is a Python `bool`.

### Pass collections

Pass a Python `list` or `dict` as it is. Rubicon-ObjC builds the dictionary
correctly, and nested lists and dictionaries convert too:

```python
notebook.addNotes(["more apples", "bread"])
notebook.applyOptions({"author": "Swift", "keepLast": 2})
```

### Read the error from a throwing method

Pass a pointer to an `objc_id` for the `error:` argument. When the method
throws, it returns `None` and the pointer holds the `NSError`, so the shim
does not need to keep the reason itself:

```python
from ctypes import byref

from rubicon.objc import ObjCInstance
from rubicon.objc.runtime import objc_id

error = objc_id()
note = notebook.noteAtIndex(10, error=byref(error))
if note is None:
    print("failed:", ObjCInstance(error).localizedDescription)
```

### Call an `async` method with a completion handler

Swift exports an `async` method as one whose last argument is a completion
handler. Give it an explicit selector that ends in `completionHandler:`:

```swift
@objc(currentNotificationSettingsWithCompletionHandler:)
public static func currentNotificationSettings() async -> [String: Any] {
    let settings = await UNUserNotificationCenter.current().notificationSettings()
    return ["authorizationStatus": settings.authorizationStatus.rawValue]
}
```

Pass a Python function for the handler. Swift calls it once, when the work
finishes:

```python
from kivy.clock import Clock
from rubicon.objc import ObjCClass, ObjCInstance, py_from_ns
from rubicon.objc.runtime import objc_id

Work = ObjCClass("SBWork")


def done(settings: objc_id) -> None:
    result = py_from_ns(ObjCInstance(settings))
    Clock.schedule_once(lambda _dt: print(result), 0)


Work.currentNotificationSettingsWithCompletionHandler(done)
```

Write every completion handler to these rules:

- **Annotate every parameter and the return.** Rubicon-ObjC builds the
  block's signature from the annotations, and raises `ValueError` without
  them. Use `objc_id` for an object, and `-> None`.
- **Wrap each object argument yourself.** It arrives as a bare `objc_id`
  pointer even when annotated `ObjCInstance`. Pass it to `ObjCInstance()` to
  call methods on it. A null pointer is false.
- **Move to Kivy's thread before touching widgets.** Swift calls the handler
  on one of its own threads. `Clock.schedule_once` is safe to call from any
  thread, so schedule the rest of the work there.
- **Expect two arguments from a throwing method.** The handler of an
  `async throws` method takes the result and an error, and exactly one of
  them is null:

    ```python
    def done(result: objc_id, error: objc_id) -> None:
        if error:
            print("failed:", ObjCInstance(error).localizedDescription)
    ```

You do not need to keep a reference to the function: Rubicon-ObjC keeps it
alive until Swift releases the handler. A completion handler cannot report
progress or be cancelled, so for long work that needs either, keep the
polled-job pattern. The example still counts primes with `SBJob`.

### Implement a Swift delegate in Python

Subclass `NSObject` and name the protocol. Mark each method with
`@objc_method`; its name maps to the selector the same way, underscores for
colons. Annotate parameters that are not objects: a Swift `Int` is
`NSInteger`, and a `Bool` return is `bool`. Unannotated parameters arrive
as objects you can call methods on:

```python
from rubicon.objc import NSObject, ObjCProtocol, objc_method
from rubicon.objc.types import NSInteger


class MetronomeListener(NSObject, protocols=[ObjCProtocol("SBMetronomeDelegate")]):
    @objc_method
    def metronome_didTick_(self, metronome, count: NSInteger) -> None:
        print("tick", count)

    @objc_method
    def metronome_shouldContinueAfter_(self, metronome, count: NSInteger) -> bool:
        return count < 6


listener = MetronomeListener.alloc().init()
metronome = ObjCClass("SBMetronome").alloc().init()
metronome.delegate = listener
metronome.start()
```

Swift reads the return value, so the metronome stops after six ticks without
the `maxTicks` property the pyobjus version needs. Write every delegate class
to these rules:

- **Define the class once, at module level.** It is a real Objective-C class,
  and class names are global to the process: defining the same name twice
  raises `RuntimeError`.
- **Keep a reference to the delegate.** A delegate property is usually
  `weak`, and Rubicon-ObjC does not keep the object alive for it the way
  pyobjus does. Hold it for as long as Swift should call it, as the example's
  `MetronomeDemo` does.
- **An exception is printed, not raised.** Python prints the traceback, and
  Swift reads `0`, `false` or `nil` as the method's return value. Later calls
  work normally. Catch the exception yourself if a wrong return value would
  matter.
- **Expect to run on the caller's thread.** This rule is the same as for
  pyobjus: Swift should call the delegate on the main thread.

You can set Python attributes on the instance, such as a callback
(`listener.log = print`), and read them from its methods.

### Compare the two bridges

The shim is the same for both: `@objc` names, Objective-C types and a
dynamic product. What differs is the Python side:

| | pyobjus 1.2.5 | Rubicon-ObjC 0.5.7 |
|---|---|---|
| Wheel | compiled, from the kivy-mobile-wheels index | pure Python, from PyPI |
| Look up a class | `autoclass("SBNotebook")` | `ObjCClass("SBNotebook")` |
| Call `noteAtIndex:error:` | `noteAtIndex_error_(i, None)` | `noteAtIndex(i, error=...)` |
| Convert a result | `objc_convert.to_py()` from the example | `py_from_ns()`; a `Bool` in a collection is `0`/`1` |
| `dict` argument | `objc_dict(...)` | a plain `dict` |
| List inside a list | can crash the call | converts |
| Error from a throwing method | not returned; the shim keeps the reason | `error=byref(objc_id())` |
| `async` work | poll a job from `Clock` | a completion handler, or poll |
| Delegate return value | dropped | reaches Swift |
| Exception in a delegate | ends the app later; catch it | printed; Swift reads zero |
| Delegate lifetime | kept alive forever | you keep a reference |

## Verify

Build and run the example on the Simulator:

```bash
cd examples/mobile/swift-bridge
kivyforge lock -p ios
kivyforge build -p ios --simulator
kivyforge run -p ios --simulator
```

Tap each button. The log shows the converted results, the async jobs
finishing, failing or being cancelled, and the metronome's ticks arriving in
Python. Then tap **Rubicon-ObjC** at the top and tap each button again: the
results match, and the metronome stops at six ticks because Swift read the
Python delegate's answer.

## Things to know

- **pyobjus defects behind the rules above.** Each one has an open fix in
  pyobjus. Until a pyobjus wheel that includes the fix is published, follow
  the workaround:

    | Defect | Workaround | Fix |
    |---|---|---|
    | A plain `dict` argument arrives with keys and values swapped | `objc_dict()` | [kivy/pyobjus#180](https://github.com/kivy/pyobjus/pull/180) |
    | A delegate method's return value is dropped | return nothing; use a property | [kivy/pyobjus#181](https://github.com/kivy/pyobjus/pull/181) |
    | An exception in a delegate method is never cleared | `try`/`except` in every delegate method | [kivy/pyobjus#181](https://github.com/kivy/pyobjus/pull/181) |
    | A list nested in a list can crash a call | pass flat lists, or JSON | [kivy/pyobjus#182](https://github.com/kivy/pyobjus/pull/182) |

    The workarounds stay correct after the fixes, so code written to them
    keeps working.

- **No closures with pyobjus.** Besides completion handlers, this rules
  out any Swift API that takes a closure, such as a sort comparator or an
  observer block. Wrap such APIs in the shim and expose the result as a
  value, a polled job or a delegate call, or call them with Rubicon-ObjC,
  which passes a Python function as the closure.
- **Struct arguments to delegate methods.** pyobjus 1.2.5 copies each
  delegate argument into a pointer-sized slot, so a larger struct, such as a
  `CGRect`, cannot arrive intact. Pass the fields as separate numbers. [Call iOS APIs with pyobjus](pyobjus.md#know-what-pyobjus-gets-wrong-on-ios)
  covers structs passed to Objective-C methods.
- **When you need more than a shim.** A shim keeps Python's view of Swift to
  a few `@objc` classes, which is usually what an app wants. If you need
  Python to see Swift types that Objective-C cannot represent, or Swift to
  hold Python objects as ordinary values, you need a binding tool that
  generates a CPython extension module instead. kivyforge does not register extension modules built from Swift
  yet.

## What's next

- [Add a Swift package](swift-packages.md) to wrap a remote package with the
  shim, as the `keychain-spm` example does.
- [Run code in the iOS app lifecycle](lifecycle-hooks.md) for app-delegate
  callbacks that arrive before Python starts.
- [Run your iOS app on the simulator or a device](run.md).
