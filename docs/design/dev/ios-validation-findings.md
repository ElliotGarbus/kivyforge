# iOS marker-fix validation findings (macOS)

Validation run against `modernization-rfc` per
[`ios-validation-prompt.md`](ios-validation-prompt.md).
Date: 2026-07-25.

## Environment (Step 0)

| Item | Value |
|------|-------|
| macOS | 26.5.2 (Build 25F84) |
| Host Python | 3.14.5 |
| kivyforge | 3.0.0.dev0 (editable install) |
| pip | **26.1.2** (satisfies iOS ≥ 24.3 / Android ≥ 25.1) |
| Xcode | 26.6 (Build 17F113) |
| Swift | Apple Swift 6.3.3 (swiftlang-6.3.3.1.3) |
| Branch | `modernization-rfc` (up to date with origin) |

## Step 1 — test suite and lint

```
1755 passed, 43 skipped in ~6s
ruff: All checks passed!
```

All 43 skips are Windows-host-only tests under `tests/platforms/windows/`
(`test_cli.py`, `test_launcher_exe.py`). No macOS-only failures.

Note: the prompt's Windows baseline (1790 passed / 8 skipped) no longer matches
this tree's suite size; the macOS run is green.

## Step 2 — marker retargeting (decisive)

Probe command (shim + dry-run resolve of `requests`) wrote
`/tmp/kf-probe.json`. pip's installation report environment:

```
sys_platform    = ios
platform_system = iOS
platform_machine= arm64
implementation_name=cpython
implementation_version=3.15.0
os_name=posix
platform_python_implementation=CPython
platform_release=
platform_version=
python_full_version=3.15.0
python_version=3.15
```

**PASS:** the `default_environment` patch takes effect on pip 26.1.2.
`kivyforge/platforms/ios/lock/markers.py` values match the real resolve —
no marker-value corrections needed.

Guardrail (env unset):

```
KIVYFORGE_TARGET_MARKER_ENV is not set; refusing to resolve with the host's marker environment.
exit=2
```

**PASS:** refuses rather than falling back to host markers.

## Step 3 — host gate on macOS

```
kivyforge doctor -p ios  → exit 0
```

All capability checks **PASS**, including Xcode, pip, simulator runtimes
(17.2, 26.5), signing (automatic), find_links (`../../wheels/ios`, 6 wheels),
and network hosts. One **WARN** (pre-existing, unrelated to this change):

```
[WARN] xcframework privacy manifests: no PrivacyInfo in:
       KivyThorVG, SDL3, SDL3_image, SDL3_mixer, SDL3_ttf, libEGL, libGLESv2
```

`[SKIP] Swift package toolchain: no swift_packages declared` — expected for
hello-kivy. No "requires macOS with Xcode" false rejection.

## Step 4 — re-lock `examples/mobile/hello-kivy`

`kivyforge lock -p ios --update` succeeded (3 packages pinned).

Diff vs committed pre-fix lock (`/tmp/pylock.ios.before.toml` =
`HEAD:examples/mobile/hello-kivy/pylock.ios.toml`):

### Only two substantive changes

1. **Kivy `dependencies` list shrinks** (the point of the change).
2. **`generated_at`** updates.

`pyproject_sha256`, wheel filenames, URLs, versions, and sha256 hashes are
unchanged. `[[packages]]` set is identical:
`filetype`, `kivy`, `more-itertools`.

### Before — Kivy `dependencies` (36 entries)

```
[{ name = "Kivy-Garden" }, { name = "docutils" }, { name = "pygments" },
 { name = "requests" }, { name = "filetype" }, { name = "kivy_deps.angle" },
 { name = "kivy_deps.sdl3" }, { name = "kivy_deps.glew" },
 { name = "pypiwin32" }, { name = "oscpy" }, { name = "pytest" },
 { name = "pytest-cov" }, { name = "pytest_asyncio" },
 { name = "pytest-timeout" }, { name = "pytest-benchmark" },
 { name = "pytest-httpserver" }, { name = "trustme" },
 { name = "pyinstaller" }, { name = "sphinx" },
 { name = "sphinxcontrib-jquery" }, { name = "kivy_deps.gstreamer_dev" },
 { name = "kivy_deps.sdl3_dev" }, { name = "kivy_deps.glew_dev" },
 { name = "pre-commit" }, { name = "responses" }, { name = "ruff" },
 { name = "tomli" }, { name = "pillow" }, { name = "kivy_deps.gstreamer" },
 { name = "ffpyplayer" }, { name = "pillow" }, { name = "kivy_deps.gstreamer" },
 { name = "ffpyplayer" }, { name = "kivy_deps.gstreamer" },
 { name = "kivy_deps.angle" }, { name = "kivy_deps.glew" }]
```

These are raw `Requires-Dist` names evaluated against **macOS** host markers
(plus extras), so Windows-only (`kivy_deps.angle`, `pypiwin32`, …),
dev/extra (`pytest`, `sphinx`, `ruff`, …), and darwin-gated edges all leaked
into the recorded list even though none were installed as packages.

### After — Kivy `dependencies` (5 entries)

```
[{ name = "Kivy-Garden" }, { name = "docutils" }, { name = "pygments" },
 { name = "requests" }, { name = "filetype" }]
```

Edges whose markers do not hold on iOS (with `extra` empty) are gone.
**No `[[packages]]` entry appeared or disappeared.**

### Why Garden / docutils / pygments / requests still appear

This list is **not** "what the app installs on iOS." It is the marker-filtered
read of Kivy's own wheel `Requires-Dist`. Those five names are declared
**unconditionally** in the vendored iOS Kivy wheel — no `sys_platform` /
`extra` gate:

```
Requires-Dist: Kivy-Garden>=0.1.4
Requires-Dist: docutils
Requires-Dist: pygments
Requires-Dist: requests
Requires-Dist: filetype
```

So for any target environment (including iOS) the edge recorder keeps them.
That matches Kivy's packaging metadata, not an ideal mobile dependency set.
Garden is a desktop extension registry; `docutils` / `pygments` / `requests`
are only needed for specific widgets / `UrlRequest`. Upstream has not marked
them platform- or feature-conditional.

**What actually gets pinned** is the post-`exclude` install set. hello-kivy's
`[tool.kivy.ios].exclude` already drops `kivy-garden`, `docutils`, `pygments`,
`requests` (+ requests' transitive deps). The locked `[[packages]]` are only:

`filetype`, `Kivy`, `more-itertools`

(`filetype` stays because Kivy imports it unconditionally.) `exclude` prunes
`[[packages]]` rows; it does **not** rewrite the parent package's recorded
`dependencies = [...]` edges. Seeing Garden/docutils on that line while they
are absent from `[[packages]]` is therefore expected with today's design.

## Step 5 — SPM path (`examples/mobile/keychain-spm`)

`kivyforge lock -p ios --update` succeeded. Swift pins in the lock:

| Package | Source | Pin |
|---------|--------|-----|
| KeychainAccess | `https://github.com/kishikawakatsumi/KeychainAccess` | revision `84e546727d66f1adc5439debad16270d0fdd04e7`, version `4.2.2` (`from: 4.2.2`) |
| KeychainBridge | path `swift-shims` | local (link+embed) |

This confirms why `lock -p ios` is gated to macOS: resolution shells out to
`swift package resolve`. Working tree for this example was already in sync
with HEAD after the re-lock (no additional diff).

## Step 6 — build and run (simulator)

```
kivyforge build -p ios --simulator  → exit 0
kivyforge run   -p ios --simulator  → launched org.kivy.hello-kivy
```

Simulator: iPhone Air, iOS 26.5
(`565869C5-3F8B-4A8E-B26A-6851AF9FACA8`).

Screenshot (`xcrun simctl io booted screenshot /tmp/ios.png`): black screen
with centered white **"Hello Kivy"** — app rendered correctly.
(`run` stays attached after launch; process was stopped after the screenshot.)

## Step 7 — Android third-host check

**SKIPPED:** `examples/wheels/android/*.whl` absent (binaries not committed;
see `examples/wheels/android/README.md`). No macOS Android re-lock attempted.

## Conclusions

1. The iOS `default_environment` shim **works on a real macOS pip 26.1.2
   resolve** — report `environment.sys_platform == "ios"`.
2. Guardrail fails loudly when the env var is missing.
3. Re-locking filters recorded dependency edges as designed; install set
   unchanged.
4. Host gate allows iOS verbs on macOS; SPM lock path works; simulator
   build/run still works after the gate wiring.
5. `markers.py` values need no correction from this run.
6. Android macOS host-independence remains unverified here (no vendored
   wheels); Windows↔Linux comparison from the Android work still stands.
