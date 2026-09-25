---
title: Build for Raspberry Pi
sources:
  - docs/design/platforms/linux/linux-spec.md
  - docs/design/dev/aarch64-pi-target-findings.md
  - docs/design/dev/roadmap.md
  - docs/design/dev/test-matrix.md
  - CHANGELOG.md
---

# Build for Raspberry Pi

Raspberry Pi is a Linux target, not a separate platform. You cross-build an
`aarch64` AppImage on an `x86_64` Linux machine, copy it to the Pi, and run it
under 64-bit Raspberry Pi OS. You do not install kivyforge on the Pi.

## Before you begin

- An `x86_64` Linux build host. WSL2 works. Building on the Pi or on any other
  `aarch64` machine is untested.
- A Raspberry Pi 4 or Pi 5 running a 64-bit Raspberry Pi OS image with a
  desktop, which provides the Wayland or X11 session the app needs.
- [Install kivyforge](../../get-started/install.md).
- Optional: a Python interpreter on the build host with the same minor version
  as your pinned runtime, for example `python3.13` for runtime `3.13.14`. See
  [Byte-compiling on a cross-build](#byte-compiling-on-a-cross-build).

## Step 1: Set the architecture

Set `[tool.kivy.linux].archs` to `["aarch64"]`. The default is `["x86_64"]`.

```toml
[tool.kivy.linux]
schema_version = 1
app_id = "org.example.myapp"
archs = ["aarch64"]

[tool.kivy.linux.python]
version = "3.13.14"
```

To build for both the Pi and x86_64 PCs from one lock, list both, for example
`archs = ["x86_64", "aarch64"]`. Each `package` run builds one AppImage: the
first entry in `archs` unless you pass `--arch aarch64` (see Step 3).

## Step 2: Lock the dependencies

```bash
kivyforge lock -p linux
```

The lock pins the `aarch64` Python runtime and a `manylinux` `aarch64` wheel
for every compiled dependency. If a dependency publishes no such wheel, `lock`
fails and names it.

## Step 3: Package the AppImage

```bash
kivyforge package -p linux -f appimage --arch aarch64
```

With `archs = ["aarch64"]` alone, `--arch aarch64` is optional. kivyforge runs a pinned `x86_64` `appimagetool` and embeds the `aarch64`
AppImage runtime. The output is `dist/linux/PROJECT_NAME-VERSION-aarch64.AppImage`,
where `PROJECT_NAME` is `[project].name` and `VERSION` is `[project].version`.

You cannot launch this build on the `x86_64` host. `kivyforge run -p linux`
fails for an `aarch64` lock, and `kivyforge doctor -p linux` warns about the
cross-build in its "Native vs cross" check.

## Step 4: Run the AppImage on the Pi

Copy the AppImage to the Pi, then run these commands on the Pi:

```bash
chmod +x APPIMAGE_FILE
./APPIMAGE_FILE
```

Replace `APPIMAGE_FILE` with the AppImage's file name, for example
`dice-roller-0.1.0-aarch64.AppImage`.

!!! tip
    If you start the app over SSH, the SSH session has no display. Point the
    app at the Pi's desktop session first, for example with
    `export WAYLAND_DISPLAY=wayland-0` on a Wayland desktop.

## Verify

Your app's window opens on the Pi's display. The Pi supplies OpenGL and the
display, like any Linux host. See
[Meet the Linux host requirements](host-requirements.md).

## Byte-compiling on a cross-build

A release build compiles your app's sources to `.pyc` files by default. The
build host cannot run the `aarch64` interpreter, so kivyforge uses a host
interpreter with the same minor version instead. If it finds none, the
AppImage ships `.py` sources, and `package` reports a
`KF-BYTECOMPILE-NO-INTERP` warning. The AppImage still works. If you set
`byte_compile = true` in `[tool.kivy.linux.build_settings]`, a missing
interpreter fails the build instead.

## Scope

- Tested on a Raspberry Pi 5 running Raspberry Pi OS based on Debian 13, with
  the labwc Wayland desktop and Broadcom V3D graphics. Raspberry Pi 4 is a
  supported target but has not been tested.
- 32-bit ARM images and musl-based systems are not supported.

## What's next

- [Build a Linux AppImage or folder](build.md).
- [Meet the Linux host requirements](host-requirements.md).
- [Linux overlay reference](../../reference/pyproject/linux.md).
