---
title: Understand the Windows launcher
sources:
  - docs/design/platforms/windows/bootloader-windows.md
  - docs/design/platforms/windows/windows-spec.md
  - FAQ.md
  - kivyforge/platforms/windows/launcher/launcher.c
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

## Read the log of a packaged app

A packaged app started from Explorer has no console, so its output has nowhere
to appear. Kivy writes its own log to a file instead, in the `logs` folder of
Kivy's home directory. kivyforge doesn't set that directory, so where it is
depends on your Kivy version and your app:

Kivy 2.3, or Kivy 3.0 without `KIVY_DESKTOP_PATH_ID`
:   `%USERPROFILE%\.kivy\logs\kivy_YY-MM-DD_N.txt`. This folder is shared by
    every Kivy app on the machine. Kivy 3.0 also logs a warning that
    `KIVY_DESKTOP_PATH_ID` is not set.

Kivy 3.0 with `KIVY_DESKTOP_PATH_ID`
:   `%APPDATA%\PATH_ID\.kivy\logs\kivy_YY-MM-DD_N.txt`, one folder per app.
    Kivy turns the value into a safe folder name, so spaces become
    underscores: `"My Notes"` gives `%APPDATA%\My_Notes\.kivy\logs`. Kivy's
    config file and `App.user_data_dir` move under `%APPDATA%\PATH_ID` too.

`KIVY_HOME` overrides both on Kivy 2.3 and moves the log to `KIVY_HOME\logs`;
on Kivy 3.0, `KIVY_DESKTOP_PATH_ID` wins over it.

Kivy reads these variables when it is first imported. The launcher doesn't set
them, and the bootstrap doesn't import Kivy before your entry point, so set
them at the top of your entry-point module, before any `import kivy`:

```python
import os

os.environ.setdefault("KIVY_DESKTOP_PATH_ID", "My Notes")

from kivy.app import App
```

`YY-MM-DD` is the date and `N` counts the runs that day, so the newest file is
the last run. The first line of each file names it, so search for it when
you're not sure which folder the app used:
`[INFO   ] Logger: Record log in C:\Users\NAME\.kivy\logs\kivy_26-11-18_0.txt`.

The log has Kivy's messages, your app's `Logger` calls, and everything written
to stderr. Kivy sends stderr to the log, so an uncaught exception's traceback
is there, one line at a time, as `[WARNING] stderr:` lines. Output from
`print()` goes to stdout and is not in the log. Use `Logger.info()` for
messages you want to find later.

Kivy deletes the oldest files once the folder holds more than its
`log_maxfiles` setting, 100 by default. An app that sets
`KIVY_NO_FILELOG`, or turns off `log_enable` in Kivy's configuration, writes no
log file.

### Capture the output from a script or an agent

The launcher passes its own output handles to your app, so a script that
redirects them gets the app's stdout and stderr, `print()` included:

- In Git Bash or another POSIX shell, redirect as usual:

    ```bash
    "./dist/windows/DISPLAY_NAME-VERSION-amd64/DISPLAY_NAME.exe" > app.log 2>&1
    ```

- In PowerShell, `& .\DISPLAY_NAME.exe` returns at once and captures nothing,
  because PowerShell doesn't wait for a windowed program. Pipe it instead, so
  PowerShell waits for it to exit:

    ```powershell
    & ".\DISPLAY_NAME.exe" 2>&1 | Out-String
    ```

    Or start it with `Start-Process -Wait -NoNewWindow` and
    `-RedirectStandardOutput` and `-RedirectStandardError`.

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
