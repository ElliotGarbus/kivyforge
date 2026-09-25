---
title: Choose a target platform
sources:
  - docs/design/common/02-cli-and-platform-resolution.md
  - kivyforge/platforms/__init__.py
---

# Choose a target platform

Platform-aware verbs such as `lock`, `build`, `run`, `package`, and `status`
need to know which target they operate on. kivyforge resolves the target
explicitly and never guesses silently.

## The resolution chain

kivyforge picks the target in this order:

1. **`--platform NAME` or `-p NAME`** on the command line. This takes
   precedence over everything else. `NAME` is one of `ios`, `macos`, `linux`,
   `windows`, or `android`.
2. **The `KIVYFORGE_PLATFORM` environment variable**, a default for a shell
   session or a CI job.
3. **The host operating system**, but only if your `pyproject.toml` declares
   that platform's overlay. macOS maps to `macos`, Linux to `linux`, and
   Windows to `windows`. iOS and Android are never picked this way; always name
   them explicitly.

"Declares the overlay" means the file contains the platform's table, for
example `[tool.kivy.macos]`.

If none of these yields a target, the verb stops with an error that tells you
how to choose one. For example, on Windows in a project that configures `ios`
and `macos`:

```text
Error: no target platform resolved.
  Pass one explicitly:      kivyforge build --platform ios
  Or set a session default: export KIVYFORGE_PLATFORM=ios
  (Configured platforms in this pyproject.toml: ios, macos)
```

`kivyforge doctor` is the exception: when it cannot resolve a target, it runs
the iOS environment checks instead of failing.

## Examples

Name the target explicitly:

```bash
kivyforge build --platform android
```

Set a default for the current shell or CI job, then omit `-p`:

=== "PowerShell"
    ```powershell
    $env:KIVYFORGE_PLATFORM = "android"
    kivyforge build
    ```

=== "bash"
    ```bash
    export KIVYFORGE_PLATFORM=android
    kivyforge build
    ```

On a Mac, in a project with a `[tool.kivy.macos]` overlay, the host resolves the
target, so this builds for macOS:

```bash
kivyforge build
```

## `init` works differently

Every verb except `init` operates on exactly one target per run. `init`'s `-p`
is repeatable, because seeding several overlays at once is its job:

```bash
kivyforge init -p ios -p android
```

Without `-p`, `init` falls back to `KIVYFORGE_PLATFORM`, then to the project's
one existing overlay, then to the host operating system, even when no overlay
exists yet.

## Target selection versus host capability

Resolving *what* you build for is separate from whether *this machine can build
it*. A configured target on the wrong host still fails, with
`KF-HOST-INCAPABLE`. See [Which host builds which target](../get-started/hosts.md).

## What's next

- [Which host builds which target](../get-started/hosts.md).
- [Environment variables](../reference/environment.md).
- [CLI reference](../reference/cli.md).
