# hello-sdl3

The smallest kivyforge Android app on **Kivy 3.0 / SDL3** — the SDL2 sibling is
[`hello-android`](../hello-android). They are deliberately identical apart from
the SDL generation, so a difference between them is a difference in the
bootstrap, not the app.

```bash
kivyforge lock -p android
kivyforge build -p android              # generate hello-sdl3-android/ (no APK without --debug)
kivyforge run -p android --smoke        # contract smoke test
kivyforge run -p android                # build, install, launch it
```

Wheels resolve from the [kivy-mobile-wheels](https://github.com/ElliotGarbus/kivy-mobile-wheels)
index; Kivy 3.0 is unreleased, so the dependency specifier admits a `.dev`
version (pip skips pre-releases otherwise).

This is the **SDL3 on-device gate**, which is why its lock is tracked rather
than ignored — the lock is the evidence. It runs green on an x86_64 API-31
emulator and on a Pixel 8a (Android 16 / API 36), where it renders on the
Mali-G715 with `Window`, `GL`, `text` and `img` all on `sdl3`
([findings](../../../docs/design/dev/android-loadmodel-findings.md#kivy-30--sdl3-on-device-first-run)).
