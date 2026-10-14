# Proposal — the app's own package metadata

> Status: **plan, 2026-10-13. Not implemented; waiting for approval.** Follows
> [#122](https://github.com/ElliotGarbus/kivyforge/issues/122): #115 excluded
> the `*.egg-info` that a src-layout app's `importlib.metadata` reads, and an
> app that finds its plugins through entry points stopped starting; #123
> reverted it. The assumptions below were each tested before this was written:
> [`package-metadata-spike-findings.md`](package-metadata-spike-findings.md) (F1-F5,
> S0-S7). Two of them were wrong, and the placement changed because of it.

## 1. Problem

A packaged app is not an installed distribution. `importlib.metadata` inside it
finds the app's own name, version and entry points only through whatever
`<name>.egg-info` happens to sit in `app_dir`, which today ships by accident:

- it exists only after a setuptools editable install (`pip install -e .`,
  `uv sync`) or kivyforge's own lookup of a dynamic version, so hatch, flit,
  pdm and poetry projects, flat layouts and fresh CI checkouts have none;
- it records whatever last wrote it, so its version and entry points can be
  older than the build (the #122 reporter's said `0.1.dev27+g5f2870081`);
- it carries host paths (`SOURCES.txt`).

Apps do read this metadata: `version()`, `distribution()` and `entry_points()`
(S7), and plugin-based apps cannot start without it (#122).

## 2. Design

**kivyforge writes the app's metadata itself, into a directory of its own that
comes first on the app's import path.**

### 2.1 What is written

`<normalized>-<version>.dist-info/`, where `<normalized>` is the project name
lowercased with runs of `-_.` replaced by `_` (F5: `importlib.metadata` reads
the name from the text before the folder's first hyphen, and all five backends
name it this way):

| File | Content |
|---|---|
| `METADATA` | `Metadata-Version: 2.1`, `Name:` as written in `[project]`, `Version:` the resolved version (the same value as the plist, `versionName` and the Windows resource) |
| `entry_points.txt` | `[project.scripts]` as `console_scripts`, `[project.gui-scripts]` as `gui_scripts`, each `[project.entry-points."<group>"]` as its group, values verbatim. Omitted when there are none. |
| `INSTALLER` | `kivyforge` |

Deliberately absent: `RECORD` (`files()` returns `None`), `Requires-Dist`
(`requires()` returns `None`). `Requires-Dist` would let
`pkg_resources.require()` fail on dependencies that `exclude` lists remove on
purpose. S1 showed `[project]` read this way matches setuptools, hatchling,
pdm-backend, flit-core and poetry-core (poetry differs only in spacing inside
an extras marker).

### 2.2 Where it goes

A dedicated directory in the bundle, `_kivyforge_meta/` (name to settle in
review), placed **first** on the app's import path, before `app/`. Not `app/`,
and not the dependencies directory:

- **Not alongside a stale `egg-info`:** within one directory the winner follows
  `os.listdir` order (F1).
- **Not the dependencies directory:** `app/` comes before it on macOS, iOS and
  Android (F3), so a stale `egg-info` in `app/` shadowed a dist-info there on
  all three.
- **First wins everywhere measured:** a directory at `sys.path[0]` shadowed both
  for `version()` and `entry_points()` on CPython 3.13 (macOS), 3.14 (Android)
  and 3.15 (iOS) (F4).
- **iOS debug builds** symlink `app_dir`, so nothing can be written into, or
  excluded from, the app copy there. A separate directory sidesteps that.

Where each platform's path is built (all kivyforge-generated):

| Platform | Path set in | Change |
|---|---|---|
| Android | `bootstrap/templates/cpp/main.c` (`module_search_paths`: stdlib, bootstrap, app, site-packages) | Add the metadata directory before `app` |
| iOS | `templates/kivyforge_bootstrap.m` (`PYTHONPATH` = stdlib, lib-dynload, app) | Prepend it; add the directory to the generated Xcode project's resources |
| macOS | `launcher.py` (C source, `pypath` = `app:lib`) | Prepend it |
| Linux | `launcher.py` (`AppRun`: `PYTHONPATH="$HERE/usr/app:$HERE/usr/lib"`) | Prepend it |
| Windows | the generated `_kivyforge_bootstrap.py` (rendered by `launcher/__init__.py`), which does `sys.path.insert(0, app_dir)` | Insert it ahead of `app_dir` there; the vendored launcher `.exe` (which also sets `PYTHONPATH=<bundle>\app`) needs no rebuild, because entries inserted at runtime come first |

### 2.3 The stale `egg-info`

Once the generated metadata comes first, a stale `egg-info` in `app/` is
shadowed for `version()`, `distribution()` and `entry_points()` (F4).
`distributions()` still lists both, so code that iterates every distribution
sees a duplicate. See decision D3.

## 3. Decisions needed

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | A setuptools project with no entry points in `[project]` but some in `setup.cfg`/`setup.py` (F2: setuptools still uses them, with a deprecation warning; found in real Kivy projects) | (a) error; (b) warn, and generate no metadata so the dev `egg-info` keeps working; (c) run the backend for those projects and take its `entry_points.txt` | **(b)**: never a regression, and the warning says to move them into `[project]`, which setuptools' own deprecation asks for. Detect: backend is setuptools, `[project]` has none of `scripts`/`gui-scripts`/`entry-points`, and `setup.cfg` has `[options.entry_points]` or `setup.py` mentions `entry_points`. |
| D2 | `entry-points`, `scripts` or `gui-scripts` listed in `[project].dynamic` | error; or treat as D1 (b) | **Treat as D1 (b)**, with the same warning: kivyforge cannot know them without the backend. |
| D3 | Keep shipping a stale `egg-info` from `app_dir` | keep; or exclude in copies (not possible in iOS debug) | **Exclude when kivyforge generated metadata** (removes the `distributions()` duplicate and host paths), **keep it in the D1/D2 cases** where it is the only source. |
| D4 | Directory name | `_kivyforge_meta`, `_app_metadata`, ... | `_kivyforge_meta` |
| D5 | Release | with the next release after `3.0.0.dev1` | Ship `3.0.0.dev1` with the revert (already on `main`); this goes in the next one. |

## 4. Steps

0. **Guard today's behaviour first:** a device-side metadata check (section 5,
   layer 3) run against `main`'s `egg-info` behaviour. It must pass on `main`
   before anything changes, so the redesign is measured against it.
1. Write the hermetic and live tests of section 5. On `main`, the
   "no `egg-info`" cases must fail (that is the gap) and the rest pass.
2. Generator (`kivyforge/bundle/app_metadata.py`), D1/D2 detection and warning
   code, D3 exclusion.
3. Path changes per platform (2.2 table) and staging of the directory.
4. Docs: the versioning guide's metadata section, CHANGELOG.
5. Device runs on this Mac (section 5, layer 3), the reporter's app (#122),
   then Linux and Windows on their hosts (#118-style prompts).

## 5. Test plan

Every layer below except 5 is fully automated and runs on this Mac (macOS
host, iOS simulator, Android emulator). Each test names the finding or
assumption it guards.

### Layer 1 — hermetic (default `pytest`, every CI run)

- **Generator:** name normalization (`Meta.Probe_App` gives
  `meta_probe_app-1.2.3.dist-info`, F5); `scripts` and `gui-scripts` mapped to
  `console_scripts`/`gui_scripts`; dotted groups; extras and module-only values
  kept verbatim; no `entry_points.txt` when there are none; a local version in
  the folder name; byte-identical output across runs (Android's per-ABI identity
  check, deterministic artifacts).
- **Lookup contract:** `importlib.metadata`, pointed at the generated
  directory, finds the app by every alias (`metaprobe-app`, `metaprobe_app`,
  `Metaprobe.App`), with `version()`, `metadata()["Name"]` and
  `entry_points()` correct and `files()`/`requires()` `None` (S0).
- **Placement, per platform:** the staged tree holds the directory; and the
  platform's path configuration, read from the **rendered** launcher or
  bootstrap source (not a list in the test), puts it before `app` (F3). One test
  per platform: Android `main.c`, iOS bootstrap, macOS launcher, Linux `AppRun`,
  Windows `launcher/__init__.py`.
- **Precedence:** with a stale `egg-info` planted in `app_dir`,
  `importlib.metadata` over the platform's real path order returns the
  generated version and entry points (F1, F4).
- **Consistency:** the generated `Version:` equals the plist, `versionName` and
  Windows resource version, for static, dynamic and override sources.
- **D1/D2:** each detection case warns with the new code and generates nothing;
  a project with entry points in `[project]` generates them and does not warn.
- **D3:** the `egg-info` is excluded when metadata was generated and kept
  otherwise, on every copy path (the #123 regression test, generalized).

### Layer 2 — live backends (opt-in `--app-metadata-live`; needs network)

The S1 and S2 spikes as tests, so a backend changing behaviour fails here
first: the five backends agree with the generator on a project exercising every
entry-point form; and setuptools' handling of `setup.cfg`/`setup.py` entry
points (F2) is pinned, including the warning text D1 relies on.

### Layer 3 — inside real apps, automated on this Mac

A probe fixture, `tests/fixtures/apps/metaprobe/`: one project with macOS, iOS
and Android overlays, a `main.py` that reports what `importlib.metadata` sees
and exits, two local dependency wheels with entry points, and entry points of
its own in `[project]` (a group, `scripts`, `gui-scripts`). It is the S3 probe,
kept.

A driver, `tests/integration/test_app_metadata_devices.py` (marker
`requires_toolchain`), selected with `--metaprobe macos,ios-sim,android-emu`.
For each platform it locks, builds, launches and collects the report with no
manual step: `run -p macos [--release]` stdout; `build -p ios --simulator`,
`simctl boot`/`install`/`launch` and the app's data container; `run -p android
--emulator --no-follow [--release]`, `run-as` for debug and per-key logcat
lines for release. Variants, each with its own assertions:

| Variant | Asserts |
|---|---|
| static version, no `egg-info` | the app finds its own name, version and every entry point it declares; a dependency's entry point loads |
| stale `egg-info` planted in `app_dir` | the generated metadata wins for `version()` and `entry_points()`; with D3, the `egg-info` is absent from copies (and shadowed on iOS debug) |
| dynamic version (git tag, one commit past) | the reported version equals `data.version` and the plist/`versionName` |
| `setup.cfg` entry points (D1) | the build warns; the dev `egg-info` still provides them |
| release flavor (macOS, Android) | the same, with byte-compiled, source-stripped apps |

Expected wall time on this Mac, from the spikes: macOS about 10 s per build,
iOS about 20 s per build plus launch, Android about 55 s per flavor plus the
first emulator boot. The emulator and simulator are booted by the driver.

### Layer 4 — CI (existing jobs, no new runners)

- **Android:** the contract self-test (`_kivyforge_selftest.py`), which every
  emulator job already runs (API 24 and 35), checks the app's own metadata:
  name, version, and the entry points kivyforge generated. kivyforge renders the
  expected values into it, so it needs no fixture.
- **iOS Simulator job and Integration (macOS) job:** run the layer 3 driver for
  their platform.
- **Live backends:** the layer 2 tests in the macOS integration job.

### Layer 5 — not on this Mac

Linux and Windows runtimes (path order there is only read from source today),
physical devices, and the #122 reporter's app as the acceptance case before
release.

## 6. Done when

- Layers 1-4 pass, and layer 3's "no `egg-info`" variant, which fails on
  `main` today for any project without a dev install, passes.
- The #122 reporter confirms their APK.
- Linux and Windows have a dated row in `test-matrix.md` §7.
