---
title: Call Swift from Python
sources:
  - docs/design/dev/swift-bridge-spike-findings.md
  - docs/design/dev/macos-swift-packages-spike-findings.md
  - examples/mobile/swift-bridge/pyproject.toml
  - examples/mobile/swift-bridge/swift-shims/Sources/SwiftBridge/Notebook.swift
  - examples/mobile/swift-bridge/swift-shims/Sources/SwiftBridge/Job.swift
  - examples/mobile/swift-bridge/swift-shims/Sources/SwiftBridge/Metronome.swift
  - examples/mobile/swift-bridge/src/demos.py
---

# Call Swift from Python

Python on iOS and macOS reaches native code through the Objective-C runtime. Swift code
is visible there only when it is marked `@objc`, and only in the shapes
Objective-C understands. To call Swift, you write a small Swift package of
`@objc` classes, called a *shim*, that exposes exactly what your app needs,
and call it from Python by class name with
[Rubicon-ObjC](https://github.com/beeware/rubicon-objc), BeeWare's bridge to
the Objective-C runtime.

This page shows you how to write the shim and how to call it. It covers
objects with state, collections, methods that throw, `async` work and
delegates. If your app already uses pyobjus, it can call the same shim; see
[Use pyobjus instead](#use-pyobjus-instead).

## Before you begin

- [Add a Swift package](swift-packages.md) explains how packages are
  declared. A shim is a local `path` package.
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

## Add Rubicon-ObjC

1. Add it to your dependencies:

    ```toml
    [project]
    dependencies = [
        "kivy>=3.0.0.dev0,<4",
        "rubicon-objc>=0.5.7",
    ]
    ```

    Rubicon-ObjC is pure Python on top of `ctypes`, published as one
    `py3-none-any` wheel, so the lock takes it from PyPI for every iOS slice.
    Version 0.5.7 is the one tested here, and it supports CPython 3.15.

2. Lock the project:

    ```bash
    kivyforge lock -p ios
    ```

3. Import Rubicon-ObjC and look up the shim's classes only on iOS, where the
   shim exists. The example does it in `main.py`:

    ```python
    from kivy.utils import platform

    demos = None
    if platform == "ios":
        import demos  # imports Rubicon-ObjC and looks up the shim's classes
    ```

## Write Swift that Python can call

Follow these rules for every class and method Python calls:

- **Subclass `NSObject` and give the class an explicit Objective-C name**,
  such as `@objc(SBNotebook)`. Without one, Swift generates a mangled name.
  A short prefix keeps your names apart from Apple's.
- **Give each method an explicit selector**, such as `@objc(addNote:)`. You
  then know exactly what Python calls it: the first part of the selector is
  the method name and each later part is a keyword argument, so `addNote:`
  is `addNote(...)` and `noteAtIndex:error:` is `noteAtIndex(..., error=...)`.
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

Look the class up with `ObjCClass` by its Objective-C name, then create an
instance with `alloc()` and an initialiser. An `@objc` property is a plain
attribute, and a `var` can be assigned:

```python
from rubicon.objc import ObjCClass

Notebook = ObjCClass("SBNotebook")

notebook = Notebook.alloc().initWithTitle("Groceries")
notebook.author = "Kivy"
count = notebook.addNote("apples and pears")
```

## Convert what Swift returns

A Swift `Int`, `Double` or `Bool` arrives as a Python `int`, `float` or
`bool`, and `nil` arrives as `None`. Everything else arrives as an object
that wraps the Objective-C value:

| Swift returns | Python receives |
|---|---|
| `String` | an `NSString` that formats and compares like a `str`, but is not one |
| `[String]`, `[Int]`, ... | an `NSArray` that behaves like a read-only list |
| `[String: Any]`, `[String: Int]`, ... | an `NSDictionary` that behaves like a read-only dictionary |
| an `NSObject` subclass | an object you can call methods on |

Call `str()` when you need a real `str`. `py_from_ns()` converts a whole
tree of strings, numbers, arrays and dictionaries to Python values:

```python
from rubicon.objc import py_from_ns

print(notebook.title)                   # Groceries
print(py_from_ns(notebook.notes))       # ['apples and pears']
print(py_from_ns(notebook.summary()))   # {'count': 1, 'isEmpty': 0, ...}
```

A Swift `Bool` inside a collection comes back from `py_from_ns()` as `0` or
`1`, not `False` or `True`, as `isEmpty` shows. Wrap it in `bool()` where the
type matters.

## Pass collections to Swift

Pass a Python `list` or `dict` as it is. Swift receives a list of strings as
`[String]`, and a dictionary with string keys as `[String: Any]`. Nested
lists and dictionaries convert too:

```python
notebook.addNotes(["more apples", "bread"])
notebook.applyOptions({"author": "Swift", "keepLast": 2})
```

## Call a method that throws

Swift exports a throwing method with an extra `error:` argument:

```swift
@objc(noteAtIndex:error:)
public func note(at index: Int) throws -> String
```

Pass a pointer to an `objc_id` for it. When the method throws, it returns
`None` and the pointer holds the `NSError`:

```python
from ctypes import byref

from rubicon.objc import ObjCInstance
from rubicon.objc.runtime import objc_id

error = objc_id()
note = notebook.noteAtIndex(10, error=byref(error))
if note is None:
    print("failed:", ObjCInstance(error).localizedDescription)
```

Return an object type, such as `String`, so that `None` means failure.

## Call an `async` method with a completion handler

Swift exports an `async` method as one whose last argument is a completion
handler. Give it an explicit selector that ends in `completionHandler:`:

```swift
@objc(SBWork)
public final class Work: NSObject {
    @objc(notificationSettingsWithCompletionHandler:)
    public static func notificationSettings() async -> [String: Any] {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        return ["authorizationStatus": settings.authorizationStatus.rawValue]
    }
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


Work.notificationSettingsWithCompletionHandler(done)
```

Write every completion handler to these rules:

- **Annotate every parameter and the return.** Rubicon-ObjC builds the
  handler's Objective-C signature from the annotations, and raises
  `ValueError` without them. Use `objc_id` for an object, and `-> None`.
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
alive until Swift releases the handler. Rubicon-ObjC passes a Python function
wherever Objective-C expects a block, so an API that takes another kind of
closure, such as a sort comparator, takes one the same way: annotate it to
match the block's signature.

## Report progress and cancel: poll a job

A completion handler is called once, at the end, and cannot stop the work.
For long work that should report progress or be cancellable, have the shim
start the work and return an object that holds its state, and poll that
object from Kivy's `Clock`. The example's `SBJob` does this:

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
    @objc(countPrimesBelow:)
    public static func countPrimes(below limit: Int) -> Job {
        Job { job in
            // calls Task.checkCancellation() and job.report(progress:)
            // as it goes, and returns the count
        }
    }
}
```

On the Python side, poll until the job finishes, then read the result:

```python
from kivy.clock import Clock
from rubicon.objc import py_from_ns


class JobWatcher:
    _active = set()

    def __init__(self, job, on_result):
        self.job = job
        self.on_result = on_result
        JobWatcher._active.add(self)
        Clock.schedule_interval(self._poll, 0.1)

    def _poll(self, _dt):
        if not self.job.isFinished:
            print(f"{self.job.progress:.0%}")
            return True  # keep polling
        JobWatcher._active.discard(self)
        if str(self.job.state) == "done":
            self.on_result(py_from_ns(self.job.result))
        return False  # stop polling


watcher = JobWatcher(Work.countPrimesBelow(10_000_000), print)
# to stop it early: watcher.job.cancel()
```

!!! warning "Keep the watcher alive"
    Kivy's `Clock` holds a bound method only weakly. If nothing else refers
    to the watcher, it is garbage-collected and polling stops without an
    error. `_active` holds each watcher until its job finishes.

Polling costs one call into Swift per job per tick. It runs on Kivy's
thread, so the poll can update widgets directly.

## Implement a Swift delegate in Python

Swift calls back into an app through a delegate protocol, the way UIKit
does. To implement one in Python:

1. Declare the protocol in the shim with an explicit name, and give the
   class a `weak` delegate property:

    ```swift
    @objc(SBMetronomeDelegate)
    public protocol MetronomeDelegate: NSObjectProtocol {
        @objc(metronome:didTick:)
        func metronome(_ metronome: Metronome, didTick count: Int)

        @objc(metronome:didStopWithSummary:)
        optional func metronome(_ metronome: Metronome, didStopWithSummary summary: [String: Any])

        @objc(metronome:shouldContinueAfter:)
        optional func metronome(_ metronome: Metronome, shouldContinueAfter count: Int) -> Bool
    }

    @objc(SBMetronome)
    public final class Metronome: NSObject {
        @objc public weak var delegate: MetronomeDelegate?
        // ...
    }
    ```

2. In Python, subclass `NSObject` and name the protocol. Mark each method
   with `@objc_method`; its name maps to the selector with an underscore for
   each colon. Annotate each parameter that is not an object: a Swift `Int`
   is `NSInteger`, and a `Bool` return is `bool`. Unannotated parameters
   arrive as objects you can call methods on:

    ```python
    from rubicon.objc import NSObject, ObjCProtocol, objc_method, py_from_ns
    from rubicon.objc.types import NSInteger


    class MetronomeListener(NSObject, protocols=[ObjCProtocol("SBMetronomeDelegate")]):
        @objc_method
        def metronome_didTick_(self, metronome, count: NSInteger) -> None:
            print("tick", count)

        @objc_method
        def metronome_didStopWithSummary_(self, metronome, summary) -> None:
            print("stopped", py_from_ns(summary))

        @objc_method
        def metronome_shouldContinueAfter_(self, metronome, count: NSInteger) -> bool:
            return count < 6
    ```

3. Create the delegate, keep a reference to it, and assign it:

    ```python
    listener = MetronomeListener.alloc().init()
    metronome = ObjCClass("SBMetronome").alloc().init()
    metronome.delegate = listener
    metronome.start()
    ```

Swift reads the return value, so the metronome stops after six ticks. Write
every delegate class to these rules:

- **Define the class once, at module level.** It is a real Objective-C class,
  and class names are global to the process: defining the same name twice
  raises `RuntimeError`.
- **Keep a reference to the delegate.** A delegate property is usually
  `weak`, so Swift does not keep the object alive. Hold it for as long as
  Swift should call it, as the example's `MetronomeDemo` does.
- **An exception is printed, not raised.** Python prints the traceback, and
  Swift reads `0`, `false` or `nil` as the method's return value. Later calls
  work normally. Catch the exception yourself if a wrong return value would
  matter.
- **Expect to run on the caller's thread.** If Swift calls the delegate from
  a background thread, your Python method runs on that thread. Code that
  changes widgets must run on Kivy's thread. The simplest fix is in the shim:
  call the delegate from the main thread, with a main-thread `Timer` as the
  metronome does or with `DispatchQueue.main.async { ... }`.

You can set Python attributes on the instance, such as a callback
(`listener.log = print`), and read them from its methods. The main thread's
run loop runs while Kivy runs, so a `Timer` or `DispatchQueue.main` in the
shim fires on time.

## Use pyobjus instead

If your app already uses [pyobjus](pyobjus.md), for example for plyer's iOS
facades, it can call the same shim without adding Rubicon-ObjC. Look the
class up with `autoclass`, and write each colon in a selector as an
underscore:

```python
from pyobjus import autoclass

Notebook = autoclass("SBNotebook")
notebook = Notebook.alloc().initWithTitle_("Groceries")
note = notebook.noteAtIndex_error_(0, None)
```

pyobjus 1.2.5 reaches less of Swift. It cannot pass a Python function as a
completion handler or other closure, so every `async` method needs a polled
job; a delegate method's return value never reaches Swift; and it does not
return the `NSError` from a throwing method. Its defects with a dictionary
argument, a nested list and an exception in a delegate method each need a
workaround.
[Use pyobjus](pyobjus.md#know-what-pyobjus-gets-wrong-on-ios)
lists them with their fixes.

## Verify

Build and run the example on the Simulator:

```bash
cd examples/mobile/swift-bridge
kivyforge lock -p ios
kivyforge build -p ios --simulator
kivyforge run -p ios --simulator
```

Tap each button. The log shows the converted results, the error from the
throwing method, the completion handlers' results, the prime count's
progress and its cancellation, and the metronome's ticks arriving in Python
until the delegate tells Swift to stop.

## Call the shim on macOS

The same shim and the same Python work in a macOS app, with two differences:

- Declare the package under `[tool.kivy.macos.native.swift_packages]`,
  without `link` or `embed`.
- Nothing loads the shim at launch. Load the framework kivyforge builds before
  you look up a class:

    ```python
    import sys
    from pathlib import Path

    from rubicon.objc.runtime import load_library

    frameworks = Path(sys.prefix).parents[1] / "Frameworks"
    load_library(str(frameworks / "KivyforgePackages.framework" / "KivyforgePackages"))
    ```

[Add a Swift package to your macOS app](../macos/swift-packages.md) explains
the build. The `swift-bridge` example itself stays iOS-only, because its UI
needs Kivy 3, which has no macOS wheel yet.

## Things to know

- **When you need more than a shim.** A shim keeps Python's view of Swift to
  a few `@objc` classes, which is usually what an app wants. If you need
  Python to see Swift structs, generics or enums with associated values, or
  Swift to hold Python objects as ordinary values, you need a binding tool
  that generates a CPython extension module instead. kivyforge does not
  register extension modules built from Swift yet.

## What's next

- [Add a Swift package](swift-packages.md) to wrap a remote package with the
  shim, as the `keychain-spm` example does.
- [Run code in the iOS app lifecycle](lifecycle-hooks.md) for app-delegate
  callbacks that arrive before Python starts.
- [Run your iOS app on the simulator or a device](run.md).
