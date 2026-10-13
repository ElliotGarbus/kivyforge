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
is the strongest argument for the proposal's Apple reduction rule
(`release[:3]` plus `KF-VERSION-REDUCED`): without it, a dynamic-version
project produces an `.app` that works locally and is refused at submission.

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

## Not covered

- App Store Connect accepting or refusing the plist value (finding 1): needs a
  signing account.
- Launching through LaunchServices (`open`), a device, or an emulator.
- Real `uv tool install` and pipx (stood in for by a kivyforge-only venv).
- Windows and Linux hosts; a cold pip cache; a project with no git history.

## Consequences for the proposal

- Finding 1 confirms the Apple reduction rule is needed, not just tidy.
- Findings 2 and 3 refine section 3.9's side-effects table: the egg-info goes
  where setuptools' discovery puts it, which for a converted app with no
  setuptools table is `app_dir`; #115 covers every copy except iOS debug.
- Finding 4 is the concrete case for deferring `"auto"` on dynamic versions.
- Finding 5 gives section 3.3 real numbers to cite.
- Nothing found argues against the design.
