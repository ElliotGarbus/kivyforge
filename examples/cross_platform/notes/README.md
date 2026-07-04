# Notes — cross-platform Kivy example with a pure-Python dependency

A one-note editor that persists to the OS per-user data directory. Demonstrates a
**pure-Python dependency** (`platformdirs`) resolved into the bundle alongside
Kivy: on macOS the note lands under `~/Library/Application Support`, on iOS in
the app container.

## macOS (builds today from PyPI)

```bash
cd examples/cross_platform/notes
kivyforge lock -p macos
kivyforge build -p macos
kivyforge run  -p macos
```

macOS bundles a python-build-standalone CPython 3.13 runtime plus Kivy 2.3.1 and
`platformdirs` from PyPI (universal2 / pure-Python wheels).

## iOS

```bash
kivyforge lock -p ios
kivyforge run  -p ios --simulator
```

## Files

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Shared deps (`kivy`, `platformdirs`) + platform overlays |
| `pylock.macos.toml` | Pinned CPython 3.13 (PBS) + Kivy 2.3.1 + platformdirs |
| `src/main.py` | The app |
