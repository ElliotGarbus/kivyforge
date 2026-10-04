# android-package-sdl3

The `android-package` example on Kivy 3.0 (SDL3). It uses each part of the
`android` package that kivyforge bundles in every Android build. Its
`src/main.py` is a copy of `android-package/src/main.py`, and a test keeps the
two identical, so both generations run the same checks.

## Build and run

```bash
kivyforge lock -p android
kivyforge run -p android
```

Each check logs one line starting with `android-package:`:

```bash
adb logcat -s python.stdout | grep android-package
```

The steps and what counts as a pass are in
`docs/design/dev/hardware-checklist.toml`, item `android-package-sdl3`.

The lock is gitignored, per the [example-repo lock
policy](../../../docs/design/common/03-lockfile-concept.md) — only the
on-device gate examples keep a committed lock as validation evidence.
