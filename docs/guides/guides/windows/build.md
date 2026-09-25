---
title: Build a Windows onedir app
sources:
  - docs/design/platforms/windows/windows-spec.md
  - docs/design/dev/test-matrix.md
  - examples/desktop/dice-roller/pyproject.toml
  - FAQ.md
---

# Build a Windows onedir app

This page builds a run-from-folder **onedir** bundle: a folder that holds a
windowed launcher `.exe`, a complete Python runtime, your app, and its wheels.
Every file the app needs is in the folder, so it runs on a Windows machine that
has no Python installed. The folder is the only Windows package format
kivyforge produces.

## Before you begin

- A Windows host. Windows apps build only on Windows.
- [Install kivyforge](../../get-started/install.md). To render an app icon,
  install the `kivyforge[windows]` extra, which adds Pillow.

## Step 1: Configure the overlay

Add a `[tool.kivy.windows]` table to `pyproject.toml`:

```toml
[tool.kivy.windows]
schema_version = 1
app_id = "Example.MyApp"
archs = ["amd64"]

[tool.kivy.windows.python]
version = "3.13.14"

[tool.kivy.windows.icons]
source = "assets/icon.png"
```

`schema_version`, `app_id`, and `[tool.kivy.windows.python].version` are
required. `app_id` is the Windows AppUserModelID, which groups your app's
windows on the taskbar. Use the `CompanyName.ProductName` style, not the
reverse-DNS IDs that Apple platforms and Linux use. See the
[Windows overlay reference](../../reference/pyproject/windows.md) for every key.

## Step 2: Lock the dependencies

```powershell
kivyforge lock -p windows
```

This writes `pylock.windows.toml`.

## Step 3: Run the app

```powershell
kivyforge run -p windows
```

`run` builds the bundle in `build\windows\` and launches it attached to your
terminal, so you see stdout, stderr, and tracebacks while you develop.

## Step 4: Package the distributable

```powershell
kivyforge package -p windows
```

`package` builds a release bundle and copies it to
`dist\windows\DISPLAY_NAME-VERSION-amd64\`. `DISPLAY_NAME` is
`[tool.kivy].display_name` with characters that Windows forbids in file names
removed, and `VERSION` is `[project].version`. The launcher inside the folder is
`DISPLAY_NAME.exe`. For example, the `dice-roller` example packages to
`dist\windows\Dice Roller-0.1.0-amd64\Dice Roller.exe`.

The bundle is unsigned unless you [configure signing](signing.md), and
`package` reports a `KF-SIGNING-UNCONFIGURED` warning to say so.

## Verify

```powershell
kivyforge package -p windows --json
```

`data.artifacts` lists the packaged folder with `"kind": "folder"`. Open that
folder in Explorer and double-click the `.exe`. Your window opens with no
console window.

## Keep paths short

Windows limits a path to 260 characters (`MAX_PATH`) unless long-path support
is turned on, and it is off by default. This limit matters in two places:

- **On your build machine.** The full runtime nests deep under
  `build\windows\`. If a build fails with a path error, keep the project near
  the drive root, or turn on long paths. `kivyforge doctor -p windows` warns
  when long-path support is off. For the registry command, see
  [Use a short project path](file-locking.md#use-a-short-project-path).
- **On your users' machines.** Every file in the bundle must fit in the limit
  *including the folder the user puts the bundle in*. After packaging,
  kivyforge measures the deepest path in the bundle. If that leaves less than
  100 characters for the install folder, `package` prints a warning and reports
  a `KF-PATH-DEPTH` warning that says how long the folder can be. The package
  still succeeds. Install the bundle to a short folder, or turn on long paths on
  the machines that run it.

## What's next

- [Understand the Windows launcher](launcher.md).
- [Sign a Windows app with Authenticode](signing.md).
- [Create a Windows installer](installer.md).
