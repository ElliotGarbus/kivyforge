# android-fullscreen

Runs with the Android status bar and navigation bar hidden. A swipe in from the
top or bottom edge shows them for a few seconds, then they hide again. The only
setting involved is in `pyproject.toml`:

```toml
[tool.kivy.android]
fullscreen = true
```

## How it works

On Android, Kivy ignores its own `graphics.fullscreen` setting when it creates
the window. It reads the `P4A_IS_WINDOWED` environment variable instead, a name
inherited from python-for-android. With `fullscreen = true`, kivyforge's
generated activity sets it to `False`, Kivy creates a fullscreen SDL window, and
SDL hides the bars in immersive-sticky mode. The app's label shows the variable.

The generated theme also gets `android:windowFullscreen`, but only for the
moment before Python starts: `SDLActivity.onCreate` clears that flag, so a theme
on its own leaves the bars visible.

## Build and run

```bash
kivyforge lock -p android
kivyforge run -p android
```

The lock is gitignored, per the [example-repo lock
policy](../../../docs/design/common/03-lockfile-concept.md) — only the
on-device gate examples keep a committed lock as validation evidence.
