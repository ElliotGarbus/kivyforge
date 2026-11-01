---
title: Use pyobjus
sources:
  - docs/design/dev/ios-webview-spike-findings.md
  - docs/design/dev/swift-bridge-spike-findings.md
---

# Use pyobjus

[pyobjus](https://github.com/kivy/pyobjus) is Kivy's bridge to the
Objective-C runtime. kivyforge's guides and examples use
[Rubicon-ObjC](rubicon.md) instead, which reaches more of iOS and of Swift
with fewer workarounds. pyobjus is still supported, and you need it when:

- your app already uses it, and you are moving it to kivyforge;
- you use a package that imports it, such as
  [plyer's iOS facades](#use-plyers-ios-facades).

This page shows you how to add pyobjus, how its calls differ from
Rubicon-ObjC's, and what it gets wrong on iOS. The two bridges can be used in
one app, so code you write with Rubicon-ObjC keeps working next to pyobjus.

## Before you begin

- [Configure your iOS app](configure.md), including the mobile wheel index in
  `extra_index_urls`. The iOS `pyobjus` wheel resolves from that index.

## Add pyobjus

1. Add `pyobjus` to your dependencies:

    ```toml
    [project]
    dependencies = [
        "kivy>=3.0.0.dev0,<4",
        "pyobjus",
    ]
    ```

2. Lock the project:

    ```bash
    kivyforge lock -p ios
    ```

!!! note
    pyobjus works only on iOS. Import it inside a platform check and provide a
    fallback, so the app still runs when you test it elsewhere:

    ```python
    from kivy.utils import platform

    if platform == "ios":
        from pyobjus import autoclass
    ```

## Call an iOS framework class

`autoclass` returns a proxy for an Objective-C class. This example reads the
device name and system version through `UIDevice`. Unlike Rubicon-ObjC,
pyobjus calls a class property such as `currentDevice` as a method, and writes
each colon in a selector as an underscore. Instance properties are plain
attributes; `NSString` values come back as proxies, which you convert with
`UTF8String()`:

```python
from pyobjus import autoclass


def nsstr(value):
    raw = value.UTF8String()
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


device = autoclass("UIDevice").currentDevice()
print(nsstr(device.name))
print(nsstr(device.systemName), nsstr(device.systemVersion))
```

## Call your own Swift shim

When you [add a Swift package](swift-packages.md) that exposes an `@objc` class,
look the class up by its Objective-C runtime name. The `keychain-spm` example
declares `@objc(KeychainBridge)` with class methods such as
`@objc(storeString:forKey:)`. pyobjus maps each colon in a selector to an
underscore:

```python
from pyobjus import autoclass

KeychainBridge = autoclass("KeychainBridge")
KeychainBridge.storeString_forKey_("secret", "token")
value = KeychainBridge.stringForKey_("token")
```

The shim framework is linked and embedded, so it loads at launch, and its load
commands bring in the Swift package it wraps.

[Call Swift from Python](swift.md) goes further: instances, collections,
methods that throw, `async` work and delegates. It uses Rubicon-ObjC; the
defects below say where pyobjus falls short.

## Know what pyobjus gets wrong on iOS

- **`load_framework` does nothing.** `pyobjus.dylib_manager.load_framework`
  uses the macOS framework path, finds nothing on iOS and raises nothing, so
  `autoclass` then fails with `Unable to find class`. To use a system framework
  your app doesn't link, such as WebKit, open its binary with ctypes instead:
  `ctypes.CDLL("/System/Library/Frameworks/WebKit.framework/WebKit")`.
- **Passing a `CGRect` by value corrupts memory.** pyobjus 1.2.4 copies a
  struct argument into a buffer too small for any struct over 16 bytes
  ([kivy/pyobjus#90](https://github.com/kivy/pyobjus/issues/90)). A
  `CGRect` then reaches the method with its size zeroed on some launches and
  intact on others, and the heap is damaged either way; on iOS 27 the app can
  crash. `CGPoint` and `CGSize` fit. Object, string, integer and
  floating-point arguments, and returned structs, are fine. Send a `CGRect`
  argument, such as a frame, through `objc_msgSend` with ctypes. The fix,
  [kivy/pyobjus#157](https://github.com/kivy/pyobjus/pull/157), is not in a
  released pyobjus yet.

Rubicon-ObjC has neither defect: its `load_library("WebKit")` loads the
framework, and it passes a `CGRect` by value.
[Replace the kivy-ios ios module](ios-module.md) shows a web view built that
way.

Calling a Swift shim with pyobjus 1.2.5 meets these as well. Each has an open
fix in pyobjus; until a pyobjus wheel that includes it is published, follow
the workaround, which stays correct after the fix:

| Defect | Workaround | Fix |
|---|---|---|
| A plain `dict` argument arrives with keys and values swapped, which crashes a Swift method that expects `[String: Any]` | pass `pyobjus.objc_dict(d)` | [kivy/pyobjus#180](https://github.com/kivy/pyobjus/pull/180) |
| A delegate method's return value is dropped: Swift reads `false`, `0` or `nil` | return nothing; make the answer a property the app sets | [kivy/pyobjus#181](https://github.com/kivy/pyobjus/pull/181) |
| An exception that escapes a delegate method is never cleared: the next call into the delegate ends the app, or the error surfaces later in unrelated code | `try`/`except` in every delegate method | [kivy/pyobjus#181](https://github.com/kivy/pyobjus/pull/181) |
| A list nested in a list can crash a call | pass flat lists, or a JSON string | [kivy/pyobjus#182](https://github.com/kivy/pyobjus/pull/182) |

Three more limits have no fix in progress:

- **No closures.** pyobjus cannot pass a Python function where Objective-C
  expects a block, so a Swift `async` method or any completion handler
  cannot call back into Python. Have the shim return an object that holds
  the outcome, and poll it from Kivy's `Clock`.
- **No `NSError`.** A throwing method, called with `None` for `error:`,
  returns `None` when it throws but does not hand Python the error. Have the
  shim keep the reason in a property.
- **Struct arguments to delegate methods.** pyobjus copies each delegate
  argument into a pointer-sized slot, so a larger struct, such as a
  `CGRect`, cannot arrive intact. Pass the fields as separate numbers.

pyobjus also keeps every Python object it turns into a delegate alive for
the life of the app, so create one delegate and reuse it.

## Use plyer's iOS facades

Most of [plyer](https://github.com/kivy/plyer)'s iOS facades, `filechooser`
among them, call iOS through pyobjus, so add `pyobjus` to your dependencies
before you use them.

## Verify

Run the app on the Simulator and confirm that the values appear:

```bash
kivyforge run -p ios --simulator
```

## What's next

- [Call iOS APIs with Rubicon-ObjC](rubicon.md).
- [Add a Swift package to your iOS app](swift-packages.md).
- [Call Swift from Python](swift.md).
- [Replace the kivy-ios ios module](ios-module.md).
- [Run your iOS app on the simulator or a device](run.md).
- [Handle mobile screen geometry](../cross-platform/mobile-geometry.md).
