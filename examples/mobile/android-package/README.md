# android-package

Uses each part of the `android` package that kivyforge bundles in every
Android build, on Kivy 2.3.1 (SDL2): the package's own names,
`android.storage`, `android.broadcast`, `android.darkmode`,
`android.activity`, `android.permissions`, and plyer, which imports it. It
also covers what Kivy 2.3.1 itself needs the package for: the numeric
keyboard, the back key, `App.stop()`, the clipboard and audio.

`android-package-sdl3` is the same app on Kivy 3.0 (SDL3).

## Build and run

```bash
kivyforge lock -p android
kivyforge run -p android
```

Each check logs one line starting with `android-package:`, and the app shows
the same lines:

```bash
adb logcat -s python.stdout | grep android-package
```

The checks that need nobody run at start. The buttons cover the rest: a
permission request, an activity result (open the file picker, then press
back), and `App.stop()`. Switch the phone between light and dark mode to see
the dark-mode listener fire. The steps and what counts as a pass are in
`docs/design/dev/hardware-checklist.toml`, item `android-package-gen2`.

The lock is gitignored, per the [example-repo lock
policy](../../../docs/design/common/03-lockfile-concept.md) — only the
on-device gate examples keep a committed lock as validation evidence.
