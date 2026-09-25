---
title: Handle mobile screen geometry
sources:
  - docs/design/platforms/ios/04-cli-ios.md
  - docs/design/platforms/android/06-cli-android.md
  - docs/design/dev/roadmap.md
  - examples/mobile/android-safe-area/src/main.py
  - examples/mobile/android-safe-area/pyproject.toml
  - examples/mobile/mobile-geometry/src/main.py
---

# Handle mobile screen geometry

Phones have notches, rounded corners, system bars, and on-screen keyboards that
cover part of the window. Kivy 3.0 reports the geometry you need to lay out
around them through its `kivy.mobile` module. This page shows how to pad your
layout by the safe-area insets on Android and iOS.

`kivy.mobile` is part of Kivy, not kivyforge. kivyforge adds nothing to your app
for it.

## Before you begin

- A configured [Android](../android/configure.md) or [iOS](../ios/configure.md)
  app that depends on Kivy 3.0. `kivy.mobile` doesn't exist in Kivy 2.3.1.
- On Android, `kivy_generation = 3` in `[tool.kivy.android]`, and `pyjnius` in
  `[project].dependencies`.
- For safe-area insets on Android, a device or emulator running API level 30 or
  higher. Below API 30, the insets are all zero.

## What `kivy.mobile` provides

| Function | Returns |
|---|---|
| `get_safe_area()` | A dict with `top`, `left`, `bottom`, and `right` insets. |
| `get_scale()` | The display scale factor. |
| `get_dpi()` | The display's dots per inch. |
| `get_density()` | The display density. |
| `get_keyboard_height()` | The height of the on-screen keyboard, `0` when hidden. |
| `subscribe_keyboard_height(callback)` | Registers a callback for keyboard height changes. |

`kivy.mobile` works only on Android and iOS. Guard the import so the same code
also runs on the desktop.

## Pad your layout by the safe area

1. Add a helper that returns the insets in Kivy pixels. `get_safe_area()`
   returns pixels on Android but points on iOS, so scale only on iOS:

    ```python
    from kivy.utils import platform


    def safe_area_insets():
        """Return [left, top, right, bottom] in Kivy pixels."""
        if platform not in ("ios", "android"):
            return [0, 0, 0, 0]
        import kivy.mobile as mobile

        insets = mobile.get_safe_area()
        scale = mobile.get_scale() if platform == "ios" else 1.0
        return [insets[side] * scale for side in ("left", "top", "right", "bottom")]
    ```

2. Apply the insets as padding on your root layout, and refresh them on the next
   frame and whenever the window resizes, because they change with rotation:

    ```python
    from kivy.clock import Clock
    from kivy.core.window import Window
    from kivy.uix.boxlayout import BoxLayout


    class Root(BoxLayout):
        def on_kv_post(self, base_widget):
            Clock.schedule_once(self.refresh_insets, 0)
            Window.bind(on_resize=lambda *_: Clock.schedule_once(self.refresh_insets, 0))

        def refresh_insets(self, *_):
            self.padding = safe_area_insets()
    ```

## Verify

Run the app on a device or emulator with a notch or gesture navigation:

=== "Android"
    ```bash
    kivyforge run -p android
    ```

=== "iOS"
    ```bash
    kivyforge run -p ios --simulator
    ```

Confirm that no content sits under the status bar, the notch, or the navigation
area, and that it stays clear after you rotate the device.

The `android-safe-area` example in the kivyforge repository paints the unsafe
region red so you can see the insets. The `mobile-geometry` example displays every
value `kivy.mobile` reports, including the live keyboard height.

## What's next

- [Run on a device or emulator](../android/run.md) or
  [run on the simulator or a device](../ios/run.md)
- [Configure your Android app](../android/configure.md) or
  [configure your iOS app](../ios/configure.md)
