---
title: Understand the Windows launcher
sources:
  - docs/design/platforms/windows/bootloader-windows.md
  - docs/design/platforms/windows/windows-spec.md
  - FAQ.md
---

# Understand the Windows launcher

Every kivyforge Windows bundle ships a small native launcher `.exe`. This page
explains what the launcher does, how it behaves when started from Explorer and
from a terminal, and why you ship the launcher instead of `python.exe`.

## What the launcher is

The launcher is one prebuilt, windowed-subsystem executable that serves every
app. kivyforge does not compile it on your machine. It copies the vendored
binary into your bundle as `DISPLAY_NAME.exe` and patches only its icon and
version resources.

When it starts, the launcher:

1. Finds its own folder, and derives the bundle layout from there rather than
   from the current directory.
2. Points the bundled runtime at the bundle by setting `PYTHONHOME`,
   `PYTHONPATH`, and `PYTHONNOUSERSITE=1`.
3. Starts the bundled `python\python.exe` on the generated
   `_kivyforge_bootstrap.py`, passing through any command-line arguments.
4. Puts that process in a Windows Job object, so that closing the launcher
   also ends every process the app started.
5. Waits for the app and exits with its exit code.

Everything app-specific lives in `_kivyforge_bootstrap.py` at the bundle root.
The bootstrap sets your `app_id` as the AppUserModelID before any window
opens, registers the runtime's native DLL folders and any
[native binaries](../cross-platform/native-binaries.md) in `bin\`, and runs your
entry-point module as `__main__`.

## How your app starts

Double-click in Explorer
:   There is no parent console, so the launcher starts Python without one.
    Your Kivy window opens with no console window. This is the path your users
    take.

From a terminal, or with `kivyforge run`
:   The launcher attaches to the terminal that started it, so the app's stdout,
    stderr, and tracebacks appear there. `kivyforge run -p windows` uses this to
    show you output while you develop.

## Ship the launcher, not python.exe

Always run and distribute the generated `DISPLAY_NAME.exe`. If you start
`python.exe` directly, you get a console window and none of the bootstrap's
setup: no AppUserModelID, no DLL folders, and no entry point. If a
double-clicked app shows a console window, check that the shortcut points at
the launcher.

## Troubleshoot a window that never appears

Start the launcher from a terminal, or use `kivyforge run -p windows`, to see
the traceback. A missing OpenGL backend or an import error in your app appears
there.

## The runtime is self-contained

The bundled runtime ships the core Visual C++ runtime DLLs
(`vcruntime140.dll`, `vcruntime140_1.dll`) beside `python.exe`. When the
runtime lacks the C++ runtime `msvcp140.dll`, kivyforge copies it into the
bundle from the build machine's `System32` folder if it is there. Your users do
not need to install the Visual C++ Redistributable.

## What's next

- [Build a Windows onedir app](build.md).
- [Sign a Windows app with Authenticode](signing.md).
- [Avoid Windows file-locking problems](file-locking.md).
