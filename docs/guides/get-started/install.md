---
title: Install kivyforge
sources:
  - README.md
  - pyproject.toml
  - docs/design/common/02-cli-and-platform-resolution.md
  - FAQ.md
---

# Install kivyforge

kivyforge is a command-line tool. This page installs it and confirms that it
runs. It does not install the per-target toolchains (Xcode, the Android SDK, and
so on). Each platform guide covers those.

## Before you begin

- Python 3.13 or newer. If you install with uv and have no suitable Python, uv
  downloads one for you.
- One of these installers: [uv](https://docs.astral.sh/uv/) (recommended),
  [pipx](https://pipx.pypa.io/), or pip.

## Install with uv (recommended)

[uv](https://docs.astral.sh/uv/) installs command-line tools into their own
isolated environment and puts them on your `PATH`, so `kivyforge` works from any
directory without you managing a virtual environment.

```bash
uv tool install kivyforge
```

If your shell reports that `kivyforge` is not found, uv's tool directory is not
on your `PATH` yet. Add it, then open a new terminal:

```bash
uv tool update-shell
```

To upgrade or remove the tool later:

```bash
uv tool upgrade kivyforge
uv tool uninstall kivyforge
```

## Install with pipx

[pipx](https://pipx.pypa.io/) also installs command-line tools into isolated
environments:

```bash
pipx install kivyforge
```

## Install with pip

If you use neither uv nor pipx, install kivyforge into a virtual environment so
it does not collide with other projects:

=== "PowerShell"
    ```powershell
    python -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install kivyforge
    ```

=== "bash"
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install kivyforge
    ```

With this method, `kivyforge` is available only while the virtual environment is
active.

## Add the icon extras

Rendering app icons for Linux, Windows, and Android needs
[Pillow](https://python-pillow.org/), which kivyforge ships as optional extras.
If your project sets `[tool.kivy.<platform>.icons].source` for one of these
targets, install the matching extra (`linux`, `windows`, or `android`). Without
it, the build stops with an error that names the missing extra. macOS and iOS
icons need no extra.

For example, to install kivyforge with the Windows extra:

=== "uv"
    ```bash
    uv tool install "kivyforge[windows]"
    ```

=== "pipx"
    ```bash
    pipx install "kivyforge[windows]"
    ```

=== "pip"
    ```bash
    pip install "kivyforge[windows]"
    ```

To combine extras, list them together, for example `kivyforge[linux,android]`.

## Verify

Check the version and ask the tool what it can do:

```bash
kivyforge --version
kivyforge capabilities
```

`kivyforge capabilities` needs no project, lock, or network. It prints the
targets, their architectures and package formats, and which hosts can build
which targets.

!!! tip "The `kf` alias"
    The install also adds a `kf` command, so `kf build -p linux` is the same as
    `kivyforge build -p linux`. This documentation uses the full name.

## Per-host prerequisites

Each target needs its own toolchain on the build host. Install these when you
start building for a target:

- **Android** (build from Windows, macOS, or Linux): JDK 17 or newer, the
  Android SDK, and the Android NDK. See
  [Configure your Android app](../guides/android/configure.md).
- **iOS** (build from macOS only): Xcode 15 or newer. See
  [Configure your iOS app](../guides/ios/configure.md).
- **macOS** (build from macOS): the Xcode command-line tools, which provide
  `codesign`. See [Build a .app](../guides/macos/build.md).
- **Windows** (build from Windows): no extra toolchain. The bundled Python
  runtime carries its own Visual C++ runtime DLLs. See
  [Build an onedir app](../guides/windows/build.md).
- **Linux** (build from Linux): OpenGL libraries and an X11 or Wayland session
  to run the result. See
  [Meet the host requirements](../guides/linux/host-requirements.md).

To check whether this host is ready for a target, run `doctor`:

```bash
kivyforge doctor -p PLATFORM
```

Replace `PLATFORM` with `android`, `ios`, `macos`, `linux`, or `windows`. For
the full host matrix, see [Which host builds which target](hosts.md).

## What's next

- [Build a desktop app](quickstart-desktop.md): the fastest path to a running result.
- [Which host builds which target](hosts.md).
- [How kivyforge works](../concepts/how-it-works.md).
