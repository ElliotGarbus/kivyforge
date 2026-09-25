---
title: "[tool.kivy] reference"
sources:
  - kivyforge/config/model.py
  - kivyforge/config/loader.py
  - docs/design/common/01-pyproject-kivy-spec.md
  - examples/desktop/dice-roller/pyproject.toml
---

# `[tool.kivy]` reference

`[tool.kivy]` holds the settings that every target shares. Each target also
needs its own overlay table, such as `[tool.kivy.android]`; `[tool.kivy]` alone
does not configure a target. For how the tables fit together, see
[Project configuration](../../concepts/configuration.md).

kivyforge reads the app's name and version from `[project]`, and its
dependencies from `[project].dependencies`.

## Keys

| Key | Type | Default | Description |
|---|---|---|---|
| `app_dir` | string | required | Directory that contains your Python source, relative to `pyproject.toml`. It must be a subdirectory such as `"src"`. The project root (`"."`), an empty string, an absolute path, and a path outside the project are rejected. |
| `entry_point` | string | `"main"` | Module to run at startup, as a dotted Python name resolved inside `app_dir`. For example, `"main"` runs `src/main.py` and `"pkg.start"` runs `src/pkg/start.py`. |
| `display_name` | string | `[project].name` | The app name shown to users. Each platform maps it to its own field, for example `CFBundleDisplayName` on iOS and `android:label` on Android. |
| `orientation` | list of string | `["portrait"]` | Allowed screen orientations. Valid values: `portrait`, `portrait-upside-down`, `landscape-left`, `landscape-right`. The list must not be empty. |

kivyforge rejects any key under `[tool.kivy]` that it doesn't recognize,
including keys in the platform overlays. The error names the key and its line,
and suggests the closest valid key, for example:

```text
Error: unknown key 'deployment_targt' in [tool.kivy.ios] (line 14)
  hint: did you mean 'deployment_target'? kivyforge does not read this key, so it would have no effect. [...]
```

The exceptions are tables whose keys belong to another tool, such as
`[tool.kivy.ios.info_plist]` and `[tool.kivy.android.gradle_properties]`, and a
table for a platform that kivyforge doesn't support yet, such as
`[tool.kivy.web]`, which is ignored.

## Example

```toml
[tool.kivy]
display_name = "Dice Roller"
app_dir = "src"
entry_point = "main"
orientation = ["portrait"]
```

## How `entry_point` runs

kivyforge adds `app_dir` to `sys.path` and runs `entry_point` as `__main__` on
every platform, the same as `python -m`. As a result:

- An `if __name__ == "__main__":` block in the module runs.
- Calling `App().run()` at the top level of the module also works.
- If `entry_point` names a package rather than a module, the package needs a
  `__main__.py`.

## Icons and splash screens

Each platform needs its own icon sizes and formats, so you declare icons and
splash screens in the platform overlays, not in `[tool.kivy]`. See the
[Android](android.md), [iOS](ios.md), [macOS](macos.md), [Windows](windows.md),
and [Linux](linux.md) overlay references.

## What's next

- The platform overlays: [Android](android.md), [iOS](ios.md), [macOS](macos.md),
  [Windows](windows.md), and [Linux](linux.md).
- [Project configuration](../../concepts/configuration.md)
