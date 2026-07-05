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

## Files

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Identity + `[tool.kivy.macos]` overlay |
| `pylock.macos.toml` | Pinned CPython 3.13 (PBS) + Kivy 2.3.1 universal2 wheel |
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
