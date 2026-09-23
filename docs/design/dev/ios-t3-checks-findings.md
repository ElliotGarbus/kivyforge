# iOS T3 artifact checks — findings

Run against `ios-t3-artifact-checks` (branched from `main` @ `53a4bbd0`) per
[`ios-t3-checks-prompt.md`](ios-t3-checks-prompt.md). Date: 2026-09-23.

**All six steps done.** `ios_app_problems`/`ios_expected_plist` landed in
`tests/artifact_checks.py`, 20 hermetic tests in `tests/test_artifact_checks.py`,
`--ios-app`/`--ios-arch`/`--ios-project` in `conftest.py`,
`tests/platforms/ios/test_app_artifact.py` mirroring the macOS driver, wired
into `ios_simulator` as a new step between the T2 build and the T4 launch, and
validated (including negatives) against a real `hello-kivy` build. Full suite
green, `ruff`/`pyright` clean, docs updated
(`test-matrix.md` §5.1/§3.1/§3.2/§7, roadmap item 5).

## No defects found

Unlike several of this project's other findings docs, this run found no bug in
kivyforge itself — no shipped launcher defect, no false positive, no escaping
exception. The two things worth recording up front are a scope decision and a
genuine (and correct) exclusion the arch sweep takes:

1. **The scope constraint from the prompt is still current.** `kivyforge
   doctor -p ios` on `hello-kivy` still prints `no final CPython 3.15 found
   (this project ships 3.15.0b4)`. python.org has not published a final-release
   iOS `Python.xcframework`. iOS `strip_source`/`.pyc`-magic checks remain
   unwritten, and `ios_app_problems` takes no `stripped` parameter — see
   "What this harness does not cover" below.

2. **8 of the app's 121 `Frameworks/*.framework` binaries are universal (fat),
   and the arch sweep correctly skips them rather than missing a bug.**
   `SDL3.framework`, `SDL3_image.framework`, `SDL3_mixer.framework`,
   `SDL3_ttf.framework`, `KivyThorVG.framework`, `libEGL.framework`,
   `libGLESv2.framework`, and — notably — `Python.framework` itself all ship
   as `lipo`-confirmed `x86_64 arm64` fat binaries (their xcframework's single
   iphonesimulator-platform slice already covers both simulator archs). The
   remaining 113 — one per Kivy/CPython compiled extension module, staged by
   *this* build via `install_python` — are thin, single-arch Mach-O matching
   whatever `ARCHS` was passed to `xcodebuild`. `read_macho_cpu_type` raises
   `MachoError` on a fat header (documented scope, inherited from macOS's
   reader) and `_ios_arch_problems` skips anything it can't parse, so these 8
   are silently not checked — which is correct, not a gap: a universal binary
   cannot be "the wrong arch" the way a thin one can, since it already
   contains every arch it will ever need. The binaries a cross-arch leak could
   actually happen to — the ones *this* build compiles — are exactly the ones
   the sweep does check.

## What this harness does not cover, and why

- **`strip_source`/`.pyc`-magic.** Cannot be exercised honestly: see the scope
  constraint above, unchanged since 2026-09-14. `ios_app_problems` has no
  `stripped` parameter at all — the prompt's instruction was "do not write a
  `stripped=True` path you cannot exercise; either omit it, or add it with an
  explicit note and leave it unused by the driver," and omitting it entirely
  seemed more honest than carrying a parameter no driver will ever set `True`.
- **A stray-`.so`/hoisting-integrity check** (Android's `_native_lib_problems`
  has a close analogue: no shared object left stranded in the payload). Not
  written — it wasn't in the prompt's four-item scope list, and every `.so` in
  the real bundle was already correctly hoisted by `install_python`, so there
  was no observed failure mode to design a check around. Worth a future pass
  if a hoisting regression is ever suspected.
- **The device build path** (`--device`, `--release`/`--export-method`).
  Everything here was validated only against a `--simulator` build. The
  bundle layout should be identical (Info.plist/executable/Frameworks/app/
  pip-deps/python — none of that is simulator-specific), but this was not
  confirmed against a real device or release archive in this session.

## Environment (Step 0)

| Item | Value |
|---|---|
| Host | macOS 26.6.2 (BuildVersion 25G83), Apple Silicon |
| Xcode | 26.6 (Build 17F113) |
| Swift | 6.3.3 (swiftlang-6.3.3.1.3, clang-2100.1.1.101) |
| Host Python (pytest) | 3.14.7 |
| kivyforge | 3.0.0.dev0 (editable install, `.venv`) |
| Branch | `ios-t3-artifact-checks`, off `main` @ `53a4bbd0` |
| Example | `examples/mobile/hello-kivy` (committed `pylock.ios.toml`, untouched) |
| Target | `--simulator`, `arm64` (default on this Apple Silicon host) |
| Simulator runtime | iOS 26.5 (per `kivyforge doctor -p ios`) |
| iOS project's CPython | `3.15.0b4` (every iOS example pins this — pre-release) |

### Step 0 — `doctor`, `build`, and the real bundle layout

```
$ cd examples/mobile/hello-kivy
$ kivyforge doctor -p ios
kivyforge doctor (ios, project mode)

[PASS] Xcode version: 26.6
[PASS] Command-line tools: /Applications/Xcode.app/Contents/Developer
[PASS] pip version: 26.2.1
[PASS] Simulator runtimes: 26.5
[PASS] kivyforge version: 3.0.0.dev0
[PASS] App source directory: src
[WARN] Byte-compile interpreter: byte_compile = "release", but no final CPython 3.15 found (this project ships 3.15.0b4); release builds will silently ship source
       hint: Pre-releases do not count: CPython only freezes the .pyc magic number at the first release candidate, so a 3.15 alpha writes bytecode 3.15.0b4 refuses to import.
       Fix: install a final CPython 3.15 — kivyforge finds it automatically — or set byte_compile = false in [tool.kivy.ios.python.build_settings].
[PASS] Signing identity: automatic signing
[PASS] Provisioning profile: not set
[SKIP] Entitlements vs. profile: no entitlements declared
[PASS] App icon: 1024x1024 PNG
[SKIP] Swift package toolchain: no swift_packages declared
[SKIP] find_links directories: not configured
[PASS] Required hosts reachable: files.pythonhosted.org, github.com, www.python.org
[PASS] App-local native binaries: none non-iOS
[WARN] App-level privacy manifest: PrivacyInfo.xcprivacy absent
       hint: `kivyforge build` generates a minimal stub; if you use required-reason APIs, set [tool.kivy.ios.privacy_manifest].source.
[SKIP] xcframework privacy manifests: project not built

$ kivyforge build -p ios --simulator
Collecting artifacts for ios_16_0_arm64_iphonesimulator ...
Generated hello-kivy-ios
xcodebuild build (simulator) ...
Built hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/hello-kivy.app
kivyforge build -p ios --simulator  1.95s user 3.03s system 25% cpu 19.816 total
```

Both `WARN`s are the two documented, iOS-simulator-specific expectations (the
same two `test-matrix.md`'s `ios_simulator` row has always cited) — exit 0,
gating without a waiver.

**Bundle structure (`find <app> -maxdepth 2`), annotated:**

```
hello-kivy.app/
├── Info.plist                       # bundle root, NOT Contents/Info.plist
├── PkgInfo
├── PrivacyInfo.xcprivacy
├── Assets.car
├── AppIcon60x60@2x.png
├── AppIcon76x76@2x~ipad.png
├── _CodeSignature/CodeResources
├── hello-kivy                        # the executable itself, at bundle root (Mach-O 64-bit arm64)
├── app/                              # the developer's own payload (macOS's Contents/Resources/app)
│   ├── icon.png
│   └── main.py                       # source only — byte_compile degraded per the WARN above
├── pip-deps/                         # third-party wheels (macOS's Contents/Resources/lib)
│   ├── kivy/                         #   .py source + *.fwork stubs (see below), no .so left in place
│   ├── kivy-3.0.0.dev202607301604.dist-info/
│   ├── filetype/, filetype-1.2.0.dist-info/
│   └── more_itertools/, more_itertools-11.1.0.dist-info/
├── python/lib/python3.15/            # the embedded runtime's OWN stdlib (macOS's Contents/Resources/python)
│   └── ... 1037+ .py, lib-dynload/*.fwork stubs ...
└── Frameworks/                       # every dynamic library AND every compiled extension module
    ├── Python.framework/Python           # fat (x86_64 arm64) — the runtime itself
    ├── SDL3.framework/, SDL3_image.framework/, SDL3_mixer.framework/, SDL3_ttf.framework/   # fat
    ├── KivyThorVG.framework/, libEGL.framework/, libGLESv2.framework/                        # fat
    ├── _ssl.framework/_ssl               # thin (arm64 only) — hoisted from python/lib/.../lib-dynload
    ├── kivy._clock.framework/kivy._clock # thin (arm64 only) — hoisted from pip-deps/kivy
    └── ... 113 more, one per compiled extension module (121 Frameworks/* total) ...
```

`plutil -p hello-kivy.app/Info.plist` (abbreviated to the keys that matter for
the T3 pass — the full dump also carries `DTXcode`/`DTPlatformVersion`/
`CFBundleIcons*`/`UIDeviceFamily`, all build-time or fixed, not config-decided):

```
{
  "CFBundleDisplayName" => "Hello Kivy"
  "CFBundleExecutable" => "hello-kivy"
  "CFBundleIdentifier" => "org.kivy.hello-kivy"
  "CFBundleInfoDictionaryVersion" => "6.0"
  "CFBundleName" => "hello-kivy"
  "CFBundlePackageType" => "APPL"
  "CFBundleShortVersionString" => "0.1.0"
  "CFBundleVersion" => "1"
  "LSRequiresIPhoneOS" => true
  "MinimumOSVersion" => "16.0"
  "UIApplicationSceneManifest" => { ... }
  "UIApplicationSupportsIndirectInputEvents" => true
  "UISupportedInterfaceOrientations" => ["UIInterfaceOrientationPortrait"]
  "UISupportedInterfaceOrientations~ipad" => [ ...all four... ]
}
```

**What every compiled extension module looks like once hoisted** — e.g.
`Frameworks/_ssl.framework/`: `_ssl` (the Mach-O), `Info.plist`,
`PrivacyInfo.xcprivacy`, `_ssl.origin` (a text file naming the `.fwork` stub it
replaced — `python/lib/python3.15/lib-dynload/_ssl.cpython-315-iphonesimulator.fwork`),
and `_CodeSignature/CodeResources`. The stub itself, left at the original
location, is plain text containing the relative path back to the framework
(`Frameworks/_ssl.framework/_ssl`) — never Mach-O, which is why the arch sweep
below does not need to special-case it: `read_macho_cpu_type` simply fails to
parse it and it is skipped like any other non-binary file.

This is python-apple-support's `install_python` — Apple requires dynamic
libraries under `Frameworks/`, so every compiled `.so` in `app/`, `pip-deps/`,
and `python/lib/.../lib-dynload/` is moved there and replaced with a stub.
`_apple_support.py`/`_ios_support.py` in the staged stdlib are the runtime
half of that mechanism (a `MetaPathFinder` that resolves a `.fwork` stub back
to its framework at import time).

## Step 1 — the checker function

`ios_app_problems(app, *, arch, expected_plist=None)` added to
`tests/artifact_checks.py`, in a new "iOS" section between the macOS and Linux
ones, mirroring `macos_app_problems`'s shape:

- `_ios_required_entry_problems` — `Info.plist`, `Frameworks/Python.framework/
  Python`, `python/lib`, `app/`, `pip-deps/` all present.
- `_ios_plist_problems` — parses, the four required keys are non-empty,
  `CFBundleExecutable` names a real file at the bundle root, and every key in
  `expected_plist` matches.
- `_ios_arch_problems` — walks the whole tree (mirrors `_macos_arch_problems`
  exactly), reusing `machotools.read_macho_cpu_type`/`cpu_type_name`/
  `CPU_TYPE_ARM64`/`CPU_TYPE_X86_64` — no second Mach-O reader.
- `ios_expected_plist(config)` calls the production
  `platforms.ios.plist.build_info_plist` and drops `CFBundleExecutable`
  (written as the unresolved `"$(EXECUTABLE_NAME)"` placeholder), mirroring
  `macos_expected_plist`'s "call the production builder, don't restate its
  key list" shape.

No `stripped`/`expected_magic` parameters — see "What this harness does not
cover" above.

## Step 2 — hermetic tests

20 tests added to `tests/test_artifact_checks.py` (`TestIosCleanArtifacts`,
`TestIosArch`, `TestIosPlist`, `TestIosRequiredEntries`), built on a new
`_ios_app()` synthetic-bundle helper reusing the existing `_macho()` header
generator. Every check has a test that makes it fire, not only one that it
passes, per the prompt's instruction — including a specific
`test_a_fwork_stub_is_not_mistaken_for_a_binary` regression given how much of
the real bundle turned out to be `.fwork` text stubs (Step 0 above).

```
$ pytest tests/test_artifact_checks.py -k Ios -v --no-cov
...
20 passed in ...s
```

## Step 3 — CLI options and driver

`--ios-app`, `--ios-arch` (default `arm64`), `--ios-project` added to
`tests/conftest.py`'s `kivyforge artifacts` option group — no `--ios-stripped`,
documented at the option itself. `tests/platforms/ios/test_app_artifact.py`
mirrors `tests/platforms/macos/test_app_artifact.py`: skips cleanly without
`--ios-app`, `test_the_app_is_internally_consistent` turns on the
`Info.plist`-vs-config comparison when `--ios-project` is given, and
`test_the_app_is_codesigned` reuses `platforms.macos.machotools.codesign_verify`
directly rather than duplicating it — `codesign` doesn't care which platform's
bundle it's pointed at.

```
$ pytest tests/platforms/ios/test_app_artifact.py -v --no-cov
2 skipped in 0.75s
```

## Step 4 — validated against the real `.app`, including negatives

All four commands below were run against the exact bundle Step 0 produced.

**Clean pass:**

```
$ pytest tests/platforms/ios/test_app_artifact.py -v --no-cov \
    --ios-app .../hello-kivy.app --ios-project examples/mobile/hello-kivy
tests/platforms/ios/test_app_artifact.py::test_the_app_is_internally_consistent PASSED
tests/platforms/ios/test_app_artifact.py::test_the_app_is_codesigned PASSED
2 passed in 0.64s
```

**Negative 1 — claim the wrong arch** (`--ios-arch x86_64`): named all 114 real
Mach-O binaries at the wrong arch — the root executable plus every one of the
113 thin, single-arch `Frameworks/*` binaries this build compiled (the 8
fat/universal vendor frameworks are correctly not among them; see "No defects
found" above):

```
E       Frameworks/kivy.graphics.vertex_instructions.framework/kivy.graphics.vertex_instructions is arm64 but this build is x86_64 — a host or cross-arch binary leaked into the bundle
E       ...(112 more)...
E       hello-kivy is arm64 but this build is x86_64 — a host or cross-arch binary leaked into the bundle
1 failed in 0.38s
```

**Negative 2 — edit the built `Info.plist`** (`plutil -replace
CFBundleShortVersionString -string "9.9.9"`, the *built* file, not the
fixture's `pyproject.toml`): caught by the comparison, **and** — exactly as
the prompt asked to check, and exactly as macOS behaves — it independently
broke the code signature, because the signature seals `Info.plist`:

```
E   AssertionError: hello-kivy.app is not the artifact the build promised (arch=arm64):
E       Info.plist CFBundleShortVersionString is '9.9.9', but config declares '0.1.0'
...
FAILED test_the_app_is_internally_consistent
FAILED test_the_app_is_codesigned
2 failed in 0.39s
```

**Rebuilt clean:** `Info.plist` restored byte-for-byte from a backup taken
before the edit (`codesign --verify` passes again on the restored bytes — no
full `xcodebuild` re-run needed for a same-bytes restore). Re-ran both tests
green afterward. `git status` was clean throughout — `hello-kivy-ios/` is
gitignored and was never tracked.

## Step 5 — wired into `ios_simulator`

A new step, "Assert the .app is the artifact the build promised (T3)", added
between "Build for the simulator (T2)" and "Install + launch on the simulator
(T4 launch smoke)" in `.github/workflows/kivyforge.yml`. Confirmed locally
with the *exact* command CI runs (same `APP_DIR`, same `ls -d` glob, same
`KIVYFORGE_REQUIRE_TOOLCHAIN=1`):

```
$ export APP_DIR=examples/mobile/hello-kivy KIVYFORGE_REQUIRE_TOOLCHAIN=1
$ app="$(ls -d "$APP_DIR"/hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/*.app)"
$ pytest tests/platforms/ios/test_app_artifact.py -q --no-cov \
    --ios-app "$app" --ios-arch arm64 --ios-project "$APP_DIR"
..                                                                       [100%]
```

Confirmed: `..`, not `.s` — both tests actually ran, not skipped. The YAML was
validated with `python -c "import yaml; yaml.safe_load(...)"` before and after
this edit.

## Step 6 — full suite, docs

```
$ pytest
3012 passed, 55 skipped, 289 warnings in 10.54s
Required test coverage of 80% reached. Total coverage: 92.88%

$ ruff check kivyforge tests && ruff format --check kivyforge tests
All checks passed! / 381 files already formatted

$ pyright
0 errors, 0 warnings, 0 informations
```

Docs updated: `test-matrix.md` §5.1 (iOS box checked off), §3.1 (`ios_simulator`
Serves column), §3.2 (iOS simulator T3 cell), §7 (this row + the "reading the
partials" and "known-unverified" prose that referenced the missing harness),
and roadmap item 5 (remaining-work list — only the hardware checklist is
left).

## What was not touched

- `pylock.ios.toml` — untouched (`git status` clean throughout; not diffed
  because it was never regenerated).
- `hello-kivy-ios/` — the generated staging tree was never in the working
  tree at any point (`examples/mobile/hello-kivy/.gitignore` excludes it).
- No device or `--release`/`--export-method` build was produced this session
  — see "What this harness does not cover" above.
