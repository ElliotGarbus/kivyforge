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
delegates, and the rules pyobjus sets for each.

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
Python.

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

- **No closures in either direction.** Besides completion handlers, this
  rules out any Swift API that takes a closure, such as a sort comparator or
  an observer block. Wrap such APIs in the shim and expose the result as a
  value, a polled job or a delegate call.
- **Struct arguments to delegate methods.** pyobjus 1.2.5 copies each
  delegate argument into a pointer-sized slot, so a larger struct, such as a
  `CGRect`, cannot arrive intact. Pass the fields as separate numbers. [Call iOS APIs with pyobjus](pyobjus.md#know-what-pyobjus-gets-wrong-on-ios)
  covers structs passed to Objective-C methods.
- **When you need more than a shim.** A shim keeps Python's view of Swift to
  a few `@objc` classes, which is usually what an app wants. If you need
  Python to receive closures, or Swift to hold Python objects as ordinary
  values, you need a binding tool that generates a CPython extension module
  instead. kivyforge does not register extension modules built from Swift
  yet.

## What's next

- [Add a Swift package](swift-packages.md) to wrap a remote package with the
  shim, as the `keychain-spm` example does.
- [Run code in the iOS app lifecycle](lifecycle-hooks.md) for app-delegate
  callbacks that arrive before Python starts.
- [Run your iOS app on the simulator or a device](run.md).
