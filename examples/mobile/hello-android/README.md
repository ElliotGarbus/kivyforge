# hello-android

The smallest possible kivyforge Android app — a single Kivy `Label`.

```bash
kivyforge lock -p android
kivyforge build -p android --debug      # -> a debug APK
kivyforge run -p android --emulator     # build, install, launch on an AVD
```

The Kivy 2.3.1 + pyjnius wheels are vendored under
[`examples/wheels/android`](../../wheels/android/). `<app>-android/` is
generated and git-ignored; `pyproject.toml` and `pylock.android.toml` are
committed.

> Note the entry point calls `App().run()` at module top level — kivyforge
> **imports** the entry-point module, so an `if __name__ == "__main__":` guard
> would prevent the app from ever starting.
