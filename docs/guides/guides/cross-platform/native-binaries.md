---
title: Ship native binaries
sources:
  - docs/design/common/08-native-binaries-channel.md
  - kivyforge/config/model.py
  - kivyforge/platforms/windows/native_stage.py
  - kivyforge/platforms/macos/native_stage.py
  - kivyforge/platforms/macos/native_links.py
  - examples/desktop/hello-native/pyproject.toml
  - examples/desktop/hello-native/src/main.py
---

# Ship native binaries

Some apps need a native file that no Python wheel provides: a vendor SDK's shared
library that your code loads with `ctypes`, or a helper executable that it runs.
On macOS, Linux, and Windows, you declare these in
`[tool.kivy.<platform>.native.binaries]`. kivyforge pins each one in the lock,
stages it into the app, and makes it loadable. This page shows how, using the
`hello-native` example.

This channel is for desktop targets only. On iOS, use xcframeworks or
[Swift packages](../ios/swift-packages.md). On Android, use
[`.aar` and `.jar` libraries](../android/java-libraries.md).

## Before you begin

- A project with an overlay for each desktop target you ship.
- The native binaries, already built for each target and architecture.
  kivyforge stages prebuilt binaries; it does not compile them.

## Declare and stage a binary

1. Add each binary to the target's overlay. The key is a name you choose. Set
   `version`, and set `source` to either an `http://` or `https://` download URL
   or a path relative to `pyproject.toml`:

    === "Windows"
        ```toml
        [tool.kivy.windows.native.binaries]
        roll = { version = "0.1.0", source = "binaries/windows/roll.exe" }
        greet = { version = "0.1.0", source = "binaries/windows/greet.dll" }
        ```

    === "macOS"
        ```toml
        [tool.kivy.macos.native.binaries]
        roll = { version = "0.1.0", source = "binaries/macos/roll" }
        libgreet = { version = "0.1.0", source = "binaries/macos/libgreet.dylib" }
        ```

    === "Linux"
        ```toml
        [tool.kivy.linux.native.binaries]
        roll = { version = "0.1.0", source = "binaries/linux/roll" }
        libgreet = { version = "0.1.0", source = "binaries/linux/libgreet.so" }
        ```

    Absolute paths and paths outside the project are rejected. A `.zip`,
    `.tar.gz`, or `.tgz` source is extracted, keeping its directory structure;
    any other file is copied under its own filename.

2. Re-lock the target. `lock` pins each binary by SHA-256:

    ```bash
    kivyforge lock -p linux
    ```

3. Build the app:

    ```bash
    kivyforge build -p linux
    ```

The build downloads or copies each binary, verifies its SHA-256, and stages it
into the app. It fails if two entries would write the same file. On Windows
and macOS, it also fails if a binary was built for the wrong architecture.

| Target | Staged into | How your code finds it |
|---|---|---|
| Windows | `bin\` in the bundle | The generated bootstrap registers `bin\` with `os.add_dll_directory` and adds it to `PATH`, so executables run by name and DLLs load by name. |
| macOS | Executables in `Contents/Helpers`, libraries in `Contents/Frameworks` | Executables run by name, because `Contents/Helpers` is added to `PATH`. Load libraries by absolute path: macOS strips `DYLD_*` variables, so loading by name is not possible. The signing step signs the staged binaries. |
| Linux | `usr/bin` in the AppDir | The generated `AppRun` adds `usr/bin` to `PATH` and `LD_LIBRARY_PATH`, so executables run by name and libraries load by name. |

kivyforge does not resolve a binary's own dependencies or fix its load paths.
If a library needs other libraries, declare those too, so they are staged into
the app beside it.

### macOS: code only, in Apple's layout

On macOS, the build reads each file's Mach-O header and places it where Apple's
bundle layout says code goes. Every location is flat: a file from an archive
keeps only its name, and names that differ only in case count as the same name.

- A single file that is not native code fails the build
  (`KF-MACOS-NATIVE-NOT-CODE`). Ship data with
  [`include_files`](../../reference/pyproject/macos.md) and scripts in
  `app_dir`. Files in an archive that are not native code, such as headers or
  licences, are skipped with a warning.
- Plug-ins (`MH_BUNDLE`), object files, and binaries inside a bundle in an
  archive, such as a `.framework`, fail the build
  (`KF-MACOS-NATIVE-UNSUPPORTED`).
- A link between declared binaries that would not resolve in the new layout
  fails the build (`KF-MACOS-NATIVE-LOAD-PATH`). The message gives the
  `install_name_tool` commands that fix it. The usual cause is a helper built
  to find its library beside it. Apple's form works from `Contents/Helpers`:
  link the library as `@rpath/<name>` and give the helper the run path
  `@executable_path/../Frameworks`. A library your Python code loads should
  find its own dependencies with the run path `@loader_path`.

## Use the binaries from Python

Run a helper executable by name on every desktop target:

```python
import subprocess

out = subprocess.run(["roll"], capture_output=True, text=True, check=True)
```

Load a shared library the way each target requires:

=== "Windows"
    ```python
    import ctypes

    lib = ctypes.WinDLL("greet.dll")
    ```

=== "macOS"
    ```python
    import ctypes
    import sys
    from pathlib import Path

    # sys.prefix is Contents/Resources/python.
    frameworks = Path(sys.prefix).parents[1] / "Frameworks"
    lib = ctypes.CDLL(str(frameworks / "libgreet.dylib"))
    ```

=== "Linux"
    ```python
    import ctypes

    lib = ctypes.CDLL("libgreet.so")
    ```

## Verify

Run the app and confirm that the library loads and the helper runs:

```bash
kivyforge run -p linux
```

Then run `doctor` for the target:

```bash
kivyforge doctor -p linux
```

Its native-binaries check fails if a declared source file is missing or two
entries would collide. On macOS, it also fails if a declared single file is not
an executable or a dynamic library. On macOS and Linux, once the app is built,
it also checks that every staged binary matches the target architecture. On
Windows and macOS, the build itself checks the architecture.

## What's next

- [Prebuilt runtimes and wheels](../../concepts/runtimes-and-wheels.md), the
  channel for compiled Python packages
- [Manage dependencies and re-lock](dependencies.md)
- [Lockfile format](../../reference/lockfile.md)
