---
title: Manage dependencies and re-lock
sources:
  - docs/design/common/03-lockfile-concept.md
  - docs/design/common/04-artifact-distribution.md
  - kivyforge/cli/lock.py
  - kivyforge/lock/reader.py
  - kivyforge/platforms/android/lock/builder.py
  - FAQ.md
---

# Manage dependencies and re-lock

Your app's dependencies live in `[project].dependencies`. kivyforge resolves them
separately for each target and pins the result in that target's lockfile. This
page shows how to add a dependency, hold a package on one version, re-lock, and
keep the lock in sync with `pyproject.toml`.

## Before you begin

- A project with an overlay for each target you build. See
  [Project configuration](../../concepts/configuration.md).
- A host that can build the target. `lock` follows the same host rules as
  `build`: lock iOS and macOS on a Mac, Windows on Windows, and Linux on x86_64
  Linux. Android locks on any of them. See
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

## Pin a package version

The first lock takes the newest version your specifier allows. After that,
`kivyforge lock` keeps the versions already locked: when a lock input
changes, only the packages that change requires move. `--update` resolves
everything to the newest version allowed.

To hold a package on one version, require that version exactly:

```toml
[project]
dependencies = [
    "kivy==2.3.1",
    "pillow==10.4.0",
]
```

A range such as `kivy>=2.3.1` or `pillow>=10` moves to the newest match the
next time you pass `--update`. A Kivy 3 development snapshot is a pre-release, so the
specifier has to name one. See the `kivy_generation` setting in
[Configure your Android app](../android/configure.md). A range such as
`kivy>=3.0.0.dev0,<4` still moves to the newest snapshot. Pin the snapshot
you mean:

```toml
[project]
dependencies = [
    "kivy==3.0.0.dev202607301604",
]
```

A package you did not list moves as well. On Android, `lock` adds pyjnius when
you have not declared it, using a range, so a re-lock picks up newer pyjnius
releases. Declare it yourself to choose the version. See
[Call Android APIs with pyjnius](../android/pyjnius.md). A package pulled in by
another package moves the same way. List it in `[project].dependencies` with
`==` and that requirement is the one `lock` resolves.

`lock --check` resolves again and compares the result with the lock on disk.
An exact pin stays stable. A range fails the check when a newer match is
published, even though `pyproject.toml` has not changed. `build`, `run`, and
`package` still accept that lock. They refuse it when the file hash no longer
matches.

The next `lock` overwrites a hand-edited `pylock.<platform>.toml`. Change the
specifier and re-lock.

When a step edits `pyproject.toml` after the lock was resolved, and this build
should keep the pins on disk, pass `--no-verify-lock` to `build`, `run`, or
`package`. That skips the drift check. See
[Drive kivyforge from CI or an agent](ci-and-agents.md).

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

The lock records a hash of its lock inputs: `[project].dependencies`,
`requires-python`, and the target's Python version, architectures, indexes,
`find_links`, `exclude`, and native libraries. When you change one of them,
re-lock the targets you build. The re-lock keeps the versions already locked
and moves only what the change requires. Editing anything else, such as
signing, icons, or another platform's settings, leaves the lock in sync.

If the lock is in sync, `lock` leaves it unchanged. To resolve again anyway and
take the newest version each specifier allows, pass `--update`:

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

This clears kivyforge's cache of runtimes and wheels. pip's own cache, which
`lock` uses while resolving, is separate; clear it with `pip cache purge`.

## Verify

Check that the lock matches `pyproject.toml`:

```bash
kivyforge lock -p linux --check
```

The command exits `0` and prints that the lock is up to date. It resolves
while keeping the locked versions, so a newer upstream release alone does not
fail it. If a lock input changed, it lists what would change, exits `4` with
`KF-LOCK-DRIFT`, and writes nothing. `build`, `run`, and `package` fail the
same way when the lock inputs' hash no longer matches the lock. See
[Pin a package version](#pin-a-package-version) and
[Drive kivyforge from CI or an agent](ci-and-agents.md).

## What's next

- [Lockfiles](../../concepts/lockfiles.md) and the
  [lockfile format reference](../../reference/lockfile.md)
- [Drive kivyforge from CI or an agent](ci-and-agents.md)
