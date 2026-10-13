# Findings — dynamic-version spike (app level)

> 2026-10-12, macOS host. A throwaway spike for
> [`dynamic-version-proposal.md`](dynamic-version-proposal.md): does resolving a
> dynamic `[project].version` through pip work end to end in real builds?
> Branch `spike/dynamic-version` (`754a9f62`, never to be merged): `main` at
> `70573b79` plus #115 (exclude `*.egg-info` from app copies) plus a ~50-line
> hack in `load_config_from_text`. When `version` is in `dynamic`, the hack
> runs `pip install --dry-run --ignore-installed --no-deps --quiet --report -`
> on the project and writes the result into `raw["project"]["version"]`. It
> resolves at **config load, in every verb**, which the design deliberately
> does not; the consequence is finding 4.

## Environment

| Item | Value |
|---|---|
| Host | macOS 26.6.2 (25G83), arm64 |
| Xcode | 27.0 (27A266a) |
| JDK | OpenJDK 17.0.20.1 |
| kivyforge's interpreter | Python 3.14.7, pip 26.2.1, in a **fresh venv holding only kivyforge** (`pip install -e` of the spike worktree): no setuptools, no setuptools-scm. This stands in for `uv tool install` / pipx, neither of which is installed on this host. |
| Backend (fetched by pip into its isolated build env) | setuptools 84.0.0, setuptools-scm 10.3.4 |

## Projects

Copies of three examples, each converted the same way:

- `[project].version` replaced by `dynamic = ["version"]`;
- `[build-system] requires = ["setuptools>=64", "setuptools-scm>=8"]`;
- `[tool.setuptools_scm] version_file = "src/_version.py"` (inside `app_dir`);
- `[tool.setuptools] py-modules = [] / packages = []` (see finding 6 for
  what happens without it);
- `git init`, tag `v1.2.3`, then one more commit.

| Copy of | Target | Extra |
|---|---|---|
| `examples/desktop/dice-roller` | macOS `.app` | `main.py` imports `__version__` from `_version` |
| `examples/mobile/hello-android` | Android debug APK, `x86_64` | `version_code = "auto"`; `main.py` imports `_version` |
| `examples/mobile/hello-kivy` | iOS simulator `.app` | — |

## Findings (defects and design-relevant facts first)

### 1. A raw dev version reaches both Apple plists, and nothing local objects

macOS `Info.plist` after `kivyforge build -p macos`:

```
$ PlistBuddy -c "Print :CFBundleShortVersionString" -c "Print :CFBundleVersion" Info.plist
1.2.4.dev1+g629b36fab
1
```

iOS simulator `Info.plist` after `kivyforge build -p ios --simulator`:

```
1.2.4.dev1+g9dc76abf8
1
```

`plutil -lint` says `OK`; `xcodebuild` printed nothing about the version
(`grep -ci CFBundleShortVersionString` on its log: `0`); the macOS app launched
and ran (finding 7). So the proposal's fact 3 is real and **silent until upload**:
the only thing that would reject this string is App Store Connect, which this
host cannot test (it needs a signing account; `hardware-checklist.toml`). This
is why the proposal checks the version before an App Store export
(`KF-VERSION-APPLE-FORMAT`, an error for an iOS `app-store` export): without a
check, a dynamic-version project produces an `.app` that works locally and is
refused at submission. (The spike was first read as an argument for rewriting
the value to `MAJOR.MINOR.PATCH`; that was dropped as overreach, see the
proposal's section 3.6.)

### 2. The egg-info lands in `app_dir` by default; #115 is what keeps it out

Where setuptools writes `<name>.egg-info` during the isolated metadata step
depends on the project's setuptools configuration:

| Project's `[tool.setuptools]` | Written to | Inside `app_dir = "src"`? |
|---|---|---|
| none (auto-discovery) | `src/dice_roller.egg-info/` | **yes** |
| `py-modules = []`, `packages = []` | `dice_roller.egg-info/` (project root) | no |

A converted app with no setuptools table, the likely default, therefore gets
the folder inside the tree every backend copies. With #115 merged into the
spike, no `.egg-info` appeared in the macOS `.app` or the Android APK. This
makes #115 a hard prerequisite, as the proposal now says, and refines its
side-effects table ("package root") to "where setuptools' discovery puts
it, usually `src/` for an app".

### 3. The iOS debug gap is real

With a folder planted at `src/planted.egg-info`, the iOS **simulator (debug)**
build shipped it:

```
debug .app: app/planted.egg-info
$ ls -la hello-kivy-ios/
lrwxr-xr-x  app -> ../src
```

The debug staging is a symlink to `app_dir` that Xcode copies as-is, so #115's
ignore list cannot reach it. Expected and documented in #115 and the proposal;
now observed. Combined with finding 2, a dynamic-version project with no
setuptools table **will** ship `src/<name>.egg-info` in every iOS debug build.
`app_dir` is on the app's import path, so `importlib.metadata` can find it and
report whatever version it holds, which is the problem #115 exists to prevent.
Debug builds only, but it is the one artifact the exclusion does not cover. Release
(`package`) builds copy and are covered.

### 4. Resolving at config load breaks `lock`, as the design predicted

With `version_code = "auto"` one commit past the tag, the hack (which resolves
at load) made **`lock`** fail:

```
$ kivyforge lock -p android
SPIKE: config load #1: resolved 1.2.4.dev1+g73df33c6f via pip in 1.08s
Error: version_code = "auto" requires a final MAJOR.MINOR.PATCH [project].version; '1.2.4.dev1+g73df33c6f' is not one (line 24)
  hint: pre-release/dev/post/local/epoch versions have no monotonic integer mapping; set an explicit integer version_code for those.
```

The message and the `line 24` are today's, which is what the proposal wants at
**build** time. At **lock** time it is wrong: the lock does not depend on the
version. This is the concrete case behind the proposal's
`AutoVersionCode` deferral for dynamic versions (section 3.1), and the reason
the implementation must not take the spike's shortcut.

### 5. Resolution cost, against real builds

Every resolution, isolated, warm pip cache:

| Invocation | Resolution | Whole command |
|---|---|---|
| `lock -p macos` | 1.09 s | 8.4 s |
| `build -p macos` (Python and wheels cached) | 1.10 s | 3.6 s |
| `lock -p android` | 1.09 s | — |
| `build -p android --debug --abi x86_64` | 1.09 s | 48.3 s |
| `lock -p ios` | 1.18 s | — |
| `build -p ios` (generate only) | 1.09 s | 7.4 s |
| `build -p ios --simulator` | 1.09 s | 18.7 s |

Steady at about 1.1 s. Negligible for Android and iOS; about **30 % of a warm
macOS build**, the case most like a `run` loop. Acceptable for a correct
version, and `--app-version` or `--no-build-isolation` (0.4 s, measured in the
proposal) are the documented ways out. Not measured: a cold pip cache.

### 6. No setuptools table is needed to resolve

Removing `[tool.setuptools] py-modules = [] / packages = []` from the macOS
copy, pip still resolved (`1.2.4.dev2+g8636a0a3f`, exit 0): setuptools'
src-layout auto-discovery accepts a lone `src/main.py`. The user-facing docs
need not tell people to add the table; finding 2 says what it changes.

## What worked (end to end)

### 7. macOS

- `lock` and `build` from the kivyforge-only venv: pip fetched setuptools and
  setuptools-scm into its isolated environment, so the install mode that broke
  the first design works.
- The bundle ships `Contents/Resources/app/_version.py`, and the bundle's own
  interpreter reads it:

  ```
  $ cd "Dice Roller.app/Contents/Resources/app" && ../python/bin/python3.13 -I -c "import sys; sys.path.insert(0, '.'); import _version; print('app reads:', _version.__version__)"
  app reads: 1.2.4.dev1+g629b36fab
  ```

- The app itself (`Contents/MacOS/dice-roller`, run directly, not through
  `open`/LaunchServices) started, logged `[Kivy] v2.3.1`, and was still running
  after 8 s with `main.py` importing `_version` at the top.

### 8. Android

Checked out at the tag (`v1.2.3`), `version_code = "auto"`:

```
$ aapt2 dump badging app-debug.apk
package: name='org.kivyforge.helloandroid' versionCode='1020300' versionName='1.2.3' ...
```

`1020300` = 1·1,000,000 + 2·10,000 + 3·100 + build 0: the existing `"auto"`
rule, fed by the resolved version. The APK carries
`assets/_python_bundle/app/_version.py` and no `.egg-info`.

### 9. iOS

`build -p ios` and `build -p ios --simulator` succeeded; the plist carries the
resolved version (finding 1) and the `.app` carries `app/_version.py`.

### 10. One config load per build

The hack logged each config load that saw a dynamic version. Every `lock` and
`build` above logged exactly one (`config load #1`), so today each of these
commands loads config once, inside the backend. Resolving once per invocation
costs nothing extra, and the proposal's "resolve in the verb, pass
`ResolvedVersion` in" adds one load in the verb, not a second resolution.

### 11. The checkout comes out dirty, as documented

`git status --short --ignored` after the macOS run: `?? dice_roller.egg-info/`
(untracked, not ignored by the example's `.gitignore`), plus the ignored
`src/_version.py` and lock. As the proposal's section 3.9 says, a build of a
dynamic-version project can leave a clean checkout dirty.

## Real uv install modes (second run, same day)

The spike commit restored into a worktree, uv 0.13.0 installed, and the macOS
copy of `dice-roller` built two more ways. Both pass.

### 12. `uv tool install` works

```
$ uv tool install --editable <spike worktree>
Installed 2 executables: kf, kivyforge
```

The tool environment (`~/.local/share/uv/tools/kivyforge`) has pip 26.2.1,
pulled in by kivyforge's own `pip>=25.1` dependency, and neither setuptools nor
setuptools-scm. From a clean clone of the converted project:

```
$ kivyforge lock -p macos
SPIKE: config load #1: resolved 1.2.4.dev1+g629b36fab via pip in 3.07s
$ kivyforge build -p macos
SPIKE: config load #1: resolved 1.2.4.dev1+g629b36fab via pip in 1.47s
Built build/macos/Dice Roller.app
```

The plist and the app's own interpreter both give `1.2.4.dev1+g629b36fab`; no
`.egg-info` in the bundle. This is the install mode that broke the first
design, now exercised for real rather than through a stand-in venv.

### 13. `uv run kf` resolves the tree, not uv's stale install

A clone made into a uv project with `uv add --dev --editable <spike
worktree>`, then committed (tree at `v1.2.3-2-g0274a04`). uv had installed the
app itself, editable, into `.venv` **before** that commit, as
`1.2.4.dev1+g629b36fab.d20261013`, and did not reinstall it afterwards:

```
$ uv run -v python -c pass
DEBUG Requirement already installed: dice-roller==1.2.4.dev1+g629b36fab.d20261013
```

kivyforge, running inside that environment, still resolved the tree:

```
$ uv run kf build -p macos
SPIKE: config load #1: resolved 1.2.4.dev2+g0274a042e via pip in 1.43s
Built build/macos/Dice Roller.app
```

Plist and `_version.py` in the bundle: `1.2.4.dev2+g0274a042e`; no
`.egg-info` in the bundle. This is the proposal's `--ignore-installed` case
under the reporter's real setup, with a genuinely stale installed copy.

### 14. The build's egg-info shadows the dev environment's metadata

After the build, `importlib.metadata` in the project's own `.venv`, run from
the project root, reports the **build's** version, not the installed one:

| Version | Found at |
|---|---|
| `1.2.4.dev2+g0274a042e` | `dice_roller.egg-info` (project root, written by kivyforge's pip run) |
| `1.2.4.dev1+g629b36fab.d20261013` | `.venv/.../dice_roller-1.2.4.dev1+g629b36fab.d20261013.dist-info` (uv's install) |

The project root is on `sys.path` (as the current directory) whenever Python
runs from it, which covers `uv run python`, `uv run pytest` and most dev
commands, and the egg-info comes first. So after a kivyforge build,
`importlib.metadata.version("dice-roller")` in the developer's environment
returns whatever the last build resolved. In this run that was the *more*
accurate value, but it no longer comes from the install. It is the same thing
any `pip install .` or `python -m build` of a setuptools project does, which is
why many projects already gitignore `*.egg-info`; it is new only in that
kivyforge now triggers it. A side effect to document, not a defect in the
design.

### 15. Timing under uv

Resolution took 1.43–1.50 s inside uv-managed environments (3.07 s on the very
first `lock` from the new tool environment), against 1.08–1.18 s from the plain
venv. A full warm `build -p macos` took 3.7–3.8 s either way.

## Not covered

- App Store Connect accepting or refusing the plist value (finding 1): needs a
  signing account.
- Launching through LaunchServices (`open`), a device, or an emulator.
- pipx (uv tool install and `uv run` are covered by findings 12-13).
- Windows and Linux hosts; a cold pip cache; a project with no git history.

## Consequences for the proposal

- Finding 1 confirms an Apple version check is needed, and that only an
  early failure for App Store exports catches it before upload.
- Findings 2 and 3 refine section 3.9's side-effects table: the egg-info goes
  where setuptools' discovery puts it, which for a converted app with no
  setuptools table is `app_dir`; #115 covers every copy except iOS debug.
- Finding 4 is the concrete case for deferring `"auto"` on dynamic versions.
- Finding 5 gives section 3.3 real numbers to cite.
- Findings 12-13 confirm the design in the two install modes the issue is
  about; finding 14 adds a side effect to section 3.9's table.
- Nothing found argues against the design.
