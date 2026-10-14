# Prompt — implement the app package-metadata proposal

> Handoff, 2026-10-14. For an agent with no prior context. Read this whole file
> before touching code.

## Goal

Implement [`package-metadata-proposal.md`](package-metadata-proposal.md):
kivyforge writes each app's own `<name>-<version>.dist-info` (from `[project]`)
into the app's code directory in every bundle, removes development `egg-info`
from that copy, rejects entry points declared only in `setup.py`/`setup.cfg`,
and warns when entry points are dynamic. The proposal is **approved**: all
decisions are recorded in its section 3 and all questions answered in section
10. Do not reopen them; if the code contradicts an assumption, stop and report
it rather than redesigning.

Background: issue #122 (an app's plugins vanished when #115 excluded the
`egg-info` that held its entry points; #123 reverted that). The whole design
exists so that never happens silently again.

## Read first, in this order

1. `AGENTS.md` (repo root): the loop, output rules, diagnostic-code rules,
   cp1252-safe strings, no prompts, tests must not skip silently, CHANGELOG,
   ask before pushing.
2. [`package-metadata-proposal.md`](package-metadata-proposal.md): the spec
   you implement. Sections 2 (design), 3 (decisions), 5 (test plan), 10
   (answers).
3. [`package-metadata-spike-findings.md`](package-metadata-spike-findings.md):
   the evidence (F1-F7). F1, F5, F6 and F7 contain facts that are easy to get
   wrong.

## Where to work

- Worktree: `../kivyforge-meta` (path relative to the main checkout), branch
  `app-metadata-design`, which holds only the design docs on top of `main`
  `f52ce1e2`. Update it from `origin/main` first (merge, not rebase; nothing is
  pushed yet). Commit implementation there, or on a new branch from it.
- **Do not touch the main checkout** (`/Users/elliotgarbus/Developer/kivyforge`):
  it is on `android-lock-runtime-progress`, someone else's work.
- The dev venv is the main checkout's `.venv`; it has kivyforge installed
  editable from the main checkout, so run tests from the worktree with
  `PYTHONPATH=<worktree>` and confirm with `kivyforge.__file__` that the
  worktree's code is the one imported. Run pyright with
  `--pythonpath <main>/.venv/bin/python`.
- Push and open PRs only when the user says so.

## Order of work (proposal section 4)

0. **Guard today's behaviour first.** Build the layer 3 probe and driver
   (below) and run it against unchanged code: on `main`, a src-layout setuptools
   project with a development `egg-info` must find its metadata on all three
   runtimes. Commit that before changing behaviour. It is the baseline the
   change is measured against.
1. Write the layer 1 tests (and layer 2, opt-in). Confirm that the "no
   `egg-info`" cases fail on unchanged code, and the rest pass.
2. `kivyforge/bundle/app_metadata.py`: generator, validation (2.1), the
   2.3 error and the 2.4 warning; codes `KF-METADATA-ENTRY-POINTS-OUTSIDE-PROJECT`
   (config error, exit 1) and `KF-METADATA-NOT-GENERATED` (warning) in
   `report/diagnostics.py`, plus their entries in `docs/hooks/kf_generated.py`
   (`mkdocs build --strict` fails until every code is documented there).
3. Copy points (2.2): macOS/Linux/Windows `bundle._copy_app_sources`, Android
   `stage/bundle._copy_app`; iOS: stage into `<app>-ios/_kivyforge_meta/` at
   `kivyforge build` and extend `BUILD_PYTHON_SCRIPT` in
   `platforms/ios/buildsettings.py`.
4. Docs: `docs/guides/guides/cross-platform/versioning.md` ("Read your package
   metadata" section: rewrite for the new behaviour, plus Q5's note), the
   pyproject reference, CHANGELOG `[Unreleased]` with the three migration
   notes of proposal section 4.
5. Run layers 1-3 on this Mac; log the device runs as a dated row in
   `docs/design/dev/test-matrix.md` §7 (append to the end of the §7 table,
   not the end of the file).

## Facts that are easy to get wrong

- **Folder name:** `importlib.metadata` takes the distribution name from the
  text before the folder name's **first hyphen**. Normalize the name
  (`re.sub(r"[-_.]+", "_", name).lower()`) and use the normalized PEP 440
  version: `meta_probe_app-1.2.3.dist-info`. `metaprobe-app-1.2.3.dist-info` is
  not found (F5). `METADATA`'s `Name:` keeps the name as written.
- **Never let a development `egg-info` and the generated `.dist-info` share a
  directory.** CPython puts both in one list in `os.listdir` order; which wins
  depends on the filesystem and the names (F1). That is why the removal in 2.2
  is mandatory.
- **`entry_points()` collects entry points from every distribution found**, so
  remove every top-level `*.egg-info`, not just the app's (proposal 2.2, Q2).
- **Do not write `entry_points.txt` with a default `configparser`:** it
  lowercases names (`MyPlugin` became `myplugin`). Write the file by hand, UTF-8,
  with `=` delimiters.
- **`top_level.txt`, not `RECORD`** (Q1): top-level `*.py` modules and
  directories with an `__init__.py`, from the source before byte-compiling;
  include `main`.
- **iOS debug builds link `<app>-ios/app` to `app_dir`.** Never write into or
  delete from `app_dir`. The bundle's `app/` is Xcode's copy (Copy Bundle
  Resources), made before the Build Python script runs and signed after it
  (F6). The script must refuse to run if `$CODESIGNING_FOLDER_PATH/app` is a
  link. The F6 spike appended, in effect:

  ```sh
  APPDIR="$CODESIGNING_FOLDER_PATH/app"
  if [ -L "$APPDIR" ]; then echo "error: bundle app/ is a symlink"; exit 1; fi
  find "$APPDIR" -maxdepth 1 -name "*.egg-info" -exec rm -rf {} +
  if [ -d "$PROJECT_DIR/_kivyforge_meta" ]; then rsync -a "$PROJECT_DIR/_kivyforge_meta/" "$APPDIR/"; fi
  ```

  The real version must also remove a `.dist-info` of the app's own name, and
  `generator.py` removes and re-adds the run script by exact text match
  (`remove_run_script(BUILD_PYTHON_SCRIPT)`), so changing the script must still
  replace the old phase in existing projects. Test that.
- **2.3 detection:** setuptools backend means `build-backend` is
  `setuptools.build_meta` or `setuptools.build_meta:__legacy__`, or there is no
  `[build-system]`. An empty `[project.entry-points]` table does **not** count as
  declaring entry points (F7). A hatchling project with a stray `setup.py` is
  not affected.
- **The existing regression test** `tests/bundle/test_app_metadata.py` (from
  #123) asserts the `egg-info` ships. It is replaced by the layer 1 removal test
  (Q6); do not just delete it.
- **Android copies the app payload once**, not per ABI (`assemble_bundle`
  calls `_copy_app` once after the dependency identity check), so the metadata
  needs no per-ABI handling.
- **`.gitignore` ignores `app-*`** anywhere: don't name new files `app-...`.

## Layer 3: the probe and driver (proposal 5, layer 3)

The spike's scripts lived in a session scratchpad and are gone; rebuild them as
the real fixture and driver.

- **Fixture** `tests/fixtures/apps/metaprobe/`: one project with
  `[tool.kivy.macos]` (from `examples/desktop/dice-roller`),
  `[tool.kivy.ios]` (from `examples/mobile/hello-kivy`, pinned deps) and
  `[tool.kivy.android]` (from `examples/mobile/hello-android`) overlays;
  entry points of its own in `[project]` (a group, `scripts`, `gui-scripts`);
  two local wheels under `wheels/` via `find_links = ["wheels"]` in each overlay
  (build them in a fixture step with `pip wheel`, setuptools backend, each
  declaring an entry point in group `metaprobe.plugins`). Do not commit
  generated locks.
- **`src/main.py`** reports, as JSON, `sys.path`, where
  `importlib.metadata.distribution()` finds each probe name, all
  `entry_points(group="metaprobe.plugins")` with the providing distribution,
  `packages_distributions()` for the app's modules, and the result of loading a
  dependency's entry point. It prints one line `METAPROBE {json}` **and** one
  short line per key (`METAPROBE.<key> <json>`), because logcat truncates long
  lines at about 1,000 characters, and writes the full line to
  `metaprobe.json` in `$ANDROID_PRIVATE`, else `~`, else the temp dir. Then it
  exits.
- **Collecting the report:**
  - macOS: `kivyforge run -p macos [--release]`; the app's stdout is `run`'s
    stdout.
  - iOS simulator: `kivyforge build -p ios --simulator`, then
    `xcrun simctl boot`/`bootstatus -b`, `uninstall`, `install`,
    `launch --terminate-running-process`, and read `metaprobe.json` from
    `xcrun simctl get_app_container <udid> <bundle-id> data`. macOS has no
    `timeout` command: poll for the file, then terminate.
  - iOS Xcode-only rebuilds (the F6 steps): capture the exact `xcodebuild` argv
    kivyforge runs (wrap `kivyforge.platforms.ios.xcode.runner.run_command`,
    importing `kivyforge.cli` **first**, or the backend import is circular),
    then re-run that argv alone after a no-op, after editing `src/main.py`, and
    after rewriting the development `egg-info`; check `codesign --verify
    --deep --strict` each time.
  - Android: `kivyforge run -p android --emulator --avd kf_api35_arm64 --abi
    arm64_v8a --no-follow [--release]` with `ANDROID_HOME=~/Library/Android/sdk`;
    for debug read `adb shell run-as <package> cat files/metaprobe.json`; for
    release (not debuggable) reassemble the per-key `METAPROBE.` lines from
    `run`'s output.
- **The driver must refuse to collect a report when the build failed** and
  must reinstall cleanly: in the spike, a failed build left the previous app
  installed and it answered with stale results.
- Shut the simulator and emulator down when finished.

Machine resources: macOS 26.6.2, Xcode 27.0, AVD `kf_api35_arm64` (API 35,
arm64-v8a), simulator iPhone 17 Pro `0B7524AA-8D44-4FDD-AA08-4BE045C1374E`, uv
0.13.0. Runtimes seen: macOS bundle CPython 3.13.14, iOS 3.15.0b4, Android
3.14.6.

## Done when (proposal section 8)

Layers 1-4 pass; layer 3's "no `egg-info`" variant (which fails on unchanged
code) passes; the full gate is green (`pytest` with coverage, `ruff check`,
`ruff format --check`, `pyright`, `mkdocs build --strict`). Then report to the
user, ask before pushing, and note what remains for layer 5 (Linux, Windows,
iOS release, devices, the #122 reporter's confirmation).
