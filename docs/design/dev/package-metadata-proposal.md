# Proposal — the app's own package metadata

> Status: **implemented 2026-10-14** on branch `app-metadata-design`, not yet
> released; layers 1-3 pass on this Mac, layer 4 is wired into CI, and of
> layer 5 a physical iPhone has run (I8), Windows (I9, 2026-10-17) and Linux
> (I10, 2026-10-18); only the #122 reporter's app is open (section 5). What the implementation decided beyond this plan is in
> section 11. Follows
> [#122](https://github.com/ElliotGarbus/kivyforge/issues/122): #115 excluded
> the `*.egg-info` that a src-layout app's `importlib.metadata` reads, and an
> app that finds its plugins through entry points stopped starting; #123
> reverted it. Every assumption here was tested before it was written down
> ([`package-metadata-spike-findings.md`](package-metadata-spike-findings.md),
> F1-F7), the design was checked against the PyPA specifications (section 6) and
> compared with Briefcase (section 7). Decisions are in section 3, answered
> questions in section 10.

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

## 2. Design

**kivyforge writes the app's metadata itself, from `[project]`, into the app's
own code directory in the bundle, and removes any development `egg-info` from
that copy (option A).** This is where the recording-installed-projects spec
puts a `.dist-info` (alongside the importable modules) and what Briefcase does.

### 2.1 What is written

`<name>-<version>.dist-info/`. Both fields normalized, as the spec requires of
new tools: the name lowercased with runs of `-_.` replaced by `_`, the version
in its normalized PEP 440 form (which contains no `-`). F5: `importlib.metadata`
reads the name from the text before the first hyphen, so an unnormalized name is
not found; all five backends name it this way.

| File | Content |
|---|---|
| `METADATA` | `Metadata-Version: 2.1`, `Name:` as written in `[project]`, `Version:` the resolved version (the same value as the plist, `versionName` and the Windows resource) |
| `entry_points.txt` | `[project.scripts]` as `console_scripts`, `[project.gui-scripts]` as `gui_scripts`, each `[project.entry-points."<group>"]` as its group. Omitted when there are none. |
| `top_level.txt` | Every top-level `*.py` module and every top-level directory containing an `__init__.py` in `app_dir`, computed from the source before byte-compiling; `main` included. Asset folders and directories without an `__init__.py` are not listed (setuptools' default). |
| `INSTALLER` | `kivyforge` |

`top_level.txt` is what makes `packages_distributions()` work without a
`RECORD`. It is a setuptools convention, not a spec: of the five backends only
setuptools writes it (F7); the others rely on `RECORD`, and Briefcase writes
`top_level.txt` too. `RECORD` is not written: it must list every file as finally
shipped, and the payload changes after the copy (byte-compiling,
`strip_source`, Xcode's own steps); `top_level.txt` names only top-level modules,
which those steps do not change. The spec makes only `METADATA` mandatory for an
installed project, and without `RECORD` tools must not uninstall or upgrade it,
which suits an app bundle. `Requires-Dist` is not written either: it would let
`pkg_resources.require()` fail on dependencies that `exclude` lists remove on
purpose. No script wrappers are created for `console_scripts`/`gui_scripts`: an
app bundle has no command line or `PATH` (section 6, C5).

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

Into each platform's copy of `app_dir` in the bundle, after the copy. From that
copy's **top level** kivyforge first removes:

- every `*.egg-info`: in a source tree these are always development-install
  leftovers (modern pip installs `.dist-info`), and `entry_points()` collects
  entry points from every distribution it finds, so an `oldname.egg-info` left
  by a renamed project would keep injecting stale plugins;
- any `.dist-info` of the app's own normalized name.

Other `.dist-info` folders stay: a library vendored with `pip install --target
src ...` keeps its metadata. Nothing deeper than the top level is touched;
setuptools writes only there. The user's source tree is never written to.

| Platform | Copy point | Change |
|---|---|---|
| macOS | `platforms/macos/bundle.py` `_copy_app_sources` | remove, then write |
| Linux | `platforms/linux/bundle.py` `_copy_app_sources` | remove, then write |
| Windows | `platforms/windows/bundle.py` `_copy_app_sources` | remove, then write |
| Android | `platforms/android/stage/bundle.py` `_copy_app` | remove, then write. `assemble_bundle` calls it once, after the per-ABI identity check of the dependencies, so the app payload and its metadata are shared by every ABI. |
| iOS | Xcode's Copy Bundle Resources copies the `app` folder reference; the generated **Build Python** script runs after it and before code signing (`buildsettings.py`) | `kivyforge build` stages the `.dist-info` in `<app>-ios/_kivyforge_meta/`; the script removes the same top-level entries from the bundle's `app/` and copies the staged folder in. One mechanism for debug and release. |

iOS debug builds keep their link from `<app>-ios/app` to `app_dir` (spec 06's
edit-then-Cmd-R loop): the link lives only in the staging folder, and Xcode
still copies the folder into the bundle on every build (F6). The script refuses
to run if the bundle's `app/` is ever a link, so it can never delete from the
user's tree.

Option B, the first draft (a separate directory placed first on the import
path), works on every runtime measured (F4) but departs from the spec's
location and rests on how CPython's `importlib.metadata` orders lookups, which
no spec defines. Option A needs neither: with the development `egg-info` gone,
exactly one copy of the app's metadata exists. B stays the fallback if A's
removal ever proves impossible on a platform.

### 2.3 Entry points declared outside `[project]`: an error

A setuptools project (its `build-backend` is `setuptools.build_meta` or
`setuptools.build_meta:__legacy__`, or it has no `[build-system]`) whose
`[project]` declares none of `scripts`, `gui-scripts` or `entry-points`, and
that declares entry points elsewhere, fails the build with
`KF-METADATA-ENTRY-POINTS-OUTSIDE-PROJECT` (config error, exit 1):

- `setup.cfg` with a non-empty `[options.entry_points]` (parsed exactly);
- `setup.py` whose text mentions `entry_points`.

The message names the file and the fix: move them into `[project.entry-points]`
(or `scripts`/`gui-scripts`). Why an error and not a fallback (decision D1):

- With a `[project]` table, which kivyforge requires, the `pyproject.toml` spec
  says a backend cannot fill in a key `[project]` neither declares nor lists in
  `dynamic`: those entry points are not part of the project's metadata.
  setuptools still includes them, with a deprecation warning saying it will
  stop (F2). PyPA has not deprecated `setup.py` as a configuration file, only
  running it as a command; this specific mix is what is deprecated.
- Every kivyforge project with entry points only in `setup.py`/`setup.cfg` is
  therefore that deprecated mix, and silently dropping its plugins is the #122
  failure. An error at build time cannot be missed; a warning can.
- Apps that keep a `setup.py` for other reasons (a build step) and declare no
  entry points there get correct generated metadata, which a "fall back to the
  `egg-info`" rule would have denied them.

When `[project]` declares entry points **and** `setup.py`/`setup.cfg` declare
others, setuptools uses only `[project]`'s (S2), so generating from `[project]`
matches what setuptools produces; no error. An empty `[project.entry-points]`
table does **not** count as declaring them: setuptools 84 still used
`setup.py`'s entry points with it (F7).

Not detected: a `setup.py` that hides its entry points from a text search (for
example `setup(**config)`) in a project that also has a `[project]` table.
Deprecated twice over and rare; documented, not designed around.

### 2.4 Entry points the backend supplies: a warning

When `entry-points`, `scripts` or `gui-scripts` is listed in `[project].dynamic`
(alone, or alongside static entries, which the spec allows the backend to
extend), only the backend knows the full set. kivyforge then generates nothing,
removes nothing, and warns with `KF-METADATA-NOT-GENERATED` (WARNING; `context`:
`reason` = `dynamic` or `static-and-dynamic`, `fallback` = the path of a
development `egg-info` that ships instead, or `none`, in which case the message
says the app has no package metadata). This is decision D2; the existing rule
that rejects `version` declared both ways does not apply to these keys.

## 3. Decisions (recorded 2026-10-14)

| # | Question | Decision |
|---|---|---|
| D6 | Placement | **Option A** (2.2). |
| D1 | Entry points in `setup.cfg`/`setup.py`, none in `[project]` | **Config error** with the fix (2.3). This replaces the earlier "warn and fall back to the `egg-info`" recommendation, which D1 had accepted; the discussion of Q3 showed it protected only a deprecated, spec-invalid mix while denying correct metadata to other apps with a `setup.py`. |
| D2 | Entry points listed in `dynamic` | **Warn, generate nothing, remove nothing** (2.4). |
| D3 | The development `egg-info` | **Removed whenever kivyforge generates metadata**; left in place in the D2 case. |
| D4 | iOS staging directory | **`_kivyforge_meta`** inside `<app>-ios/`, never on the runtime path. |
| D5 | Release | **Not in `3.0.0.dev1`**, which ships with the revert already on `main`; this goes in the next release. |
| D7 | Briefcase-style `Formal-Name`/`App-ID` fields | **Not now**: nothing in the Kivy ecosystem reads them. |

## 4. Steps

0. **Guard today's behaviour first:** a device-side metadata check (section 5,
   layer 3) run against `main`'s `egg-info` behaviour. It must pass on `main`
   before anything changes, so the redesign is measured against it.
1. Write the hermetic and live tests of section 5. On `main`, the "no
   `egg-info`" cases must fail (that is the gap) and the rest pass.
2. Generator (`kivyforge/bundle/app_metadata.py`), validation, the 2.3 error,
   the 2.4 warning, and the two codes.
3. Copy points (2.2): removal plus writing on four platforms; iOS staging and
   the Build Python script.
4. Docs: the versioning guide's metadata section (including Q5's note), the
   pyproject reference (validation, entry points must be in `[project]`), and
   CHANGELOG with migration notes: entry points declared only in
   `setup.py`/`setup.cfg` must move to `[project]`; spec-invalid entry-point
   tables and project names are now errors; the development `egg-info` no
   longer ships.
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
  no `entry_points.txt` when there are none; `top_level.txt` per the 2.1 rule
  (modules, packages, `main`; not asset folders or `__init__`-less
  directories); a local version in the folder name; byte-identical output
  across runs.
- **Validation:** each spec rule of 2.1 is a config error with the file line.
- **Lookup contract:** `importlib.metadata` over the generated folder finds the
  app by every alias (`metaprobe-app`, `metaprobe_app`, `Metaprobe.App`), with
  `version()`, `metadata()["Name"]`, `entry_points()` and
  `packages_distributions()` correct and `files()`/`requires()` `None` (S0).
- **Removal, every copy path:** with top-level `*.egg-info` folders (the app's
  own and another name's) and a stale `<app>-*.dist-info` planted in
  `app_dir`, plus a vendored library's `.dist-info` and an `egg-info` one level
  down, each platform's real copy function leaves exactly the generated folder
  and the vendored one at the top level, and the deeper `egg-info` untouched;
  the user's `app_dir` is unchanged afterwards. This replaces the #123
  regression test (`tests/bundle/test_app_metadata.py`, Q6), rewritten around
  behaviour: the app's metadata is reachable in every copy.
- **iOS script:** the rendered Build Python script contains the link guard, the
  removals and the copy from `_kivyforge_meta`, after the existing `pip-deps`
  step; `kivyforge build` stages the folder there.
- **Consistency:** the generated `Version:` equals the plist, `versionName` and
  Windows resource version, for static, dynamic and override sources.
- **2.3:** `setup.cfg` with `[options.entry_points]`, and `setup.py` mentioning
  `entry_points`, each fail with `KF-METADATA-ENTRY-POINTS-OUTSIDE-PROJECT`
  and name the file; the same with entry points also in `[project]` generates
  and does not fail; an empty `[project.entry-points]` table still fails; a
  hatchling project with a stray `setup.py` does not fail; a setuptools project
  whose `setup.py` has no entry points generates normally.
- **2.4:** `dynamic` only, and static plus `dynamic`, each warn with
  `KF-METADATA-NOT-GENERATED` (`reason` and `fallback` in `context`), generate
  nothing and remove nothing.

### Layer 2 — live backends (opt-in `--app-metadata-live`; needs network)

The S1 and S2 spikes as tests, so a backend changing behaviour fails here
first: setuptools, hatchling, pdm-backend, flit-core and poetry-core agree with
the generator on a project exercising every entry-point form; setuptools'
handling of `setup.cfg`/`setup.py` entry points (F2), including the empty-table
case (F7) and the deprecation warning 2.3 cites, is pinned. When setuptools
stops including them, this test shows it.

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
| static version, no `egg-info` | the app finds its own name, version and every entry point it declares; `packages_distributions()` maps its modules; a dependency's entry point loads |
| development `egg-info` planted in `app_dir` | exactly one copy of the app's metadata in the bundle (the generated one); the source tree keeps its `egg-info` |
| iOS, Xcode-only rebuilds (the captured `xcodebuild` command, as Cmd-R) | no-change rebuild, a `src/` edit, and a rewritten development `egg-info`: each leaves only the generated metadata, shows the edit, and keeps a valid signature (F6) |
| dynamic version (git tag, one commit past) | the reported version equals `data.version` and the plist/`versionName` |
| dynamic entry points (2.4) | the build warns; a development `egg-info`, when present, still provides them |
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
had run there; both have since, I9 and I10: the driver's `--metaprobe windows`
and `--metaprobe linux` run every layer 3 variant that is not iOS-only), an iOS release archive and physical devices (both need
signing), and the #122 reporter's app as the acceptance case before release.

## 6. Conformance with the PyPA specifications

Reviewed 2026-10-14: recording installed projects, core metadata (2.6 is the
latest), entry points, `pyproject.toml`, binary distribution format, name
normalization.

| # | Finding | Resolution |
|---|---|---|
| C1 | The `.dist-info` belongs alongside the importable modules; option B put it elsewhere. | Option A (2.2). |
| C2 | Backends must reject reserved and nested entry-point tables; group and entry point names have rules; `Name` must be a valid project name. | Validation in 2.1. |
| C3 | `entry_points.txt` is UTF-8 with case-sensitive names and `=` delimiters. | Writer rules in 2.1. |
| C4 | Table keys such as `entry-points` may be both static and dynamic; the backend may append. | 2.4 covers "static plus dynamic". |
| C5 | Install tools are expected to create wrappers for `console_scripts`/`gui_scripts`. | Recorded, no wrappers created (2.1). |
| C6 | With a `[project]` table, keys it neither declares nor lists in `dynamic` cannot come from the backend. | Entry points only in `setup.py`/`setup.cfg` are an error (2.3). |

Consistent with the specs: normalized folder name (both fields); only `METADATA`
mandatory; `Metadata-Version: 2.1` (builders may use the lowest version holding
their fields); `Requires-Dist` optional; extras in entry points no longer
recommended but readable; static `[project]` values cannot be changed by a tool,
which is why reading them gives what a backend would produce (S1).

**Not covered by any spec:** which copy wins when a project appears twice on the
path (F1, F4); option A avoids relying on it by ensuring there is one copy, and
layer 3 checks that on every platform this Mac runs. Also not covered:
`top_level.txt` (a setuptools convention, F7) and `egg-info` in general.

## 7. Comparison with Briefcase

Source: `beeware/briefcase` `main` (`bffc7303`, 2026-10-13), `beeware/toga`.

| | Briefcase | This proposal |
|---|---|---|
| Who writes the metadata | Briefcase (`write_dist_info`), from its config | kivyforge, from `[project]` |
| Files | `INSTALLER`, `WHEEL`, `METADATA` (with `Formal-Name`, `App-ID`), `top_level.txt` | `INSTALLER`, `METADATA`, `entry_points.txt`, `top_level.txt` |
| Location | in the app folder (option A) | option A |
| How code reaches the app | copied fresh every build, every platform | copied, except iOS debug's staging link (handled by the Xcode script) |
| What is copied | the package directories (`sources = ["src/helloworld"]`), so the `egg-info` in `src/` never comes along | all of `app_dir` (`src/`), hence the removal |
| Entry points | not supported (beeware/briefcase#2868 open) | supported, from `[project]` only |
| `setup.py`/`setup.cfg` metadata | not supported (beeware/briefcase#515 open) | entry points there are an error (2.3) |
| Direction | let the build backend produce it, `pip install . --target` (beeware/briefcase#2867) | out of scope (section 9) |

Toga (`toga.App`) reads `Formal-Name`, `App-ID` and `Version` through
`importlib.metadata.metadata(app_name)`: a framework built on generated app
metadata. Briefcase's dev mode writes `{module_name}.dist-info` (no version)
into the user's source tree; this design writes nothing there.

## 8. Done when

- Layers 1-4 pass, and layer 3's "no `egg-info`" variant, which fails on
  `main` today for any project without a dev install, passes.
- The #122 reporter confirms their APK.
- Linux and Windows have a dated row in `test-matrix.md` §7.

## 9. Out of scope

- **Where finished artifacts land and what they are called**
  ([#112](https://github.com/ElliotGarbus/kivyforge/issues/112): Android, macOS
  and iOS outputs into `dist/` with versioned names, as Linux and Windows
  already do). Independent of this proposal: it changes the output step of
  `build`/`package`, not what is inside the app. Its one dependency,
  `ResolvedVersion.filename_part`, is already on `main`. Proposed and
  implemented in [`dist-artifacts-proposal.md`](dist-artifacts-proposal.md)
  (2026-10-15).
- **Metadata produced by the build backend** (PEP 517
  `prepare_metadata_for_build_wheel`), which would cover dynamic entry points
  exactly; Briefcase's stated direction. Not this change.
- **Extra `METADATA` fields** in Briefcase's style (D7).
- **Script wrappers** for `console_scripts`/`gui_scripts` (C5).
- **A configuration switch** to force or skip generation.

## 10. Questions, answered 2026-10-14

| # | Question | Answer |
|---|---|---|
| Q1 | What goes in `top_level.txt`? | Top-level `*.py` modules and directories with an `__init__.py`, from the source before byte-compiling; `main` included (2.1). `top_level.txt` rather than `RECORD`, because the payload keeps changing after the copy. |
| Q2 | How far does the removal reach? | The top level of the app copy: every `*.egg-info`, and a `.dist-info` of the app's own name. Other `.dist-info` folders and anything deeper stay (2.2). |
| Q3 | How should entry points in `setup.cfg`/`setup.py` be detected and handled? | Spec-strict: a config error when detected and `[project]` declares none (2.3). Alternatives considered: fall back to the development `egg-info` (denies correct metadata to every app with a `setup.py`), warn only (a missed warning is #122 again), ask the backend (keeps honouring what setuptools is removing; slow), a switch (more surface). |
| Q4 | Code names | `KF-METADATA-ENTRY-POINTS-OUTSIDE-PROJECT` (error, 2.3) and `KF-METADATA-NOT-GENERATED` (warning, 2.4), following `KF-<AREA>-<CONDITION>`. |
| Q5 | iOS Xcode-only rebuilds keep the metadata from the last `kivyforge build`; after a new commit, a dynamic version is stale. | Accepted and documented: the plist's version is generated at `kivyforge build` too, so the two stay stale together and agree; run `kivyforge build` (or `run`) before Cmd-R when the version matters. |
| Q6 | The #123 regression test asserts the `egg-info` ships. | Replaced by the removal test of layer 1. |
| Q7 | Untested here: iOS release archives, physical devices, Linux, Windows. | Layer 5, before the release that ships this. iOS archives and a device: I8. Windows: I9. Linux: I10. |
| Q8 | Acceptance by the #122 reporter. | Their project declares entry points only in `[project]` with a static version, so it takes the generated path; ask them to confirm their APK on the branch before release. |

## 11. Implementation notes, 2026-10-14

What the implementation settled that the plan above left open, and one fact
it found. None of it changes a decision in section 3.

| # | Note |
|---|---|
| I1 | The 2.1 checks live in the config loader (`_parse_entry_points`), not in `bundle/app_metadata.py`: the loader owns `[project]` and the line finder, so each rule is a config error at its line, in every verb that loads the config (`lock` and `doctor` too), not only in builds. |
| I2 | An entry point name or value containing a line break is also rejected: the spec allows it in a name, but `entry_points.txt` cannot hold it, so no backend could write it either. |
| I3 | `top_level.txt` lists only names that are Python identifiers (`not-a-module.py` is not importable), plus the top-level module of `[tool.kivy].entry_point`. |
| I4 | 2.3 and 2.4 are checked by `build`, `package` and `run` (`cli/_version.py` `check_app_metadata`) right after the version is resolved and before any backend runs. After, not before, because resolving a dynamic version runs the backend, which can write the development `egg-info` the 2.4 warning names. |
| I5 | The iOS script removes a stale `.dist-info` of the app's name by normalizing each folder's name as Python does, so `MyApp-0.9.dist-info` goes too. `_BUILD_PYTHON_SCRIPT_V1`, the script before this change, is kept as `PREVIOUS_BUILD_PYTHON_SCRIPTS`, so regenerating an existing project replaces its phase instead of adding a second (tested). |
| I6 | **Found by the metaprobe:** with `scripts` declared in `[project]` and only `entry-points` in `dynamic`, setuptools 84.0.0 builds without `setup.cfg`'s `[options.entry_points]` groups, and says nothing. kivyforge warns (2.4) and generates nothing, so the app gets exactly what setuptools wrote; `tests/bundle/test_app_metadata_live.py` pins it, and the layer 3 variant lists all three keys in `dynamic`. |
| I7 | The layer 3 driver shares this Mac's devices with other work: it prefers an already booted simulator, shuts down only what it booted, and uninstalls its probe app at the end. `METAPROBE_SIMULATOR` and `METAPROBE_AVD` choose the devices. |
| I8 | **On a physical iPhone** (layer 5, `--metaprobe ios-device`, hardware checklist `ios-device-app-metadata`, 2026-10-14): the metadata holds in every variant, a release archive exported for development included. An Xcode-only rebuild of a *device* build, though, leaves the `Frameworks/*.framework` extension binaries modified after signing, so `codesign --verify` fails. It happens with the metadata step switched off too: `install_python` rewrites those binaries on every build and Xcode does not sign them again. The simulator is unaffected. Fixed the same day: the Build Python phase now declares its bundle outputs, so Xcode signs the app again after it ([spec 05](../platforms/ios/05-xcode-project-generation.md), "The phase declares its outputs"). The xfail is gone, and every device variant passes ([test-matrix](test-matrix.md) section 7). |
| I9 | **On Windows** (layer 5, `--metaprobe windows`, 2026-10-17, Windows 11): the driver gained a `windows` target, which reads the report from `METAPROBE_OUT` because the launcher attaches to the parent console instead of writing to a captured pipe, and checks a dynamic version against the launcher's string `ProductVersion`. The first run found two Windows bugs, neither in the metadata step. (1) The shared desktop lock builder turned pip's `file:///C:/...` URL into a drive-relative path, so `pylock.windows.toml` recorded `Users/...` and every build failed to find the `find_links` wheels; it now uses `url2pathname`, as iOS and Android did. (2) The bootstrap added `app` to `sys.path` that the native launcher had already put on `PYTHONPATH`, so `distributions()` returned the app twice; it now moves the entry to the front instead. With both fixed, all six variants pass: dev-install, no and stale `egg-info`, release (`main.pyc`), dynamic version and dynamic entry points ([test-matrix](test-matrix.md) section 7). |
| I10 | **On Linux** (layer 5, `--metaprobe linux`, 2026-10-18, Ubuntu 26.04 under WSL2, x86_64): the driver gained a `linux` target, which reads the report from `run -p linux`'s stdout as macOS does (`AppRun` runs in the foreground with stdout inherited), and launches the built AppDir's `AppRun` for the `build --json` variants. A dynamic version is checked against `data.version` only: an AppDir records the version nowhere, and only the packaged `.AppImage`'s file name carries it. All six variants pass with no kivyforge change; Linux's `AppRun` puts `app` on `sys.path` once. The first run's three failures were the host's 3.9 GB tmpfs `/tmp` filling up (`ENOSPC`); with `TMPDIR` and `--basetemp` on disk, all pass. Bare-metal Linux, `aarch64` and `--metaprobe android-emu` from Linux are not run: the WSL emulator cannot start without `libpulse0` ([test-matrix](test-matrix.md) section 7). |
