---
title: Meet the Linux host requirements
sources:
  - docs/design/platforms/linux/linux-spec.md
  - docs/design/dev/test-matrix.md
  - FAQ.md
---

# Meet the Linux host requirements

A kivyforge AppImage bundles Python and your wheels, but it never bundles the C
library, the OpenGL libraries, or a display server. The Linux machine that runs
the app provides those. This page covers what that machine needs, the minimum
glibc version, and how to run the app without a display or under WSL2.

## What the host provides

- **glibc** at or above the artifact's floor. See
  [The glibc floor](#the-glibc-floor).
- **`libGL.so.1` and `libEGL.so.1`** for OpenGL. On Debian and Ubuntu, install
  `libgl1` and `libegl1`. On Fedora, install `mesa-libGL` and `mesa-libEGL`.
- **An X11 or Wayland session** to open a window.

`musl` distributions such as Alpine are not supported: the bundled runtime is
built against glibc and does not run there.

Run `kivyforge doctor -p linux` on a Linux machine to check it. `doctor` warns
when `ldconfig` cannot find `libGL.so.1` or `libEGL.so.1`, or when neither
`DISPLAY` nor `WAYLAND_DISPLAY` is set. After you lock, it also prints the
effective glibc floor.

## The glibc floor

The bundled python-build-standalone runtime needs **glibc 2.17 or later**, the
same baseline as `manylinux2014` wheels. The artifact's *effective* floor is the
higher of the runtime's floor and the highest manylinux level among your locked
wheels.

To admit wheels that are published only for a newer manylinux level, raise the
floor. The trade-off is that the app then needs a newer glibc on every machine
that runs it:

```toml
[tool.kivy.linux]
glibc_floor = "2.28"
```

`kivyforge lock` rejects a `glibc_floor` below 2.17, and `doctor` reports it as
a failure.

## Run headless in CI

Locking and building need no display; only running the app opens a window. For
a headless smoke test, run the AppImage in a virtual framebuffer with software
OpenGL:

```bash
xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 ./APPIMAGE_FILE
```

Replace `APPIMAGE_FILE` with the path to your `.AppImage`. If the runner has no
`/dev/fuse`, add `--appimage-extract-and-run` after the file name.

## Run under WSL2

The Linux backend is developed and tested on WSL2 Ubuntu. WSLg provides an X11
and Wayland session and OpenGL, so `kivyforge run -p linux` opens a real window.
If OpenGL misbehaves, set `LIBGL_ALWAYS_SOFTWARE=1` to force software rendering.

!!! warning "Keep the project off `/mnt/c`"
    The Linux runtime contains files whose names differ only by letter case,
    which a Windows drive cannot hold. A build of a project under `/mnt/c`
    stops with an error that names the clashing files. Keep the project on the
    Linux file system, for example under your home folder.

## What's next

- [Build a Linux AppImage or folder](build.md).
- [Build for Raspberry Pi](raspberry-pi.md).
- [Diagnose a failing build](../../troubleshooting/index.md).
