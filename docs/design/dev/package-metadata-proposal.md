# Proposal — the app's own package metadata

> Status: **plan, revised 2026-10-14. Not implemented; waiting for approval.**
> Follows [#122](https://github.com/ElliotGarbus/kivyforge/issues/122): #115
> excluded the `*.egg-info` that a src-layout app's `importlib.metadata` reads,
> and an app that finds its plugins through entry points stopped starting; #123
> reverted it. Every assumption here was tested before it was written down
> ([`package-metadata-spike-findings.md`](package-metadata-spike-findings.md),
> F1-F6), the design was checked against the PyPA specifications (section 6),
> and compared with how Briefcase solves the same problem (section 7). The
> first draft placed the metadata in a separate directory first on the import
> path (option B); the spec review, Briefcase and the iOS spike (F6) moved the
> recommendation to option A.

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
(S7), plugin-based apps cannot start without it (#122), and Toga builds
`toga.App` on `importlib.metadata.metadata(app_name)` (section 7).

## 2. Design (option A)

**kivyforge writes the app's metadata itself, into the app's own code
directory in the bundle, and removes any `egg-info` from that copy.** This is
where the recording-installed-projects spec puts a `.dist-info` (alongside the
importable modules) and what Briefcase does.

### 2.1 What is written

`<name>-<version>.dist-info/`. Both fields normalized, as the spec requires of
new tools: the name lowercased with runs of `-_.` replaced by `_`, the version
in its normalized PEP 440 form (it contains no `-`). F5: `importlib.metadata`
reads the name from the text before the first hyphen, so an unnormalized name is
not found; all five backends name it this way.

| File | Content |
|---|---|
| `METADATA` | `Metadata-Version: 2.1`, `Name:` as written in `[project]`, `Version:` the resolved version (the same value as the plist, `versionName` and the Windows resource) |
| `entry_points.txt` | `[project.scripts]` as `console_scripts`, `[project.gui-scripts]` as `gui_scripts`, each `[project.entry-points."<group>"]` as its group. Omitted when there are none. |
| `top_level.txt` | The top-level modules and packages of `app_dir`, one per line (Briefcase writes it too). It is what `packages_distributions()` uses to map a module to its distribution. |
| `INSTALLER` | `kivyforge` |

Deliberately absent: `RECORD` (`files()` returns `None`; the spec makes only
`METADATA` mandatory for an installed project, and without `RECORD` tools must
not uninstall or upgrade it, which suits an app bundle), and `Requires-Dist`
(`requires()` returns `None`; it would let `pkg_resources.require()` fail on
dependencies that `exclude` lists remove on purpose). No script wrappers are
created for `console_scripts`/`gui_scripts`: an app bundle has no command line
or `PATH` (section 6, C5).

**Validation (config errors, each tested).** The specs forbid, and backends
reject: `[project.entry-points.console_scripts]` and `.gui_scripts` (they clash
with `scripts`/`gui-scripts`); nested sub-tables under `entry-points`; group
names outside `^\w+(\.\w+)*$`; entry point names containing `=`, starting with
`[`, or starting or ending with whitespace; a `[project].name` that is not a
valid project name (`^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$`,
case-insensitive). kivyforge checks none of these today.

**Writer rules.** `entry_points.txt` is UTF-8 (explicitly; Windows' default
encoding is not), uses `=` as the delimiter, and **preserves case**: Python's
default `configparser` lowercases names (verified: `MyPlugin` became
`myplugin`), so it must not be the writer. Values are written as declared; the
spec only recommends a space before an extras `[`, and readers must accept any
spacing. Output is byte-identical across runs.

### 2.2 Where it goes

Into each platform's copy of `app_dir` in the bundle, after the copy, with
every top-level `*.egg-info` (and any other `.dist-info` of the app's own name)
removed from that copy. The user's source tree is never written to.

| Platform | Copy point | Change |
|---|---|---|
| macOS | `platforms/macos/bundle.py` `_copy_app_sources` | exclude, then write |
| Linux | `platforms/linux/bundle.py` `_copy_app_sources` | exclude, then write |
| Windows | `platforms/windows/bundle.py` `_copy_app_sources` | exclude, then write |
| Android | `platforms/android/stage/bundle.py` `_copy_app` | exclude, then write (the app payload is shared by every ABI, so one copy) |
| iOS | Xcode's Copy Bundle Resources copies the `app` folder reference; the generated **Build Python** script runs after it and before code signing (`buildsettings.py`) | `kivyforge build` stages the `.dist-info` in `<app>-ios/_kivyforge_meta/`; the script deletes `*.egg-info` from the bundle's `app/` and copies the staged folder in. One mechanism for debug and release. |

iOS debug builds keep their link from `<app>-ios/app` to `app_dir` (spec 06's
edit-then-Cmd-R loop): the link lives only in the staging folder, and Xcode
still copies the folder into the bundle on every build (F6). The script refuses
to run if the bundle's `app/` is ever a link, so it can never delete from the
user's tree.

Why not the first draft's option B (a separate directory placed first on the
import path): it works on every runtime measured (F4), but it departs from the
spec's location and rests on how CPython's `importlib.metadata` orders lookups,
which no spec defines. Option A needs neither: with the stale `egg-info` gone,
exactly one copy of the app's metadata exists, so no ordering question arises.
B stays the fallback if A's exclusion ever proves impossible on a platform.

### 2.3 When nothing is generated

In the D1/D2 cases (section 3) kivyforge cannot know the full set of entry
points, so it generates no metadata, does not exclude, and warns: the dev
`egg-info`, if any, ships as it does today. Under option A that never puts two
copies side by side.

## 3. Decisions needed

| # | Question | What the specs say | Options | Recommendation |
|---|---|---|---|---|
| D6 | Placement | The recording-installed-projects spec puts `.dist-info` alongside the importable modules. | A (section 2.2), or B (separate directory first on the path) | **A.** Spec-literal, Briefcase's approach, proven on iOS debug by F6. |
| D1 | A setuptools project with entry points in `setup.cfg`/`setup.py` but none in `[project]` (F2; found in real Kivy projects) | The `pyproject.toml` spec: a backend cannot fill in a key `[project]` does not list in `dynamic`. So **the project has no entry points**; setuptools including them is non-conforming and deprecated (its own warning says so). | (a) follow the spec: generate from `[project]` (none) and warn; (b) compatibility: warn, generate nothing, ship the dev `egg-info` as today; (c) take the backend's real `.dist-info` (PEP 517 `prepare_metadata_for_build_wheel`) | **(b)**, with the warning citing the spec, and ending when setuptools stops including them. (c) is the long-term route (section 7). |
| D2 | `entry-points`, `scripts` or `gui-scripts` listed in `dynamic` | Only the backend supplies a dynamic key, and for table keys a static value may also be present and **extended** by the backend, so static entries are only a minimum. | as D1 | **As D1 (b)**, for both "dynamic only" and "static plus dynamic". The existing rule that rejects `version` declared both ways must not be applied to these keys. |
| D3 | The dev `egg-info` | No spec covers `egg-info`. | exclude when generating, keep otherwise | **Exclude whenever kivyforge generated metadata; keep it in the D1/D2 cases.** Under option A, exclusion is required, not optional. |
| D4 | iOS staging directory name | none | `_kivyforge_meta` | `_kivyforge_meta` (inside `<app>-ios/`, never on the runtime path) |
| D5 | Release | none | | Ship `3.0.0.dev1` with the revert (already on `main`); this goes in the next release. |
| D7 | Extra `METADATA` fields, as Briefcase writes (`Formal-Name`, `App-ID`) | Core metadata allows extra fields only by convention. | add `display_name`/bundle id; or not | **Not now.** Nothing in the Kivy ecosystem reads them. |

## 4. Steps

0. **Guard today's behaviour first:** a device-side metadata check (section 5,
   layer 3) run against `main`'s `egg-info` behaviour. It must pass on `main`
   before anything changes, so the redesign is measured against it.
1. Write the hermetic and live tests of section 5. On `main`, the "no
   `egg-info`" cases must fail (that is the gap) and the rest pass.
2. Generator (`kivyforge/bundle/app_metadata.py`), validation, D1/D2 detection
   and warning code.
3. Copy points (section 2.2): exclusion plus writing on four platforms; iOS
   staging and the Build Python script.
4. Docs: the versioning guide's metadata section, the pyproject reference
   (validation), CHANGELOG.
5. Device runs on this Mac (layer 3), the reporter's app (#122), then Linux and
   Windows on their hosts (#118-style prompts).

## 5. Test plan

Every layer below except 5 is fully automated and runs on this Mac (macOS
host, iOS simulator, Android emulator). Each test names what it guards.

### Layer 1 — hermetic (default `pytest`, every CI run)

- **Generator:** name normalization (`Meta.Probe_App` gives
  `meta_probe_app-1.2.3.dist-info`, F5); `scripts`/`gui-scripts` mapped to
  `console_scripts`/`gui_scripts`; dotted groups; extras and module-only
  values; **case preserved** (`MyPlugin`); **non-ASCII** names written as UTF-8;
  no `entry_points.txt` when there are none; `top_level.txt` lists `app_dir`'s
  top-level modules and packages; a local version in the folder name;
  byte-identical output across runs.
- **Validation:** each spec rule of 2.1 is a config error with the file line.
- **Lookup contract:** `importlib.metadata` over the generated folder finds the
  app by every alias (`metaprobe-app`, `metaprobe_app`, `Metaprobe.App`), with
  `version()`, `metadata()["Name"]`, `entry_points()` and
  `packages_distributions()` correct and `files()`/`requires()` `None` (S0).
- **Exclusion, every copy path:** with a stale `egg-info` (and a stale
  `<app>-*.dist-info`) planted in `app_dir`, each platform's real copy function
  leaves exactly the generated folder; and the user's `app_dir` is unchanged
  afterwards. The #123 regression test, generalized.
- **iOS script:** the rendered Build Python script contains the link guard, the
  `egg-info` deletion and the copy from `_kivyforge_meta`, after the existing
  `pip-deps` step; `kivyforge build` stages the folder there.
- **Consistency:** the generated `Version:` equals the plist, `versionName` and
  Windows resource version, for static, dynamic and override sources.
- **D1/D2:** each detection case (`setup.cfg`, `setup.py`, dynamic only,
  static plus dynamic) warns with the new code, generates nothing and excludes
  nothing; a project with entry points only in `[project]` generates them and
  does not warn.

### Layer 2 — live backends (opt-in `--app-metadata-live`; needs network)

The S1 and S2 spikes as tests, so a backend changing behaviour fails here
first: setuptools, hatchling, pdm-backend, flit-core and poetry-core agree with
the generator on a project exercising every entry-point form; and setuptools'
handling of `setup.cfg`/`setup.py` entry points (F2) is pinned, including the
deprecation warning D1 cites. When setuptools stops including them, this test
says D1's allowance can go.

### Layer 3 — inside real apps, automated on this Mac

A probe fixture, `tests/fixtures/apps/metaprobe/`: one project with macOS, iOS
and Android overlays, a `main.py` that reports what `importlib.metadata` sees
and exits, two local dependency wheels with entry points, and entry points of
its own in `[project]` (a group, `scripts`, `gui-scripts`). It is the S3/S8
probe, kept.

A driver, `tests/integration/test_app_metadata_devices.py` (marker
`requires_toolchain`), selected with `--metaprobe macos,ios-sim,android-emu`.
For each platform it locks, builds, launches and collects the report with no
manual step, booting the simulator or emulator itself: `run -p macos
[--release]` stdout; `build -p ios --simulator`, `simctl install`/`launch` and
the app's data container; `run -p android --emulator --no-follow [--release]`,
`run-as` for debug and per-key logcat lines for release. It refuses to collect
a report when the build failed (the S8 run showed a stale install answering
otherwise). Variants:

| Variant | Asserts |
|---|---|
| static version, no `egg-info` | the app finds its own name, version and every entry point it declares; a dependency's entry point loads |
| stale `egg-info` planted in `app_dir` | exactly one copy of the app's metadata in the bundle (the generated one); the source tree keeps its `egg-info` |
| iOS, Xcode-only rebuilds (the captured `xcodebuild` command, as Cmd-R) | no-change rebuild, a `src/` edit, and a rewritten dev `egg-info`: each leaves only the generated metadata, shows the edit, and keeps a valid signature (F6) |
| dynamic version (git tag, one commit past) | the reported version equals `data.version` and the plist/`versionName` |
| `setup.cfg` entry points (D1) | the build warns; the dev `egg-info` still provides them |
| release flavor (macOS, Android) | the same, with byte-compiled, source-stripped apps |

Expected wall time on this Mac, from the spikes: macOS about 10 s per build,
iOS about 20 s per kivyforge build and less per Xcode-only rebuild, Android
about 55 s per flavor plus the first emulator boot.

### Layer 4 — CI (existing jobs, no new runners)

- **Android:** the contract self-test (`_kivyforge_selftest.py`), which every
  emulator job already runs (API 24 and 35), checks the app's own metadata:
  name, version, and the entry points kivyforge generated. kivyforge renders the
  expected values into it, so it needs no fixture.
- **iOS Simulator job and Integration (macOS) job:** run the layer 3 driver for
  their platform.
- **Live backends:** the layer 2 tests in the macOS integration job.

### Layer 5 — not on this Mac

Linux and Windows builds (their copy points are covered by layer 1, but no app
has run there), physical devices, and the #122 reporter's app as the
acceptance case before release.

## 6. Conformance with the PyPA specifications

Reviewed 2026-10-14: recording installed projects, core metadata (2.6 is the
latest), entry points, `pyproject.toml`, binary distribution format, name
normalization.

| # | Finding | Resolution |
|---|---|---|
| C1 | The `.dist-info` belongs alongside the importable modules; option B put it elsewhere. | Option A (2.2). |
| C2 | Backends must reject reserved and nested entry-point tables; group and entry point names have rules; `Name` must be a valid project name. | Validation in 2.1. |
| C3 | `entry_points.txt` is UTF-8 with case-sensitive names and `=` delimiters. | Writer rules in 2.1. |
| C4 | Table keys such as `entry-points` may be both static and dynamic; the backend may append. | D2 covers "static plus dynamic". |
| C5 | Install tools are expected to create wrappers for `console_scripts`/`gui_scripts`. | Recorded, no wrappers created (2.1). |

Consistent with the specs: normalized folder name (both fields); only `METADATA`
mandatory; `Metadata-Version: 2.1` (builders may use the lowest version holding
their fields); `Requires-Dist` optional; extras in entry points no longer
recommended but readable; static `[project]` values cannot be changed by a tool,
which is why reading them gives what a backend would produce (S1).

**Not covered by any spec:** which copy wins when a project appears twice on the
path (F1, F4). Option A avoids relying on it by ensuring there is one copy;
layer 3 checks that on every platform this Mac runs.

## 7. Comparison with Briefcase

Source: `beeware/briefcase` `main` (`bffc7303`, 2026-10-13), `beeware/toga`.

| | Briefcase | This proposal |
|---|---|---|
| Who writes the metadata | Briefcase (`write_dist_info`), from its config | kivyforge, from `[project]` |
| Files | `INSTALLER`, `WHEEL`, `METADATA` (with `Formal-Name`, `App-ID`), `top_level.txt` | `INSTALLER`, `METADATA`, `entry_points.txt`, `top_level.txt` |
| Location | in the app folder (option A) | option A |
| How code reaches the app | copied fresh every build, every platform | copied, except iOS debug's staging link (handled by the Xcode script) |
| What is copied | the package directories (`sources = ["src/helloworld"]`), so the `egg-info` in `src/` never comes along | all of `app_dir` (`src/`), hence the exclusion |
| Entry points | not supported (beeware/briefcase#2868 open) | supported |
| `setup.py`/`setup.cfg` metadata | not supported (beeware/briefcase#515 open) | D1 |
| Direction | let the build backend produce it, `pip install . --target` (beeware/briefcase#2867) | D1 (c), later |

Toga (`toga.App`) reads `Formal-Name`, `App-ID` and `Version` through
`importlib.metadata.metadata(app_name)`: a framework built on generated app
metadata. Briefcase's dev mode writes `{module_name}.dist-info` (no version)
into the user's source tree; kivyforge's design writes nothing there.

## 8. Done when

- Layers 1-4 pass, and layer 3's "no `egg-info`" variant, which fails on
  `main` today for any project without a dev install, passes.
- The #122 reporter confirms their APK.
- Linux and Windows have a dated row in `test-matrix.md` §7.
