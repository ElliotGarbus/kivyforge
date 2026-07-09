# Dice Roller — desktop Kivy example

A tiny Kivy app: tap **Roll** to roll two dice. Uses only stdlib + core Kivy
widgets. This is a **desktop** example — it uses Kivy 2.3.1 from PyPI. (Mobile
targets require Kivy 3.0; see the examples under `examples/mobile/`.)

## macOS (builds today from PyPI)

macOS bundles a [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
CPython 3.13 runtime and Kivy 2.3.1's universal2 wheel straight from PyPI — no
wheel-building step.

```bash
cd examples/desktop/dice-roller
kivyforge lock -p macos
kivyforge build -p macos        # add --arch arm64 for a faster thin build
kivyforge run  -p macos         # launches the .app
# distributable, ad-hoc-signed bundle:
kivyforge package -p macos      # -> build/macos/Dice Roller.app
```

## Linux (builds today from PyPI)

The same `pyproject.toml` — now with a `[tool.kivy.linux]` overlay — bundles a
PBS CPython 3.13 gnu/glibc runtime and the Kivy 2.3.1 manylinux wheel from PyPI.
The folder artifact is an [AppDir](https://docs.appimage.org/); `package`
wraps it into a single AppImage with an embedded static-FUSE runtime.

```bash
cd examples/desktop/dice-roller
kivyforge lock    -p linux
kivyforge build   -p linux      # -> build/linux/Dice Roller.AppDir
kivyforge run     -p linux      # runs ./AppRun directly (no FUSE)
kivyforge package -p linux      # -> dist/linux/dice-roller-0.1.0-x86_64.AppImage
```

**Host contract:** the AppImage bundles Python + wheels but never libGL/libEGL or
a display server. The host must provide glibc ≥ the effective floor (2.17 here),
`libGL.so.1`/`libEGL.so.1`, and an X11 or Wayland session. No `libfuse2` is
needed (static-FUSE runtime); `./app.AppImage --appimage-extract-and-run` is the
universal no-FUSE fallback. Run `kivyforge doctor -p linux` to check the host.

## Files

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Identity + `[tool.kivy.macos]` / `[tool.kivy.linux]` overlays |
| `pylock.macos.toml` | Pinned CPython 3.13 (PBS) + Kivy 2.3.1 universal2 wheel |
| `pylock.linux.toml` | Pinned CPython 3.13 (PBS gnu) + Kivy 2.3.1 manylinux wheel |
| `src/main.py` | The app (dice faces are canvas-drawn, not font glyphs) |
| `src/icon.png` | 512×512 runtime window/Dock icon (bundled with the app) |
| `assets/icon.png` | 1024×1024 macOS icon — transparent rounded corners → `.icns` |

## App icons

Two icons are set by two different systems:

- **macOS bundle** (`[tool.kivy.macos.icons]`) → `assets/icon.png`, a squircle with
  **transparent** rounded corners, rendered into the `.app`'s `.icns`.
- **Runtime window/Dock icon** → `src/icon.png`, set via `Window.set_icon()` /
  `App.icon` so the running app shows the dice instead of Kivy's default logo. It
  lives under `src/` so it's bundled and resolvable at runtime.
