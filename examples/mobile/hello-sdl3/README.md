# hello-sdl3

The smallest kivyforge Android app on **Kivy 3.0 / SDL3** — the SDL2 sibling is
[`hello-android`](../hello-android). They are deliberately identical apart from
the SDL generation, so a difference between them is a difference in the
bootstrap, not the app.

```bash
kivyforge lock -p android
kivyforge build -p android
kivyforge run -p android --smoke        # contract smoke test
kivyforge run -p android                # launch it
```

Wheels resolve from the [kivy-mobile-wheels](https://github.com/ElliotGarbus/kivy-mobile-wheels)
index; Kivy 3.0 is unreleased, so the dependency specifier admits a `.dev`
version (pip skips pre-releases otherwise).
