---
title: "[tool.kivy.linux] reference"
sources:
  - docs/design/platforms/linux/linux-spec.md
  - examples/desktop/dice-roller/pyproject.toml
  - examples/desktop/hello-native/pyproject.toml
---

# `[tool.kivy.linux]` reference

The Linux overlay in `pyproject.toml`. For the task, see
[Build a Linux AppImage or folder](../../guides/linux/build.md).

## `[tool.kivy.linux]`

| Key | Type | Default | Description |
|---|---|---|---|
| `schema_version` | integer | Required | Overlay schema version. Use `1`. |
| `app_id` | string | Required | Reverse-DNS ID, such as `org.example.myapp`. Names the `.desktop` file, its `Icon=` entry, and the window class. Letters, digits, hyphens, and periods only. |
| `archs` | list of strings | `["x86_64"]` | Target architectures: `x86_64`, `aarch64` (Raspberry Pi). `package` builds the first entry unless you pass `--arch`. |
| `glibc_floor` | string | `"2.17"` (the runtime's floor) | Minimum glibc on the machines that run the app. Raise it to admit newer-manylinux wheels. `lock` rejects values below 2.17. |
| `exclude` | list of strings | `[]` | Package names to prune from the dependency resolve. |
| `extra_index_urls` | list of strings | `[]` | Extra package indexes to resolve wheels from. |
| `find_links` | list of strings | `[]` | Project-relative folders that hold local wheels. |

## Sub-tables

### `[tool.kivy.linux.python]`

Required.

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | string | Required | CPython version to bundle (python-build-standalone), such as `3.13.14`. Must satisfy `[project].requires-python`. |

### `[tool.kivy.linux.icons]`

| Key | Type | Default | Description |
|---|---|---|---|
| `source` | string | None | Project-relative path to a 1024x1024 PNG. kivyforge resizes it into the freedesktop `hicolor` icon set. Needs the `kivyforge[linux]` extra. |

### `[tool.kivy.linux.desktop]`

| Key | Type | Default | Description |
|---|---|---|---|
| `categories` | list of strings | `["Utility"]` | freedesktop main menu categories for the `.desktop` entry. Allowed values: `AudioVideo`, `Audio`, `Video`, `Development`, `Education`, `Game`, `Graphics`, `Network`, `Office`, `Science`, `Settings`, `System`, `Utility`. |

### `[tool.kivy.linux.native.binaries]`

Native binaries that do not come from a wheel, such as a vendor shared library.
kivyforge stages them into the AppDir's `usr/bin`. Each entry is an inline table
with `version` and `source` keys. See
[Ship native binaries](../../guides/cross-platform/native-binaries.md).

### `[tool.kivy.linux.build_settings]`

| Key | Type | Default | Description |
|---|---|---|---|
| `byte_compile` | boolean or `"release"` | `"release"` | Compile app and wheel sources to `.pyc`. `"release"` applies to `package` and `run --release` only. |
| `strip_source` | boolean or `"release"` | `"release"` | Remove `.py` files after compiling. Has no effect when nothing is compiled. |

## Example

From `examples/desktop/dice-roller`:

```toml
[tool.kivy.linux]
schema_version = 1
app_id = "org.example.dice-roller"
archs = ["x86_64"]

[tool.kivy.linux.icons]
source = "assets/icon.png"

[tool.kivy.linux.desktop]
categories = ["Game"]

[tool.kivy.linux.python]
version = "3.13.14"
```

## What's next

- [Build a Linux AppImage or folder](../../guides/linux/build.md).
- [Meet the Linux host requirements](../../guides/linux/host-requirements.md).
- [Build for Raspberry Pi](../../guides/linux/raspberry-pi.md).
