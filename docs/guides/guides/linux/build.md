---
title: Build a Linux AppImage or folder
sources:
  - docs/design/platforms/linux/linux-spec.md
  - docs/design/dev/test-matrix.md
  - examples/desktop/dice-roller/pyproject.toml
  - FAQ.md
---

# Build a Linux AppImage or folder

This page builds a Linux app in one of two formats: a single self-contained
`.AppImage` file (the default), or a run-from-folder AppDir. An AppDir is the
folder an AppImage is built from, with an `AppRun` launcher at its root. Both
formats bundle a relocatable CPython and your wheels. Both rely on the machine
that runs the app for the C library, OpenGL, and a display server. See
[Meet the Linux host requirements](host-requirements.md).

## Before you begin

- An `x86_64` Linux host. Linux apps build only on Linux. WSL2 works; keep the
  project on the Linux file system, not under `/mnt/c`.
- [Install kivyforge](../../get-started/install.md). To render an app icon,
  install the `kivyforge[linux]` extra, which adds Pillow.

You do not need to install `appimagetool`. kivyforge downloads a pinned copy
the first time you package an AppImage.

## Step 1: Configure the overlay

Add a `[tool.kivy.linux]` table to `pyproject.toml`:

```toml
[tool.kivy.linux]
schema_version = 1
app_id = "org.example.myapp"
archs = ["x86_64"]

[tool.kivy.linux.python]
version = "3.13.14"

[tool.kivy.linux.icons]
source = "assets/icon.png"

[tool.kivy.linux.desktop]
categories = ["Game"]
```

`schema_version`, `app_id`, and `[tool.kivy.linux.python].version` are
required. `app_id` is a reverse-DNS ID that names the generated `.desktop`
file, its `Icon=` entry, and the window class. It can contain only letters,
digits, hyphens, and periods. See the
[Linux overlay reference](../../reference/pyproject/linux.md) for every key.

## Step 2: Lock the dependencies

```bash
kivyforge lock -p linux
```

This writes `pylock.linux.toml`.

## Step 3: Run the app

```bash
kivyforge run -p linux
```

`run` builds the AppDir in `build/linux/` and starts its `AppRun` in your
terminal, so you see stdout, stderr, and tracebacks.

## Step 4: Package

Choose the format with `-f`:

=== "AppImage (default)"
    ```bash
    kivyforge package -p linux -f appimage
    ```
    This writes `dist/linux/PROJECT_NAME-VERSION-ARCH.AppImage`, where
    `PROJECT_NAME` is `[project].name`, `VERSION` is `[project].version`, and
    `ARCH` is `x86_64` or `aarch64`. kivyforge embeds a static-FUSE runtime, so
    the machine that runs the AppImage does not need the `libfuse2` package.

=== "Folder"
    ```bash
    kivyforge package -p linux -f folder
    ```
    This builds a release AppDir at `build/linux/DISPLAY_NAME.AppDir/`, where
    `DISPLAY_NAME` is `[tool.kivy].display_name`. Run it with its `AppRun`
    launcher.

Each `package` run produces one architecture: the first entry in `archs`, or
the one you name with `--arch x86_64` or `--arch aarch64`. To build for a
Raspberry Pi, see [Build for Raspberry Pi](raspberry-pi.md).

## Verify

```bash
kivyforge package -p linux -f appimage --json
```

`data.artifacts` lists the AppImage with `"kind": "appimage"`. For the
`dice-roller` example, run it like this:

```bash
chmod +x dist/linux/dice-roller-0.1.0-x86_64.AppImage
./dist/linux/dice-roller-0.1.0-x86_64.AppImage
```

Your app's window opens.

!!! tip "If the AppImage fails with a FUSE error"
    An AppImage mounts itself through the kernel's `/dev/fuse`, which some
    containers and CI runners do not provide. Extract and run it from a
    temporary folder instead:

    ```bash
    ./dist/linux/dice-roller-0.1.0-x86_64.AppImage --appimage-extract-and-run
    ```

    Setting `APPIMAGE_EXTRACT_AND_RUN=1` in the environment does the same.

## What's next

- [Meet the Linux host requirements](host-requirements.md).
- [Build for Raspberry Pi](raspberry-pi.md).
- [Linux overlay reference](../../reference/pyproject/linux.md).
