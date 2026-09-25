---
title: CLI reference
sources:
  - kivyforge/cli/__init__.py
  - kivyforge/cli/_platform.py
  - kivyforge/platforms/__init__.py
  - pyproject.toml
  - docs/design/common/02-cli-and-platform-resolution.md
---

# CLI reference

The `kivyforge` command, also installed as `kf`, is a group of verbs. Run every
verb from the directory that contains your `pyproject.toml`. kivyforge looks for
the file in the current directory only, not in parent directories.

The command reference on this page is generated from kivyforge's own command
definitions. For how a verb behaves on a specific platform, see that platform's
guide.

## Target selection

Verbs that take `-p` / `--platform` resolve the target in this order:

1. `-p` / `--platform` on the command line.
2. The `KIVYFORGE_PLATFORM` environment variable.
3. The host's own platform, if `pyproject.toml` has an overlay for it. Android
   and iOS are never a host default, so they always need `-p` or
   `KIVYFORGE_PLATFORM`.

If none of these resolves a target, the verb fails and lists the platforms
configured in `pyproject.toml`. `init` accepts `-p` more than once and, without
it, also falls back to the project's only existing overlay. See
[Choose a target platform](../concepts/choose-platform.md).

## Commands

::: mkdocs-click
    :module: kivyforge.cli
    :command: main
    :prog_name: kivyforge
    :depth: 2
    :style: table

## Platform-specific flags

Some flags apply to only one target. The platform guides explain them in context.

| Target | Flags | Guide |
|---|---|---|
| Android | `build`: `--debug`, `-f apk\|aab`, `--abi`. `run`: `--emulator`, `--device`, `--avd`, `--serial`, `--smoke`, `--abi`. `package`: `--keystore`, `--key-alias`, `--abi`. | [Run on a device or emulator](../guides/android/run.md), [Sign and publish to Google Play](../guides/android/signing.md) |
| iOS | `build`: `--simulator`, `--device`, `--release`, `--arch`, `--team-id`, `--signing-identity`, `--export-method`. `run`: `--simulator`, `--device`, `--destination`, `--list-devices`. `package`: `--team-id`, `--signing-identity`, `--export-method`. | [Run on the simulator or a device](../guides/ios/run.md), [Sign the app](../guides/ios/signing.md) |
| macOS | `build` and `package`: `--arch`. `package`: `--signing-identity`, `--notarize` / `--no-notarize`, `--notary-profile`. | [Sign, notarize, and staple](../guides/macos/signing.md) |
| Linux | `build` and `package`: `--arch x86_64\|aarch64` (default: the first entry in `archs`). `package`: `-f appimage\|folder`. | [Build an AppImage or folder](../guides/linux/build.md) |
| Windows | None. Configure signing in `[tool.kivy.windows.signing]`. | [Sign with Authenticode](../guides/windows/signing.md) |

For which verb produces which artifact, see
[Build versus package](../concepts/build-vs-package.md).

## What's next

- [JSON output](json-output.md) for scripts and CI
- [Exit and diagnostic codes](codes.md)
- [Environment variables](environment.md)
