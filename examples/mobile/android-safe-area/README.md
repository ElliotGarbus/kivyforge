# android-safe-area

Makes the Android **safe area** visible: the app paints the whole window red,
then paints the region the system actually leaves to the app on top in dark
grey. Any red still showing is the status bar, the gesture-navigation pill, or
the display cutout. Rotate the device and the bands move.

## Why this example exists separately

`kivy.mobile` — the module that reports safe-area insets — **does not exist in
Kivy 2.3.1**. The other Android examples (`hello-android`, `qr-maven`,
`pyjnius-deviceinfo`) are on `kivy_generation = 2` and so cannot report a safe
area at all, and moving them to generation 3 would change what they
demonstrate. This example pins `kivy_generation = 3` instead, keeping the
generation-2 / generation-3 coverage split intact.

## Two things worth knowing

**Units differ per platform.** `get_safe_area()` returns **pixels** on Android,
which is already Kivy's layout coordinate system there, but UIKit **points** on
iOS, which must be scaled by `get_scale()`. Scaling on Android too would
inflate the padding by the display density (typically 2–3.5×). Kivy's own
`kivy/mobile/__init__.py` currently documents "layout points" for both, without
the per-platform caveat — following that doc verbatim over-pads Android.

**Typed `WindowInsets` needs API 30+.** Below that Kivy returns all-zero
insets. The app reports that case explicitly rather than just showing no red.

## Build and run

```bash
kivyforge lock -p android
kivyforge build -p android
kivyforge run -p android
```

The lock is gitignored, per the [example-repo lock
policy](../../../docs/design/common/03-lockfile-concept.md) — only the
on-device gate examples keep a committed lock as validation evidence.

Running `python src/main.py` on the desktop works as a smoke-test:
`kivy.mobile` is mobile-only and raises `ImportError` there, so the insets read
as zero, no red is visible, and the app says why.
