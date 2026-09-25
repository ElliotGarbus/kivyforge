---
title: Manage dependencies and re-lock
sources:
  - docs/design/common/03-lockfile-concept.md
  - docs/design/common/04-artifact-distribution.md
  - kivyforge/cli/lock.py
  - kivyforge/lock/reader.py
  - FAQ.md
---

# Manage dependencies and re-lock

Your app's dependencies live in `[project].dependencies`. kivyforge resolves them
separately for each target and pins the result in that target's lockfile. This
page shows how to add a dependency, re-lock, and keep the lock in sync with
`pyproject.toml`.

## Before you begin

- A project with an overlay for each target you build. See
  [Project configuration](../../concepts/configuration.md).
- A host that can lock the target. `lock` runs on any host for every target
  except iOS, which needs macOS. See
  [Which host builds which target](../../get-started/hosts.md).
- For an Android project that declares Maven dependencies in
  `[tool.kivy.android.gradle]`, a JDK. `lock` runs Gradle to resolve them.

## Add or change a dependency

1. Edit `[project].dependencies` in `pyproject.toml`:

    ```toml
    [project]
    dependencies = [
        "kivy>=2.3.1",
        "pillow>=10",
    ]
    ```

2. Re-lock each target you build:

    ```bash
    kivyforge lock -p macos
    kivyforge lock -p android
    ```

Each target gets its own `pylock.<platform>.toml`, because the wheels differ by
platform.

## Make sure every dependency has a wheel

kivyforge installs prebuilt wheels only and never builds a package from source.
A pure-Python package works on every target. A package with compiled code works
only on targets that have a matching wheel: `macosx_*`, `manylinux_*`,
`win_amd64`, `ios_*`, or `android_*`. If a target has no matching wheel, `lock`
fails for that target. See
[Prebuilt runtimes and wheels](../../concepts/runtimes-and-wheels.md).

To add an index or a local directory of wheels, use `extra_index_urls` or
`find_links` in the target's overlay.

## Prune unused Kivy dependencies

Kivy's wheels declare dependencies that many apps don't use. To leave them out of
the lock and the bundle, list them in the overlay's `exclude` key:

```toml
[tool.kivy.macos]
exclude = ["kivy-garden", "docutils", "pygments"]
```

## Keep the lock in sync

The lock records a hash of the whole `pyproject.toml`, so any edit to the file
makes the lock stale, including edits outside `[project].dependencies`. After you
edit `pyproject.toml`, re-lock the targets you build.

If the lock is in sync, `lock` leaves it unchanged. To resolve again anyway, for
example to pick up a newer release that your version specifiers allow, pass
`--update`:

```bash
kivyforge lock -p linux --update
```

## Refresh downloaded artifacts

To download the pinned runtime and native artifacts again without resolving
again, run `upgrade`:

```bash
kivyforge upgrade -p linux
```

To remove the generated project files and also clear the download cache, run:

```bash
kivyforge clean --cache
```

## Verify

Check that the lock matches `pyproject.toml`:

```bash
kivyforge lock -p linux --check
```

The command exits `0` and prints that the lock is up to date. If the lock is
stale, it lists what changed, exits `4` with `KF-LOCK-DRIFT`, and writes
nothing. A `build` or `package` against a stale lock fails the same way. See
[Drive kivyforge from CI or an agent](ci-and-agents.md).

## What's next

- [Lockfiles](../../concepts/lockfiles.md) and the
  [lockfile format reference](../../reference/lockfile.md)
- [Drive kivyforge from CI or an agent](ci-and-agents.md)
