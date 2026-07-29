# hello-android

The smallest possible kivyforge Android app — a single Kivy `Label`.

```bash
kivyforge lock -p android
kivyforge build -p android --debug      # -> hello-android-android/app/build/outputs/apk/debug/app-debug.apk
kivyforge run -p android --emulator     # build, install, launch on an AVD
```

Wheels resolve from the [kivy-mobile-wheels](https://github.com/ElliotGarbus/kivy-mobile-wheels)
index. `<app>-android/` is generated and git-ignored; `pyproject.toml` and
`pylock.android.toml` are committed.

This is the **SDL2 on-device gate** (the SDL3 sibling is
[`hello-sdl3`](../hello-sdl3)), which is why its lock is tracked rather than
ignored — the lock is the evidence. It runs green on an x86_64 API-31 emulator
and on a Pixel 8a (Android 16 / API 36)
([findings](../../../docs/design/dev/android-loadmodel-findings.md)).

> Note the entry point calls `App().run()` at module top level — kivyforge
> **imports** the entry-point module, so an `if __name__ == "__main__":` guard
> would prevent the app from ever starting.
