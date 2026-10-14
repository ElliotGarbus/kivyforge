---
title: Set the app version
sources:
  - docs/design/dev/dynamic-version-proposal.md
  - docs/design/dev/package-metadata-proposal.md
  - kivyforge/bundle/app_metadata.py
  - kivyforge/versioning.py
  - kivyforge/config/loader.py
  - kivyforge/config/version.py
---

# Set the app version

kivyforge writes your app's version into every artifact: Android's
`versionName`, Apple's `CFBundleShortVersionString`, the Windows version
resource, and the Linux and Windows file names. This page shows the three ways
to give it that version, and what each one does to your build.

## Before you begin

- A project with a `[project]` table in `pyproject.toml`.
- For a version taken from git: a build backend plugin such as setuptools-scm
  or hatch-vcs, and a git checkout with tags.

## Choose where the version comes from

kivyforge takes the first of these that applies:

| Source | How | Build backend runs? |
|---|---|---|
| Override | `--app-version 1.2.3` on `build`, `package` or `run`; or the `KIVYFORGE_APP_VERSION` environment variable. The flag wins when both are set. | No |
| Static | `version = "1.2.3"` in `[project]`. | No |
| Dynamic | `dynamic = ["version"]` in `[project]`. | Yes, through pip |

Every version must follow PEP 440, the Python version standard. kivyforge
writes the normalized form, so `v1.2` becomes `1.2` and `1.0-beta` becomes
`1.0b0`. A version that PEP 440 can't parse, such as `1.0.0-SNAPSHOT`, fails
with an error that names the line, the flag, or the variable.

## Take the version from git

1. Declare the version as dynamic and configure your build backend. For
   setuptools-scm:

    ```toml
    [build-system]
    requires = ["setuptools>=64", "setuptools-scm>=8"]
    build-backend = "setuptools.build_meta"

    [project]
    name = "myapp"
    dynamic = ["version"]

    [tool.setuptools_scm]
    ```

2. Build as usual:

    ```bash
    kivyforge build -p android --debug
    ```

    kivyforge asks pip to prepare your project's metadata, and prints the
    version it got:

    ```text
    Resolving the version with setuptools.build_meta (pip) ...
    Version 1.2.4.dev3+g1a2b3c (from setuptools.build_meta, via pip)
    ```

pip runs your build backend in a temporary environment, so the backend doesn't
need to be installed alongside kivyforge. This works whether you installed
kivyforge with `uv tool`, pipx, or as a dependency of your project.

Only `build`, `package` and `run` look up the version. `lock`, `doctor`,
`status` and `clean` never run pip, and a new commit doesn't make your lock
out of date.

### The first build needs the network

pip downloads your build backend the first time. Later builds use pip's cache.
To build offline, either:

- Pass `--app-version` with the version you want.
- Install the backend alongside kivyforge and pass `--no-build-isolation`:

    ```bash
    uv tool install kivyforge --with setuptools-scm
    kivyforge build -p android --debug --no-build-isolation
    ```

!!! warning
    With `--no-build-isolation`, pip skips installing anything the backend asks
    for at build time. A project that gets setuptools-scm through
    `setup_requires` in `setup.py` then reports version `0.0.0` without an
    error. Use `--no-build-isolation` only when you know the environment has
    everything the backend needs.

pip uses its own index settings (`pip.conf`, `PIP_INDEX_URL`), not uv's. If
your backend comes from a private index, configure pip for it too.

### Fetch tags in CI

setuptools-scm reads the latest tag. A shallow CI checkout has no tags, so the
version comes out as something like `0.1.dev1+g1a2b3c`. kivyforge prints the
version it used; check that line in your CI log. With GitHub Actions, fetch
the full history:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
```

Or pass the version your pipeline already knows with `--app-version`.

## A build can change your checkout

When kivyforge looks up a dynamic version, your build backend runs inside your
project, exactly as it does for `pip install .`. kivyforge doesn't undo what it
writes:

| File | When | What to do |
|---|---|---|
| `<name>.egg-info/`, in `src/` or the project root | setuptools, when pip installs the backend | Add `*.egg-info/` to `.gitignore`. It stays out of the app: kivyforge writes the app's own metadata instead (below). |
| setuptools-scm's `version_file`, such as `src/myapp/_version.py` | Every build that looks up the version | Don't commit it; setuptools-scm's header for the file says the same. |

While an `egg-info` folder sits in your project root, Python started from that
directory, such as `uv run pytest`, finds it before the installed copy of your
project. `importlib.metadata.version("myapp")` then reports the version of the
last kivyforge build.

## Read your package metadata inside the app

!!! note "Preview"
    This describes behavior that is on `main` but not yet in a released
    version. It will ship in a future release. In 3.0.0.dev1 and earlier, the
    app's only metadata is a development `<name>.egg-info` that happens to sit
    in `app_dir`.

A packaged app isn't an installed Python distribution, so kivyforge writes its
metadata into the app itself, on every platform: a `<name>-<version>.dist-info`
folder beside your code, made from `[project]`. Inside the app,
`importlib.metadata` then finds:

| Call | Returns |
|---|---|
| `version("myapp")` | The version of this build, the same value as `versionName` or `CFBundleShortVersionString`. |
| `metadata("myapp")["Name"]` | `[project].name` as you wrote it. |
| `entry_points(group="myapp.plugins")` | The groups in `[project.entry-points]`. `[project.scripts]` and `[project.gui-scripts]` are the `console_scripts` and `gui_scripts` groups. |
| `packages_distributions()` | Your app's top-level modules and packages in `app_dir`, mapped to your app. Folders without an `__init__.py`, such as asset folders, aren't listed. |
| `files()`, `requires()` | `None`. kivyforge records neither the app's files nor its dependencies. |

The name is matched as Python normalizes it: for a project named `my-app`,
`version("my_app")` and `version("My.App")` find it too.

A development `egg-info` folder in `app_dir`, from `pip install -e .`,
`uv sync` or kivyforge's own lookup of a dynamic version, stays in your source
tree but not in the app. So does every other `*.egg-info` folder at the top of
`app_dir`, such as one left by a project you renamed: `entry_points()` would
still collect its entry points. The app always sees the metadata of the build
you made.

### Declare entry points in `[project]`

kivyforge reads entry points from `[project]` only:

```toml
[project.entry-points."myapp.plugins"]
checked = "myapp.boards:Checked"
```

Quote a group name that contains a dot. Without the quotes, TOML reads
`[project.entry-points.myapp.plugins]` as a group `myapp` holding a nested
table, which kivyforge rejects.

A setuptools project that declares entry points only in `setup.cfg`
(`[options.entry_points]`) or `setup.py` (`entry_points=`) fails to build with
`KF-METADATA-ENTRY-POINTS-OUTSIDE-PROJECT`. Move them into
`[project.entry-points]`, console scripts into `[project.scripts]` and GUI
scripts into `[project.gui-scripts]`. setuptools still reads them from those
files, but has deprecated doing so for a project with a `[project]` table. An
empty `[project.entry-points]` table doesn't count as declaring them.

### Let your build backend compute entry points

When `[project].dynamic` lists `entry-points`, `scripts` or `gui-scripts`, only
your build backend knows the full set. kivyforge then writes no metadata,
leaves `app_dir` as it is, and warns with `KF-METADATA-NOT-GENERATED`. A
development `egg-info` in `app_dir` is then the app's only metadata, so run
`pip install -e .` (or `uv sync`) before each build to keep it current.

### Rebuild in Xcode

On iOS, a build you start in Xcode, such as Run (Cmd-R), uses the metadata the
last `kivyforge build -p ios` or `kivyforge run -p ios` wrote. The
`Info.plist` version comes from the same command, so the two always agree.
After a commit changes a dynamic version, run `kivyforge build -p ios` before
building in Xcode.

### Read the version

`importlib.metadata.version("myapp")` gives the version inside the app. A
module in `app_dir` also gives it when you run your code from source without
installing it. Have setuptools-scm write the version into one:

```toml
[tool.setuptools_scm]
version_file = "src/_version.py"
```

```python
from _version import version as __version__
```

kivyforge copies the file into the app with the rest of `app_dir`.

### Pin a version and keep the file current

`--app-version` skips the build backend, so `version_file` keeps whatever the
last backend run wrote, and kivyforge warns with
`KF-VERSION-FILE-NOT-REFRESHED`. To pin a version and refresh the file, set the
plugin's own override instead of `--app-version`:

```bash
SETUPTOOLS_SCM_PRETEND_VERSION=1.2.3 kivyforge package -p ios
```

hatch-vcs reads the same variable.

## Versions for the App Store

App Store Connect accepts one to three dot-separated numbers in
`CFBundleShortVersionString`, and refuses anything else at upload with error
ITMS-90060. kivyforge writes your version as is and checks it where a build is
headed:

| Build | Version like `1.2.4.dev3+gabc` or `1.0rc1` |
|---|---|
| Simulator, device, and other debug builds | Written as is, no message. |
| iOS export with `--export-method ad-hoc` or `development`; macOS `package` | Written as is, with a `KF-VERSION-APPLE-FORMAT` warning. |
| iOS export with `--export-method app-store`, the default (`package -p ios`, `build -p ios --release`) | Fails before Xcode runs, with `KF-VERSION-APPLE-FORMAT`. |

To export for the App Store, build from a release tag or pass
`--app-version 1.2.4`.

## Android version codes

`version_code = "auto"` derives the code from the version, and refuses a
pre-release, dev, post or local version. With a dynamic version that is
checked when you build, so a build between tags fails. Build from a release
tag, or set an integer `version_code`.

## What's next

- [Drive kivyforge from CI or an agent](ci-and-agents.md)
- [Exit and diagnostic codes](../../reference/codes.md)
- [Environment variables](../../reference/environment.md)
