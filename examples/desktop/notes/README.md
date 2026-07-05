# Notes — desktop Kivy example with a pure-Python dependency

A one-note editor that persists to the OS per-user data directory. Demonstrates a
**pure-Python dependency** (`platformdirs`) resolved into the bundle alongside
Kivy — on macOS the note lands under `~/Library/Application Support`. This is a
**desktop** example (Kivy 2.3.1 from PyPI); mobile targets need Kivy 3.0, see
`examples/mobile/`.

## macOS (builds today from PyPI)

```bash
cd examples/desktop/notes
kivyforge lock -p macos
kivyforge build -p macos
kivyforge run  -p macos
```

macOS bundles a python-build-standalone CPython 3.13 runtime plus Kivy 2.3.1 and
`platformdirs` from PyPI (universal2 / pure-Python wheels).

## Files

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Deps (`kivy`, `platformdirs`) + `[tool.kivy.macos]` overlay |
| `pylock.macos.toml` | Pinned CPython 3.13 (PBS) + Kivy 2.3.1 + platformdirs |
| `src/main.py` | The app |
| `src/icon.png` | 512×512 runtime window/Dock icon (bundled with the app) |
| `assets/icon.png` | 1024×1024 macOS icon — transparent rounded corners → `.icns` |
