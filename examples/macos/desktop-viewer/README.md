# Desktop Viewer — macOS-only Kivy example

A deliberately **desktop-only** Kivy app: a resizable text viewer with a minimum
window size, Command-key shortcuts, and the **native macOS open panel** (Finder's
own file chooser, via `osascript`'s `choose file` — no extra dependencies) —
none of which map to a touch phone, so there is **no `[tool.kivy.ios]` overlay**.

| Shortcut | Action |
|----------|--------|
| ⌘O | Open a text file |
| ⌘+ / ⌘- | Increase / decrease font size |
| ⌘W / ⌘Q | Quit |

## Build & run (from PyPI, no wheel-building)

```bash
cd examples/macos/desktop-viewer
kivyforge lock -p macos
kivyforge build -p macos        # universal2 by default; --arch arm64 for a thin build
kivyforge run  -p macos
kivyforge package -p macos      # -> build/macos/Desktop Viewer.app (ad-hoc signed)
```

Bundles a python-build-standalone CPython 3.13 runtime and Kivy 2.3.1's
universal2 wheel from PyPI.

## Files

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Identity + `[tool.kivy.macos]` overlay (no iOS) |
| `pylock.macos.toml` | Pinned CPython 3.13 (PBS) + Kivy 2.3.1 universal2 wheel |
| `src/main.py` | The app |
