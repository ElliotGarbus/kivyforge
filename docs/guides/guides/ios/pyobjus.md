---
title: Call iOS APIs with pyobjus
sources:
  - examples/mobile/pyobjus-deviceinfo/pyproject.toml
  - examples/mobile/keychain-spm/pyproject.toml
---

# Call iOS APIs with pyobjus

[pyobjus](https://github.com/kivy/pyobjus) bridges Python and Objective-C, so
your app can call the iOS frameworks and any `@objc` class you ship. This page
shows you how to add pyobjus and call both kinds of class.

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
    fallback, so the app still runs when you test it elsewhere. The
    `pyobjus-deviceinfo` example does this:

    ```python
    from kivy.utils import platform

    if platform == "ios":
        from pyobjus import autoclass
    ```

## Call an iOS framework class

`autoclass` returns a proxy for an Objective-C class. This example reads the
device name and system version through `UIDevice`. Objective-C properties are
plain attributes; `NSString` values come back as proxies, which you convert with
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
  intact on others, and the heap is damaged either way. `CGPoint` and
  `CGSize` fit. Object, string, integer and floating-point arguments, and
  returned structs, are fine. Send a `CGRect` argument, such as a frame,
  through `objc_msgSend` with ctypes.

The `ios-webview` example (`examples/mobile/ios-webview`) does both, and
[Replace the kivy-ios ios module](ios-module.md) prints the working code.

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

- [Add a Swift package to your iOS app](swift-packages.md).
- [Replace the kivy-ios ios module](ios-module.md).
- [Run your iOS app on the simulator or a device](run.md).
- [Handle mobile screen geometry](../cross-platform/mobile-geometry.md).
