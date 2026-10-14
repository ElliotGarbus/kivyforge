# Findings — app package metadata spikes

> 2026-10-13, macOS host. Spikes for
> [`package-metadata-proposal.md`](package-metadata-proposal.md), run before any
> implementation, after the #115/#122 regression: kivyforge excluded the
> `*.egg-info` that an app's `importlib.metadata` depends on, because nobody
> checked what reads it. Each spike targets one assumption of the proposal; two
> of them turned out false or more subtle than assumed, and one changed the
> design. Throwaway code only (scratchpad); nothing here is product code.

## Environment

| Item | Value |
|---|---|
| Host | macOS 26.6.2, Apple Silicon; Xcode 27.0 |
| Host Python | 3.14.7, pip 26.2.1 |
| Runtimes measured | macOS `.app`: CPython **3.13.14**. iOS simulator (iPhone 17 Pro): CPython **3.15.0b4**. Android emulator (`kf_api35_arm64`, API 35, `arm64-v8a`): CPython **3.14.6** |
| Backends (S1, S2) | setuptools 84.0.0, hatchling 1.32.4, pdm-backend 2.5.0, flit_core 4.1.0, poetry-core 2.5.0 |
| kivyforge | `main` at `f52ce1e2` (the #123 revert), run from a worktree |

## Findings, surprises first

### F1. Inside one directory, which copy of a package wins is undefined (S0, S3)

CPython's `importlib.metadata` (`Lookup.__init__`) files `.dist-info` and
`.egg-info` folders of the same normalized name into **one list, in
`os.listdir` order**. `version()`/`distribution()` take the first;
`entry_points()` keeps only the first distribution of each name. So a stale
`egg-info` next to a fresh `.dist-info` wins or loses depending on the
filesystem's directory order:

| Where | Names | Winner |
|---|---|---|
| Host temp dir (APFS) | `metaprobe_app.egg-info` vs `metaprobe_app-1.2.3.dist-info` | **egg-info** (0.0.1), whichever was created first |
| macOS `.app`, iOS simulator, Android emulator | `probe_same.egg-info` vs `probe_same-2.0.dist-info` | dist-info (2.0) |

Same filesystem, different names, different winner. **The generated metadata
must never share a directory with a possibly stale `egg-info`.**

### F2. setuptools still honours `setup.cfg` / `setup.py` entry points (S2)

The proposal assumed that, with a `[project]` table, setuptools ignores entry
points declared outside it unless `entry-points` is in `dynamic`. With
setuptools 84.0.0:

| `[project]` declares entry points? | `setup.cfg` / `setup.py` declares them? | In the wheel |
|---|---|---|
| no, not dynamic | yes | **the `setup.cfg`/`setup.py` ones**, with `_MissingDynamic: entry-points defined outside of pyproject.toml is ignored` (a deprecation warning: "future versions ... will not consider this value") |
| no, dynamic | yes | the `setup.cfg`/`setup.py` ones, no warning |
| yes | yes | only `[project]`'s |

So reading `[project]` alone **silently misses** entry points for a setuptools
project that still declares them the old way. Not hypothetical: GitHub code
search (S7) finds `entry_points={...}` in `setup.py` across Kivy projects
(`kivy/kivy_pong_demo`, `MallteamDev/KivyMD`, `Bakterija/mmplayer`, ...).

### F3. The app directory comes before dependencies on every platform measured (S3)

`sys.path` inside the built app, in order:

| Runtime | Order |
|---|---|
| macOS `.app` | `Resources/app`, `Resources/lib` (dependencies), then the stdlib |
| iOS simulator | stdlib, `lib-dynload`, **`app`**, `python315.zip`, `site-packages`, `pip-deps` (dependencies) |
| Android emulator | `_python_bundle/stdlib`, `bootstrap`, **`app`**, `site-packages` (dependencies) |

(Linux `AppRun` exports `PYTHONPATH="$HERE/usr/app:$HERE/usr/lib"`, and the
Windows launcher puts `<bundle>\app` first; both read from source, not run.)

Consequence, measured on all three runtimes: a stale `egg-info` in `app/`
**shadows** a `.dist-info` in the dependencies directory. `probe-cross` reported
0.0.1 (the `egg-info`) and only the `egg-info`'s entry point, never the wheel's.
Placing generated metadata among the dependencies would lose to a stale dev
install on macOS, iOS and Android.

### F4. A dedicated metadata directory placed first wins everywhere (S3, phase 2)

The probe inserted its own directory at `sys.path[0]` holding
`probe_cross-3.0.dist-info`. On macOS (3.13.14), iOS (3.15.0b4) and Android
(3.14.6) alike: `version("probe-cross") == "3.0"`, and `entry_points()` returned
only `cross-gen` -- the stale `egg-info` in `app/` and the dependency's
`.dist-info` were both shadowed, for versions **and** entry points.
`distributions()` still yields all three copies (`AHEAD_n_probe_cross_dists 3`),
so code that iterates every distribution itself would see duplicates.

### F5. The folder name must be the normalized name (S0)

`importlib.metadata` derives a folder's distribution name from the text before
its **first hyphen**. Found by `version("metaprobe-app")`:

| Folder | Found |
|---|---|
| `metaprobe_app-1.2.3.dist-info` | yes |
| `metaprobe_app-1.2.4.dev3+g1a2b.dist-info` (local version) | yes |
| `metaprobe-app-1.2.3.dist-info` (unnormalized) | **no** |
| `whatever.dist-info` | **no** |

Lookups by `metaprobe_app`, `Metaprobe.App` and `METAPROBE-APP` all resolve.
All five backends (S1) name the folder the same way, lowercase and normalized
(`meta_probe_app-1.2.3.dist-info`), while `METADATA`'s `Name:` keeps the name as
written (`Meta.Probe_App`).

## What held

- **S1, `[project]` tables vs real backends (A1).** A project with `scripts`,
  `gui-scripts`, two entry-point groups (one dotted), an entry point with
  extras (`mod:obj [fancy]`) and a module-only entry point. setuptools,
  hatchling, pdm-backend and flit-core produced `entry_points.txt` identical to
  a prototype that reads `[project]` alone; poetry-core wrote `Extra[fancy]` for
  `Extra [fancy]`, the same module, attribute and extras. `scripts` becomes
  `console_scripts` and `gui-scripts` becomes `gui_scripts` in all five.
- **S0, a minimal `.dist-info` is enough.** `METADATA` (Metadata-Version, Name,
  Version) plus `entry_points.txt`, no `RECORD`: `version()`, `metadata()` and
  `entry_points()` work; `files()` and `requires()` return `None`.
- **S3, metadata survives staging and release processing (A5).** On macOS
  (debug and release), the iOS simulator (debug) and Android (debug and
  release), every planted `.dist-info` and `.egg-info` reached the app intact.
  The Android release APK holds `app/main.pyc` and no `main.py`; the macOS
  release log shows the payload byte-compiled ".pyc only". iOS release needs
  signing and was not run.
- **S3, dependencies' metadata survives staging.** A local wheel `probe-dep`
  declaring an entry point reached each platform's dependency directory, and
  `entry_points(group=...)` found it and `.load()` returned `probe_dep.Demo` on
  all three runtimes.

## S7, what apps call (weak evidence)

GitHub code search, files containing both `from kivy` and the term: 26 files
(13 repos) for `importlib.metadata`, 22 for `entry_points`, 100+ for
`pkg_resources`. Fragments are short and include vendored code, so this is a
signal, not a census: `version()` dominates, then `distribution()` and
`entry_points()`; `pkg_resources` use is mostly `resource_filename` (resource
files, not metadata), plus `get_distribution` and `working_set`. Most
`entry_points` hits are **declarations** in `setup.py`, which is what makes F2
matter.

## Method

One probe app (`src/main.py`, ~60 lines) prints, as JSON, `sys.path`, where
`importlib.metadata.distribution()` finds each probe name, all
`entry_points(group="metaprobe.plugins")` with the providing distribution, and
the result of loading a dependency's entry point; it also writes the report to
the app's data directory. Planted in `app_dir`: a stale `probe_stale.egg-info`
(0.0.1), a `probe_gen-1.2.3.dist-info` (candidate placement in `app/`), a
same-directory pair `probe_same.egg-info` (0.0.1) / `probe_same-2.0.dist-info`,
and `probe_cross.egg-info` (0.0.1) shadowing a wheel `probe-cross` 2.0. Two
local wheels (`probe-dep`, `probe-cross`) via `find_links`. Built from copies of
`dice-roller` (macOS), `hello-kivy` (iOS) and `hello-android` (Android) with
`kivyforge run -p macos [--release]`, `build -p ios --simulator` then
`simctl install`/`launch`, and `run -p android --emulator --no-follow
[--release]`. Reports were read from `run`'s stdout (macOS), the app's data
container (iOS), `run-as ... cat files/metaprobe.json` (Android debug) and
per-key logcat lines (Android release; logcat truncates one long line at about
1,000 characters).

## Not covered

Linux and Windows runtimes (path order read from source only); iOS release
(needs signing); a physical device; projects whose entry points come from a
backend plugin rather than a table.
