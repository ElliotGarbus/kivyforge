---
title: "[tool.kivy.windows] reference"
sources:
  - docs/design/platforms/windows/windows-spec.md
  - docs/design/platforms/windows/signing-windows.md
  - docs/design/platforms/windows/signing-prerequisites-windows.md
  - examples/desktop/dice-roller/pyproject.toml
  - examples/desktop/hello-native/pyproject.toml
---

# `[tool.kivy.windows]` reference

The Windows overlay in `pyproject.toml`. For the task, see
[Build a Windows onedir app](../../guides/windows/build.md).

## `[tool.kivy.windows]`

| Key | Type | Default | Description |
|---|---|---|---|
| `schema_version` | integer | Required | Overlay schema version. Use `1`. |
| `app_id` | string | Required | AppUserModelID. No spaces, at most 128 characters. `doctor` warns unless it uses the `CompanyName.ProductName` style, such as `Example.MyApp`. |
| `archs` | list of strings | `["amd64"]` | Target architectures. Only `amd64` is accepted. |
| `exclude` | list of strings | `[]` | Package names to prune from the dependency resolve. |
| `extra_index_urls` | list of strings | `[]` | Extra package indexes to resolve wheels from. |
| `find_links` | list of strings | `[]` | Project-relative folders that hold local wheels. |

## Sub-tables

### `[tool.kivy.windows.python]`

Required.

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | string | Required | CPython version to bundle (python-build-standalone), such as `3.13.14`. Must satisfy `[project].requires-python`. |

### `[tool.kivy.windows.icons]`

| Key | Type | Default | Description |
|---|---|---|---|
| `source` | string | None | Project-relative path to a 1024x1024 PNG. kivyforge renders it into a multi-resolution `.ico` for the launcher. Needs the `kivyforge[windows]` extra. |

### `[tool.kivy.windows.signing]`

| Key | Type | Default | Description |
|---|---|---|---|
| `thumbprint` | string | None | SHA-1 thumbprint of a code-signing certificate in the store. Spaces and letter case are ignored. |
| `store_scope` | string | `"current_user"` | `"current_user"` (`Cert:\CurrentUser\My`) or `"machine"` (`Cert:\LocalMachine\My`, adds `signtool /sm`). |
| `timestamp_url` | string | `"http://timestamp.digicert.com"` | RFC 3161 timestamp server. |

`package` signs the launcher only when `thumbprint` is set. See
[Sign a Windows app with Authenticode](../../guides/windows/signing.md).

### `[tool.kivy.windows.native.binaries]`

Native binaries that do not come from a wheel, such as a vendor DLL. kivyforge
stages them into the bundle's `bin\` folder. Each entry is an inline table with
`version` and `source` keys. See
[Ship native binaries](../../guides/cross-platform/native-binaries.md).

### `[tool.kivy.windows.build_settings]`

| Key | Type | Default | Description |
|---|---|---|---|
| `byte_compile` | boolean or `"release"` | `"release"` | Compile app and wheel sources to `.pyc`. `"release"` applies to `package` and `run --release` only. |
| `strip_source` | boolean or `"release"` | `"release"` | Remove `.py` files after compiling. Has no effect when nothing is compiled. |

## Example

From `examples/desktop/dice-roller`:

```toml
[tool.kivy.windows]
schema_version = 1
app_id = "Example.DiceRoller"
archs = ["amd64"]

[tool.kivy.windows.python]
version = "3.13.14"

[tool.kivy.windows.icons]
source = "assets/icon.png"
```

## What's next

- [Build a Windows onedir app](../../guides/windows/build.md).
- [Sign a Windows app with Authenticode](../../guides/windows/signing.md).
