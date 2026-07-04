# Dice Roller — cross-platform Kivy example

A tiny Kivy app: tap **Roll** to roll two dice. Uses only stdlib + core Kivy
widgets, so the same `src/main.py` runs on macOS and iOS.

## macOS (builds today from PyPI)

macOS bundles a [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
CPython 3.13 runtime and Kivy 2.3.1's universal2 wheel straight from PyPI — no
wheel-building step.

```bash
cd examples/cross_platform/dice-roller
kivyforge lock -p macos
kivyforge build -p macos        # add --arch arm64 for a faster thin build
kivyforge run  -p macos         # launches the .app
# distributable, ad-hoc-signed bundle:
kivyforge package -p macos      # -> build/macos/Dice Roller.app
```

## iOS

Uses the Kivy 3.0 iOS wheels vendored in `examples/wheels/ios/`.

```bash
kivyforge lock -p ios
kivyforge run  -p ios --simulator
```

## Files

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Shared identity + `[tool.kivy.macos]` / `[tool.kivy.ios]` overlays |
| `pylock.macos.toml` | Pinned CPython 3.13 (PBS) + Kivy 2.3.1 universal2 wheel |
| `src/main.py` | The app |
