---
title: Build a wheel from a GitHub repository
sources:
  - docs/design/common/03-lockfile-concept.md
  - docs/design/common/04-artifact-distribution.md
  - kivyforge/lock/find_links.py
  - kivyforge/lock/inputs.py
---

# Build a wheel from a GitHub repository

Sometimes the version of a package you need is on GitHub but not on PyPI: a
fix on the main branch, a fork, or a project that rarely publishes a release.
kivyforge installs only wheels, so it refuses a source URL such as
`kivymd @ https://github.com/.../master.zip` or a `git+https://` URL at lock
time. Instead, use pip to build a wheel from the repository once, keep it in
your project, and lock it like any other package. This page uses KivyMD's
`master` branch as the example.

The lock pins the wheel by its path and SHA-256 hash, so every build installs
exactly the wheel you built, not whatever the branch holds that day.

## Before you begin

- A project with an overlay for each target you build. See
  [Project configuration](../../concepts/configuration.md).
- Python with pip on your development machine. Any version that can build the
  package works. It does not need to match your app's Python.
- Git on your `PATH`, to build from a `git+https://` URL. Without Git, build
  from an archive URL instead. See [Build without Git](#build-without-git).
- A pure-Python package. pip builds the wheel for the machine it runs on. A
  pure-Python wheel works on every target. A package with compiled code gives
  you a wheel for your development machine only, which an Android or iOS app
  can't use. See
  [Prebuilt runtimes and wheels](../../concepts/runtimes-and-wheels.md).

## Build the wheel

1. From your project's root directory, build the wheel into `wheels/`:

    ```bash
    python -m pip wheel --no-deps --wheel-dir wheels git+https://github.com/kivymd/KivyMD.git
    ```

    pip clones the repository, builds a wheel from its packaging
    configuration, and writes the wheel to `wheels/`. `--no-deps` builds only
    KivyMD. Its dependencies come from your indexes when you lock.

    To build one commit, tag, or branch, add it after `@`:

    ```bash
    python -m pip wheel --no-deps --wheel-dir wheels "git+https://github.com/kivymd/KivyMD.git@COMMIT_SHA"
    ```

    Replace `COMMIT_SHA` with the full commit hash, a tag, or a branch name.
    A commit hash lets you rebuild the same code later.

2. Check the wheel's filename:

    ```text
    wheels/kivymd-2.0.1.dev0-py3-none-any.whl
    ```

    The filename gives the version, `2.0.1.dev0`, and the tag `py3-none-any`,
    which means the wheel is pure Python. If the tag names a platform, such
    as `win_amd64` or `macosx_14_0_arm64`, the package has compiled code and
    the wheel works only on that platform.

    The version comes from the repository's source. Every commit on KivyMD's
    `master` builds as `2.0.1.dev0` until KivyMD changes it.

### Build without Git

GitHub serves every commit, tag, and branch as a `.zip` archive. pip can build
a wheel from the archive without Git:

```bash
python -m pip wheel --no-deps --wheel-dir wheels https://github.com/kivymd/KivyMD/archive/COMMIT_SHA.zip
```

Replace `COMMIT_SHA` with a commit hash, a tag, or a branch name.

The wheel has the same code. A package that records its Git commit at build
time can't find it in an archive. KivyMD stores `"Unknown"` in
`kivymd._version.__hash__` instead of the commit hash.

## Lock the wheel

1. Depend on the package by name and exact version, not by URL:

    ```toml
    [project]
    dependencies = [
        "kivy",
        "kivymd==2.0.1.dev0",
    ]
    ```

    `2.0.1.dev0` is a pre-release, so the specifier has to name it. With
    `==`, `lock` takes that version and no other.

2. List the wheel directory in `find_links` in each target's overlay:

    ```toml
    [tool.kivy.android]
    find_links = ["wheels"]

    [tool.kivy.windows]
    find_links = ["wheels"]
    ```

    A package with a wheel in `find_links` comes only from there, so a newer
    KivyMD release on PyPI doesn't replace your wheel. See
    [Use your own wheels](dependencies.md#use-your-own-wheels).

3. Make sure every dependency of the package has a wheel for each target.
   `lock` resolves KivyMD's dependencies from your indexes, the same way it
   resolves your own. On Android, `pycairo` and `pillow` have no wheel, so
   exclude them:

    ```toml
    [tool.kivy.android]
    exclude = [
        # keep the entries that `kivyforge init` seeded
        "pycairo",  # only KivyMD's MDLoadingIndicator uses it
        "pillow",
    ]
    ```

    !!! note "Preview"
        This describes behavior that is on `main` but not yet in a released
        version. It will ship in a future release. In 3.0.0.dev1 and earlier,
        `exclude` dropped a package only after pip resolved it, so a
        dependency with no wheel for the target still failed the lock.

    Excluding a package removes it from the app. Your app fails if it uses
    the feature that needs the package. With `pycairo` excluded, don't use
    KivyMD's `MDLoadingIndicator`.

4. Lock each target:

    ```bash
    kivyforge lock -p android
    kivyforge lock -p windows
    ```

5. Commit `wheels/` together with the lockfiles. `build` installs the wheel
   from the path the lock records.

!!! warning
    Don't rebuild the wheel on another machine or in CI. Two builds of the
    same commit usually have different hashes. A rebuilt wheel no longer
    matches the lock, and `build` fails with a hash mismatch. Commit the wheel
    you locked.

## Update to a newer commit

1. Delete the old wheel from `wheels/`.
2. Build the new commit, as in [Build the wheel](#build-the-wheel).
3. If the version changed, update the `==` specifier in
   `[project].dependencies`.
4. Re-lock each target:

    ```bash
    kivyforge lock -p android
    ```

    `lock` sees that the wheel changed, names it, and resolves KivyMD again.
    Every other package keeps its locked version.

    !!! note "Preview"
        This describes behavior that is on `main` but not yet in a released
        version. It will ship in a future release. In 3.0.0.dev1 and earlier,
        `lock` reports that the lock is in sync and keeps the old hash when
        the new wheel has the same filename. Run
        `kivyforge lock -p android --update` instead. `--update` also moves
        every package with a range specifier to its newest match. See
        [Pin a package version](dependencies.md#pin-a-package-version).

## Verify

1. Check that the lock pins your wheel by path and hash. In
   `pylock.android.toml`, the `kivymd` entry looks like this:

    ```toml
    [[packages.wheels]]
    name = "kivymd-2.0.1.dev0-py3-none-any.whl"
    path = "wheels/kivymd-2.0.1.dev0-py3-none-any.whl"
    hashes = { sha256 = "..." }
    ```

    A `path` instead of a `url` means the package comes from your wheel.

2. Check that the lock still matches the wheel on disk:

    ```bash
    kivyforge lock -p android --check
    ```

    The command exits `0`. If you replaced the wheel since you locked, it
    exits `4` and names the wheel that changed.

3. Build the app:

    ```bash
    kivyforge build -p android
    ```

    `build` verifies the wheel's hash before it installs it.

To confirm which commit is in the running app, read the version module KivyMD
generates when it builds from Git:

```python
from kivymd import _version

print(_version.__version__, _version.__hash__)
```

## What's next

- [Manage dependencies and re-lock](dependencies.md)
- [Prebuilt runtimes and wheels](../../concepts/runtimes-and-wheels.md)
- [Lockfile format reference](../../reference/lockfile.md)
