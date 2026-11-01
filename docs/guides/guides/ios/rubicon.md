---
title: Call iOS APIs with Rubicon-ObjC
sources:
  - examples/mobile/rubicon-deviceinfo/src/main.py
  - examples/mobile/rubicon-ball/src/main.py
  - examples/mobile/ios-webview/src/main.py
  - examples/mobile/keychain-spm/src/main.py
  - docs/design/dev/swift-bridge-spike-findings.md
---

# Call iOS APIs with Rubicon-ObjC

[Rubicon-ObjC](https://github.com/beeware/rubicon-objc), BeeWare's bridge to
the Objective-C runtime, lets your app call the iOS frameworks and any `@objc`
class you ship. It is the bridge kivyforge's examples and guides use. This
page shows you how to add it and call a framework class.

## Before you begin

- [Configure your iOS app](configure.md).
- Have the `rubicon-deviceinfo` example from the kivyforge repository at hand
  (`examples/mobile/rubicon-deviceinfo`). The first snippets on this page come
  from it.

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
    It does not need the mobile wheel index. Version 0.5.7 is the one tested
    here, and it supports CPython 3.15.

2. Lock the project:

    ```bash
    kivyforge lock -p ios
    ```

3. Import Rubicon-ObjC only on iOS, and give the app a fallback so it still
   runs when you test it on a desktop:

    ```python
    from kivy.utils import platform

    if platform == "ios":
        from rubicon.objc import ObjCClass
    ```

## Call an iOS framework class

Look a class up with `ObjCClass` by its Objective-C name. An Objective-C
property, including a class property such as `currentDevice`, is a plain
attribute, read without a call, and a writable one can be assigned:

```python
from rubicon.objc import ObjCClass

device = ObjCClass("UIDevice").currentDevice
device.batteryMonitoringEnabled = True
print(device.name, device.systemVersion)
print(ObjCClass("NSProcessInfo").processInfo.processorCount)
```

A method is called. The first part of its selector is the method name and
each later part is a keyword argument, so `URLWithString:` is
`URLWithString(...)` and `storeString:forKey:` is
`storeString(..., forKey=...)`:

```python
NSURL = ObjCClass("NSURL")
url = NSURL.URLWithString("https://kivy.org")
```

Pass a Python `str`, number, `bool`, `list` or `dict` where Objective-C
expects one; Rubicon-ObjC converts it. What comes back follows these rules:

| Objective-C returns | Python receives |
|---|---|
| `BOOL`, an integer, a float | a Python `bool`, `int` or `float` |
| `nil` | `None` |
| `NSString` | an object that formats and compares like a `str`, but is not one: call `str()` for a real one |
| `NSArray`, `NSDictionary` | an object that behaves like a read-only list or dictionary; `py_from_ns()` converts the whole tree |
| any other object | an object you can read properties from and call methods on |
| a C struct | a `ctypes` structure (see [Pass and return structs](#pass-and-return-structs)) |

## Load a framework your app does not link

A class exists only once its framework is loaded. Foundation, UIKit and the
frameworks SDL links, such as CoreMotion, are loaded at launch. Others, such
as WebKit, are not. Load one with `load_library` before you look up its
classes:

```python
from rubicon.objc import ObjCClass
from rubicon.objc.runtime import load_library

load_library("WebKit")
WKWebView = ObjCClass("WKWebView")
```

On iOS, `load_library` opens
`/System/Library/Frameworks/<name>.framework/<name>`, which iOS resolves from
its shared cache on a device and on the Simulator.

## Pass and return structs

Rubicon-ObjC passes and returns C structs as `ctypes` structures, and ships
the common geometry types:

```python
from rubicon.objc import CGPoint, CGRect, CGSize

web_view = WKWebView.alloc().init()
web_view.frame = CGRect(CGPoint(20, 80), CGSize(300, 400))
frame = web_view.frame
print(frame.origin.x, frame.size.width)
```

A struct Apple declares without a name, such as CoreMotion's
`CMAcceleration`, comes back with fields named `field_0`, `field_1` and so
on. Register your own structure for its type encoding to name them:

```python
import ctypes

from rubicon.objc.types import register_encoding


class CMAcceleration(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double)]


register_encoding(b"{?=ddd}", CMAcceleration)

acceleration = motion_manager.accelerometerData.acceleration
print(acceleration.x, acceleration.y)
```

The `rubicon-ball` example steers a ball with it.

## Call your own Swift or Objective-C class

A class from a package you [add](swift-packages.md) is looked up the same way,
by the name its `@objc(...)` attribute gives it. The `keychain-spm` example's
shim declares `@objc(KeychainBridge)` with class methods such as
`@objc(storeString:forKey:)`:

```python
KeychainBridge = ObjCClass("KeychainBridge")
KeychainBridge.storeString("secret", forKey="token")
value = KeychainBridge.stringForKey("token")
```

[Call Swift from Python](swift.md) covers writing the shim, and calling
methods that throw, `async` work through completion handlers, and delegates
implemented in Python.

## Things to know

- **UIKit calls belong on the main thread**, which is where Kivy runs your
  event handlers and `Clock` callbacks. A completion handler or delegate
  method that iOS calls on another thread runs your Python on that thread:
  hand the rest of the work to Kivy's thread with `Clock.schedule_once`.
- **An exception in a method iOS calls is printed, not raised.** In a
  completion handler or a delegate method you implement in Python, the
  traceback is printed and the caller reads `0`, `false` or `nil`. Catch it
  yourself if that matters.
- **A class you define in Python is defined once per process.** Defining an
  `NSObject` subclass with the same name twice raises `RuntimeError`, so
  define it at module level.

## Use pyobjus instead

Rubicon-ObjC is the bridge this documentation uses. If your app already uses
pyobjus, or depends on a package that needs it, such as plyer's iOS facades,
[Use pyobjus](pyobjus.md) shows how to call the same classes with it and what
it gets wrong on iOS. The two bridges can be used in one app.

## Verify

Build and run the example on the Simulator:

```bash
cd examples/mobile/rubicon-deviceinfo
kivyforge lock -p ios
kivyforge build -p ios --simulator
kivyforge run -p ios --simulator
```

The app shows the device name, model, system version, memory and CPU count,
and its banner reads `Source: Rubicon-ObjC -> UIDevice / NSProcessInfo`. The
Simulator reports the battery as `n/a`.

## What's next

- [Call Swift from Python](swift.md).
- [Add a Swift package to your iOS app](swift-packages.md).
- [Run code in the iOS app lifecycle](lifecycle-hooks.md).
- [Replace the kivy-ios ios module](ios-module.md).
- [Handle mobile screen geometry](../cross-platform/mobile-geometry.md).
