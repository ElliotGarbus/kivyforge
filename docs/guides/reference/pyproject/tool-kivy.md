---
title: "[tool.kivy] reference"
sources:
  - kivyforge/config/model.py
  - kivyforge/config/loader.py
  - docs/design/common/01-pyproject-kivy-spec.md
  - docs/design/dev/package-metadata-proposal.md
  - examples/desktop/dice-roller/pyproject.toml
  - docs/design/dev/package-index-proposal.md
---

# `[tool.kivy]` reference

`[tool.kivy]` holds the settings that every target shares. Each target also
needs its own overlay table, such as `[tool.kivy.android]`; `[tool.kivy]` alone
does not configure a target. For how the tables fit together, see
[Project configuration](../../concepts/configuration.md).

kivyforge reads the app's name and version from `[project]`, and its
dependencies from `[project].dependencies`. The version can be dynamic, taken
from git by your build backend; see
[Set the app version](../../guides/cross-platform/versioning.md).

!!! note "Preview"
    This paragraph describes behavior that is on `main` but not yet in a
    released version. It will ship in a future release.

kivyforge also writes the app's package metadata from `[project]`: its name,
version and entry points (`[project.scripts]`, `[project.gui-scripts]` and
`[project.entry-points]`); see
[Read your package metadata inside the app](../../guides/cross-platform/versioning.md#read-your-package-metadata-inside-the-app).
So it checks them as build backends do, and each of these is a config error at
the line that breaks it:

- `[project].name` is not a valid project name: ASCII letters and digits, with
  `.`, `_` or `-` only between them.
- `[project.entry-points]` holds a `console_scripts` or `gui_scripts` group.
  Use `[project.scripts]` and `[project.gui-scripts]`.
- A group holds a nested table, usually a dotted group name without quotes:
  write `[project.entry-points."myapp.plugins"]`.
- A group name isn't words of letters, digits and underscores joined by dots.
- An entry point name contains `=`, starts with `[`, or starts or ends with
  whitespace.

Entry points must be declared in `[project]`. A setuptools project that
declares them only in `setup.cfg` or `setup.py` fails to build with
`KF-METADATA-ENTRY-POINTS-OUTSIDE-PROJECT`.

## Keys

| Key | Type | Default | Description |
|---|---|---|---|
| `app_dir` | string | required | Directory that contains your Python source, relative to `pyproject.toml`. It must be a subdirectory such as `"src"`. The project root (`"."`), an empty string, an absolute path, and a path outside the project are rejected. |
| `entry_point` | string | the one `[project.gui-scripts]` entry, else `"main"` | Where the app starts, resolved inside `app_dir`. A module name runs that module: `"main"` runs `src/main.py` and `"pkg.start"` runs `src/pkg/start.py`. A `module:function` name calls the function: `"pkg.app:main"` calls `main()` from `src/pkg/app.py`. See [How `entry_point` runs](#how-entry_point-runs). |
| `display_name` | string | `[project].name` | The app name shown to users. Each platform maps it to its own field, for example `CFBundleDisplayName` on iOS and `android:label` on Android. |
| `orientation` | list of string | `["portrait"]` | Allowed screen orientations. Valid values: `portrait`, `portrait-upside-down`, `landscape-left`, `landscape-right`. The list must not be empty. |
| `[[index]]` | array of tables | none | Named package indexes. See [Package indexes and sources](#package-indexes-and-sources). |
| `[sources]` | table | none | Which index a package comes from, for every target. See [Package indexes and sources](#package-indexes-and-sources). |

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

kivyforge adds `app_dir` to `sys.path` on every platform. What it runs then
depends on how `entry_point` is written.

### A module: `entry_point = "main"`

kivyforge runs the module as `__main__`, the same as `python -m`. As a result:

- An `if __name__ == "__main__":` block in the module runs.
- Calling `App().run()` at the top level of the module also works.
- If `entry_point` names a package rather than a module, the package needs a
  `__main__.py`.

This is the form `kivyforge init` writes, and the one a Buildozer-style app
uses.

### A function: `entry_point = "pkg.app:main"`

kivyforge calls the function the way an installed script calls it: it imports
`pkg.app`, calls `main()` with no arguments, and uses the return value as the
exit status (`None` means 0). Use this form when your app is a package whose
modules use relative imports, such as `from . import helper`. Those imports fail
when a module inside a package runs as `__main__`, and work when the module is
imported as part of its package.

`pkg:main` also works and imports `pkg/__init__.py`. `"pkg.app:App.launch"`
calls an attribute of an object in the module.

### From `[project.gui-scripts]`

If your project already declares a GUI script for `pip` and `uv`, you can leave
`entry_point` unset:

```toml
[project.gui-scripts]
myapp = "myapp.app:main"

[tool.kivy]
app_dir = "src"   # src/myapp/__init__.py, src/myapp/app.py, ...
```

When `entry_point` is unset, kivyforge picks the entry point like this:

1. If `[project.gui-scripts]` has exactly one entry, kivyforge calls it, the
   same as `entry_point = "myapp.app:main"`. The same app then starts the same
   way under `uv run myapp` and in a kivyforge build.
2. If it has more than one entry, kivyforge reports an error that names them.
   Set `entry_point` to the one the app should start.
3. If there are no GUI scripts, kivyforge uses `"main"`.

`kivyforge init` follows the same rule when it writes `[tool.kivy]`: for a
project with one GUI script it writes no `entry_point`, and for several it sets
`entry_point` to the first.

kivyforge never reads `[project.scripts]`, because those are console scripts.
A GUI script must name a function. If you want a module to run as `__main__`
instead, set `entry_point` to the module name. If `[project].dynamic` lists
`gui-scripts`, your build backend may add more entries, so kivyforge asks you
to set `entry_point`.

## Package indexes and sources

!!! note "Preview"
    This describes behavior that is on `main` but not yet in a released
    version. It will ship in a future release.

Name an index once in `[tool.kivy]`, then pin packages to it in `sources`. A
pinned package comes only from its index, on every target that applies the
pin. See
[Where packages come from](../../concepts/runtimes-and-wheels.md#where-packages-come-from)
for how pins combine with `find_links` and the other indexes.

### `[[tool.kivy.index]]`

An array of tables, one per index:

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | A unique name made of letters, digits, `.`, `_`, and `-`. `pypi` is reserved. |
| `url` | string | required | The index's simple API URL. It must start with `http://` or `https://` and can't contain a username or password, because it is written into the lockfile. |
| `explicit` | bool | `false` | If `true`, the index serves only the packages pinned to it. If `false`, it is also an extra index for every target, ranked after the target's `extra_index_urls` and before PyPI. |

`pypi` always means `https://pypi.org/simple/`. You can pin a package to it
without declaring it.

### `[tool.kivy.sources]`

Maps a package name to the index it comes from, in the same form as uv's
`[tool.uv.sources]`:

```toml
[tool.kivy.sources]
mycorp-utils = { index = "corp" }
```

Each target overlay can have its own `sources` table, such as
`[tool.kivy.android.sources]`. An entry there replaces the shared entry for the
same package on that target, and adds to the rest.

- A pin applies wherever the package appears, whether you depend on it
  directly or another package does.
- Package names are compared in normalized form, so `PyJNIus` and `pyjnius`
  are the same package.
- `index` is the only key. uv's `git`, `url`, `path`, and `marker` keys are
  rejected, because kivyforge installs prebuilt wheels only. Use a target's
  own `sources` table where uv would use `marker`.
- A pin outranks `find_links`. If the package also has wheels there, `lock`
  ignores them and warns.

### Example

```toml
[[tool.kivy.index]]
name = "mobile-wheels"
url = "https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"
explicit = true

[tool.kivy.android.sources]
kivy = { index = "mobile-wheels" }
pyjnius = { index = "pypi" }

[tool.kivy.ios.sources]
kivy = { index = "mobile-wheels" }
```

## Icons and splash screens

Each platform needs its own icon sizes and formats, so you declare icons and
splash screens in the platform overlays, not in `[tool.kivy]`. See the
[Android](android.md), [iOS](ios.md), [macOS](macos.md), [Windows](windows.md),
and [Linux](linux.md) overlay references.

## What's next

- The platform overlays: [Android](android.md), [iOS](ios.md), [macOS](macos.md),
  [Windows](windows.md), and [Linux](linux.md).
- [Project configuration](../../concepts/configuration.md)
