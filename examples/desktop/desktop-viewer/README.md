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
cd examples/desktop/desktop-viewer
kivyforge lock -p macos
kivyforge build -p macos        # universal2 by default; --arch arm64 for a thin build
kivyforge run  -p macos
kivyforge package -p macos      # -> build/macos/Desktop Viewer.app (ad-hoc signed)
```

Bundles a python-build-standalone CPython 3.13 runtime and Kivy 2.3.1's
universal2 wheel from PyPI.

## Linux (builds today from PyPI)

The same overlay pattern targets Linux (AppDir + AppImage). The window,
resizable layout, and font-size shortcuts all work; the **native open panel is
macOS-only** — `⌘O` calls `osascript`, which is absent on Linux, so it's a
graceful no-op there (the app doesn't crash). A cross-platform file chooser is
out of scope for this deliberately macOS-flavoured demo.

```bash
cd examples/desktop/desktop-viewer
kivyforge lock    -p linux
kivyforge build   -p linux      # -> build/linux/Desktop Viewer.AppDir
kivyforge run     -p linux      # runs ./AppRun directly (no FUSE)
kivyforge package -p linux      # -> dist/linux/desktop-viewer-0.1.0-x86_64.AppImage
```

**Host contract:** the host provides glibc ≥ the effective floor (2.17 here),
`libGL.so.1`/`libEGL.so.1`, and an X11/Wayland session; the bundle vendors
neither. No `libfuse2` needed (static-FUSE runtime);
`--appimage-extract-and-run` is the universal no-FUSE fallback. Check the host
with `kivyforge doctor -p linux`.

## Files

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Identity + `[tool.kivy.macos]` / `[tool.kivy.linux]` overlays (no iOS) |
| `pylock.macos.toml` | Pinned CPython 3.13 (PBS) + Kivy 2.3.1 universal2 wheel |
| `pylock.linux.toml` | Pinned CPython 3.13 (PBS gnu) + Kivy 2.3.1 manylinux wheel |
| `src/main.py` | The app |
| `src/icon.png` | 512×512 runtime window/Dock icon (bundled with the app) |
| `assets/icon.png` | 1024×1024 master app icon (rendered into the bundle's `.icns`) |

## App icon

There are **two** icons, because they're set by two different systems:

1. **Bundle icon** (Finder, `/Applications`, and the Dock/Cmd-Tab entry for the
   *installed* app). `[tool.kivy.macos.icons].source` points at a **1024×1024
   PNG**; at build time kivyforge renders it into
   `Contents/Resources/desktop-viewer.icns` (via `sips` + `iconutil`) and sets
   `CFBundleIconFile`.
2. **Runtime window icon** (the Dock/taskbar icon *while the app is running*).
   Kivy shows its own default logo unless the app sets it, so `src/main.py` calls
   `Window.set_icon()` (and sets `App.icon`) with `src/icon.png`. It lives under
   `src/` so the bundler copies it into `Contents/Resources/app/` and a path
   relative to `main.py` resolves both in the `.app` and during a plain
   `python src/main.py` dev run.
