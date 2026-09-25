---
title: Project configuration
sources:
  - docs/design/common/01-pyproject-kivy-spec.md
  - examples/desktop/dice-roller/pyproject.toml
  - examples/mobile/hello-android/pyproject.toml
---

# Project configuration

You configure a kivyforge app entirely in its `pyproject.toml`, in three layers:

1. `[project]`: standard PEP 621 metadata (name, version, dependencies).
2. `[tool.kivy]`: cross-platform Kivy settings that every target shares.
3. `[tool.kivy.<platform>]`: one additive overlay per target you build.

That is the whole configuration surface. There is no separate spec file or
requirements list.

## The three layers

### `[project]`: standard metadata

Your app's identity and its Python dependencies live here, as in any other
PEP 621 project. kivyforge resolves `[project].dependencies` when it locks, and
uses `[project].name` to name generated folders such as `<name>-android/`.

```toml
[project]
name = "dice-roller"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "kivy>=2.3.1",
]
```

### `[tool.kivy]`: cross-platform settings

Settings that every target shares: the display name, the folder that holds your
app source, the entry-point module, and the orientation.

```toml
[tool.kivy]
display_name = "Dice Roller"
app_dir = "src"
entry_point = "main"
orientation = ["portrait"]
```

`app_dir` is required and must be a subdirectory of the project, not the
project root.

### `[tool.kivy.<platform>]`: per-target overlays

Each target adds its own overlay. The overlay carries a required
`schema_version`, the platform's identity (a bundle ID on iOS and macOS, a
package name on Android, an app ID on Linux and Windows), the Python runtime
version, icons, and any platform-specific options. One project can declare
several overlays:

```toml
[tool.kivy.macos]
schema_version = 1
bundle_id = "org.example.dice-roller"
archs = ["arm64"]

[tool.kivy.macos.python]
version = "3.13.14"

[tool.kivy.windows]
schema_version = 1
app_id = "Example.DiceRoller"
archs = ["amd64"]

[tool.kivy.windows.python]
version = "3.13.14"
```

## Why overlays

Because the overlays are additive, one `pyproject.toml` can describe every
platform at once. Every build verb operates on exactly one target per run.

The overlay is also what makes a platform *configured*. kivyforge uses your
host operating system as the default target only when that platform's overlay
exists, and it never guesses a target you have not configured. See
[Choose a target platform](choose-platform.md).

## Seed overlays with `init`

`kivyforge init` adds `[tool.kivy]` and a platform overlay, with `TODO` markers
for the values you need to fill in, to an existing `pyproject.toml`. The file
must already have a `[project]` table; `init` does not create one. Its `-p`
option is repeatable, so one run can seed several overlays:

```bash
kivyforge init -p macos -p windows
```

To regenerate an overlay that already exists, add `--force`. Your signing
settings are preserved.

## Icons and splash screens

Icons are declared per platform, because each platform needs its own sizes and
formats. You point at one source image and kivyforge renders the required set:

```toml
[tool.kivy.macos.icons]
source = "assets/icon.png"
```

Rendering icons for Linux, Windows, and Android needs Pillow, which comes with
the matching kivyforge extra; see [Install kivyforge](../get-started/install.md).
iOS and Android also accept a splash screen in `[tool.kivy.<platform>.splash]`.

## Validation

kivyforge validates configuration strictly and fails fast. A missing required
key, a boolean written as a quoted string, or a path that escapes the project
directory stops the run with an error that names the key, instead of being
coerced.

## What's next

- [`[tool.kivy]` reference](../reference/pyproject/tool-kivy.md) and the
  per-platform overlay references.
- [Lockfiles](lockfiles.md): what `lock` does with `[project].dependencies`.
- [Choose a target platform](choose-platform.md).
