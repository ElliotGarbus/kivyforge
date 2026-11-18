---
title: Package your app with a Kivy development build
sources:
  - kivyforge/lock/sources.py
  - kivyforge/lock/wheelruntime/resolver.py
  - kivyforge/platforms/macos/lock/profile.py
  - kivyforge/platforms/linux/lock/profile.py
  - kivyforge/status.py
---

# Package your app with a Kivy development build

To test your app with a Kivy change that isn't released, such as a branch you
are working on, build a wheel from your Kivy checkout and lock your app against
it. kivyforge installs only wheels and never builds Kivy itself, so the wheel
has to fit the target exactly: the same CPython minor version as the Python the
target bundles, and the target's platform and architecture.

This page covers the desktop targets: Windows, macOS, and Linux. pip builds a
wheel for the machine it runs on, so build each wheel on the platform you
target. A Kivy wheel for Android or iOS has to be cross-compiled, which
`pip wheel` doesn't do.

## Before you begin

- A Kivy checkout that builds on this machine, with Kivy's build
  prerequisites installed. See Kivy's instructions for installing from source.
- Git, to make a clean worktree of the checkout.
- A project with an overlay for the target. See
  [Project configuration](../../concepts/configuration.md).

## Find the Python the target bundles

The wheel must be built by the same CPython minor version as the target's
Python, because a compiled wheel works only with the Python it was built for.
The version is in the target's `python` table:

```toml
[tool.kivy.windows.python]
version = "3.13.5"
```

`kivyforge status -p windows --json` also reports it, as `data.python`.

For `3.13.5`, you need a wheel tagged `cp313`. A `cp312` wheel doesn't fit,
even though its platform tag is right.

If you already build Kivy with another Python, for example the one in your
Kivy development environment, you can set the target's `version` to a release
of that Python instead.

## Build the wheel

1. Make a clean worktree of the commit you want to test:

    ```bash
    git -C PATH_TO_KIVY worktree add --detach PATH_TO_WORKTREE HEAD
    ```

    Replace `PATH_TO_KIVY` with your Kivy checkout and `PATH_TO_WORKTREE` with
    a new, empty directory outside it. Replace `HEAD` with a branch or commit
    to build something other than what is checked out.

    A checkout where you built Kivy in place, as `pip install -e .` does,
    holds build output that can make `pip wheel` fail, with an error that the
    setup script specifies an absolute path. A clean worktree has none of it.
    Commit your Kivy changes first, because the worktree has only committed
    work.

2. From the worktree, build the wheel with the target's CPython version into
   your app's `wheels/` directory. On Windows, the `py` launcher picks the
   version:

    ```bash
    py -3.13 -m pip wheel . --no-deps --wheel-dir PATH_TO_APP/wheels
    ```

    On macOS and Linux, use that version's interpreter, such as `python3.13`.
    pip installs Kivy's build requirements in an isolated environment, so the
    build doesn't use your Kivy development environment. `--no-deps` builds
    only Kivy. Its dependencies come from your indexes when you lock.

3. Check the wheel's filename:

    ```text
    wheels/kivy-3.0.0.dev0-cp313-cp313-win_amd64.whl
    ```

    The filename gives the version, `3.0.0.dev0`; the Python, `cp313`; and the
    platform, `win_amd64`. Each must match the target:

    - **Windows**: one wheel for each architecture in `archs`, such as
      `win_amd64`.
    - **macOS**: an `arm64` or `universal2` wheel, for a macOS version no newer
      than `[tool.kivy.macos].minimum_system_version`, which is `11.0` when
      unset. A wheel tagged `macosx_15_0_arm64` doesn't fit an `11.0` target.
      Set `MACOSX_DEPLOYMENT_TARGET` to the target's version when you build.
    - **Linux**: a `manylinux` wheel. pip builds a `linux_x86_64` wheel, which
      `lock` doesn't accept. Repair it with
      [auditwheel](https://github.com/pypa/auditwheel), and put the repaired
      wheel in `wheels/` instead. Its glibc version must be no newer than
      `[tool.kivy.linux].glibc_floor`.

4. Remove the worktree when you no longer need it:

    ```bash
    git -C PATH_TO_KIVY worktree remove PATH_TO_WORKTREE
    ```

## Lock and package the app

1. Depend on Kivy by its exact version:

    ```toml
    [project]
    dependencies = [
        "kivy==3.0.0.dev0",
    ]
    ```

    A development version is a pre-release, so the specifier has to name it.

2. List the wheel directory in the target's overlay:

    ```toml
    [tool.kivy.windows]
    find_links = ["wheels"]
    ```

    Once Kivy has a wheel in `find_links`, it comes only from there, so a Kivy
    release on PyPI doesn't replace your build. See
    [Use your own wheels](dependencies.md#use-your-own-wheels).

3. Lock the target:

    ```bash
    kivyforge lock -p windows
    ```

    If none of the wheels fits, `lock` fails with `KF-LOCK-SOURCE-UNAVAILABLE`.
    Compare the wheel's filename with the target's Python and platform, as in
    step 3 of [Build the wheel](#build-the-wheel).

4. Check the app in the form you ship, then package it:

    ```bash
    kivyforge run -p windows --release
    kivyforge package -p windows
    ```

    `run --release` strips the source as `package` does, so a problem that
    appears only without source shows up before you package. See
    [Test the stripped build before you package](../../concepts/build-vs-package.md#test-the-stripped-build-before-you-package).

## Test another Kivy commit

1. Delete the old wheel from `wheels/`.
2. Build the new commit, as in [Build the wheel](#build-the-wheel).
3. If Kivy's version changed, update the `==` specifier.
4. Re-lock:

    ```bash
    kivyforge lock -p windows
    ```

    Every commit on a Kivy branch usually builds with the same version and
    filename, such as `kivy-3.0.0.dev0-cp313-cp313-win_amd64.whl`. `lock` sees
    that the wheel's hash changed and resolves Kivy again. Every other package
    keeps its locked version.

Two builds of the same commit usually have different hashes, so a wheel rebuilt
on another machine doesn't match the lock. To share a build with your team or
CI, commit the wheel you locked. See
[Build a wheel from a GitHub repository](wheel-from-github.md#lock-the-wheel).

## What's next

- [Manage dependencies and re-lock](dependencies.md)
- [Prebuilt runtimes and wheels](../../concepts/runtimes-and-wheels.md)
- [Build versus package](../../concepts/build-vs-package.md)
