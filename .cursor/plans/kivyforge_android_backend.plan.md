---
name: Kivyforge Android backend
overview: Implement the Android backend from the settled design (docs/design/platforms/android/01–08), on the wheel-assembly + Gradle-drive bet validated by the pyjnius spike. Sequenced prove-first — Phase 0 produces the vendored Kivy 2.3.1 + pyjnius Android wheels AND proves the full kivyforge load model (asset-bundle unpack, flattened-extension finder, SDL→libpython→libmain order, invoke0 glue) in a hand-built prototype app on the Windows-host emulator BEFORE any backend code is written; the bootstrap templates are then extracted from that proven prototype. Then config/init/platform shell, the per-ABI lock engine (python.org runtime provider + pip cross-resolve + .aar/.jar + Gradle/Maven pins), bootstrap templates + native launcher, build/stage/generate (debug-APK gate), run + emulator + the generated contract smoke test, release packaging (mandatory signing, manifest-policy preflight, .aab, native debug symbols), doctor + remaining verbs, then examples (pyjnius featured; ZXing via Maven) and docs. Validation target is the Windows-host Android Studio emulator; each phase ends in a testable gate.
todos:
  - id: phase0-wheels-loadmodel-proof
    content: "Phase 0 — Vendored wheels + on-device load-model proof (PROVE FIRST): cross-build Kivy 2.3.1 android_24 wheels (cp314, arm64_v8a + x86_64, flat .libs/ SDL2 family, explicit -Wl,-z,max-page-size=16384) and rebuild the spike's pyjnius wheels in WSL; hand-assemble a minimal Gradle app on the Windows host that exercises kivyforge's OWN load model (asset unpack, meta_path finder over flattened .so, SDL2→libpython→libmain order, NativeInvocationHandler invoke0) on the Windows-host x86_64 emulator; record docs/design/dev/android-loadmodel-findings.md."
    status: completed
  - id: phase1-config-init-shell
    content: "Phase 1 — Config, init, platform shell: AndroidConfig dataclasses + loader validation (rules 1–21, version_code auto derivation, permissions/auto_features, splash/icons, services/foreground, manifest passthrough XML well-formedness, signing, build_settings), render_android_tables in init_writer, AndroidPlatform registration (host_system None, formats apk/aab), lock/build/run/package/status dispatch stubs, full loader test matrix."
    status: completed
  - id: phase2-lock-engine
    content: "Phase 2 — Lock engine: PythonOrgAndroidProvider (per-ABI python.org embeddable pins + min_api), per-ABI pip cross-resolve with missing-ABI/version-skew fail-fast and wheel-tag-floor rule, find_links/extra_index_urls/exclude, android_libs + include_files SHA-256 pins, Gradle/Maven channel (scratch project, --write-locks --write-verification-metadata sha256, parse → [[tool.kivyforge.gradle.resolved]]), pylock.android.toml writer/reader/drift, golden lockfiles + one live-boundary test. Gate: `kivyforge lock -p android` reproducible."
    status: completed
  - id: phase3-bootstrap-launcher
    content: "Phase 3 — Bootstrap templates + native launcher, extracted from the Phase 0 prototype: org.kivy.android.{PythonActivity,PythonService}, org.libsdl.app (SDL2 rev; SDL3 rev stubbed per schema), org.jnius.NativeInvocationHandler + invoke0 compat-range gate machinery, cpp/main.c + CMakeLists.txt (env contract, PyConfig, finder install, site.addsitedir), extension-module manifest format, template render/snapshot tests + marker-gate tests."
    status: completed
  - id: phase4-build-stage-generate
    content: "Phase 4 — Build (collect/stage/generate): download+cache runtime/.aar per lock; per-ABI wheel install (--no-deps from pins); jniLibs staging (runtime soname/lib-dynload split, wheel .so flattening + deterministic names, flat-only .libs/ enforcement, duplicate-.so policy); asset bundle (byte_compile/strip_source, per-ABI content-identity assertion, finder manifest); Gradle project generation (build.gradle/settings/properties/wrapper pin, AndroidManifest incl. auto_features/services/intent_filters/passthrough, styles/splash/icons mipmap pipeline, androidTest smoke source, include_files, app/gradle.lockfile + verification-metadata materialization); determinism/idempotency tests. Gate: generated project builds a debug APK via gradlew on the Windows host."
    status: completed
  - id: phase5-run-smoke
    content: "Phase 5 — Run + emulator + contract smoke test: adb/emulator integration (device pick, AVD boot/wait, install -r, am start, filtered logcat), host-arch --abi defaults, --no-build; the generated instrumented contract smoke test (launch, stdlib+wheel extension import through the finder, invoke0 proxy round-trip) wired to `run --smoke` / `--smoke --release` via connectedAndroidTest. Gate: hello app runs and `run --smoke` is green on the Windows-host emulator."
    status: completed
  - id: phase6-package-signing-policy
    content: "Phase 6 — Package, signing, manifest policy: signing preflight (keystore/alias/env fail-fast), Gradle signingConfigs emission, apksigner v1(off)–v4 toggles, bundleRelease .aab (jarsigner), native-debug-symbols.zip export per debug_symbols, manifest-policy preflight (curated lintRelease subset + hand-rolled checks: single LAUNCHER, exported explicit + bootstrap-only, debuggable, org.example placeholder, deep-link conflicts, dangerous-permission INFO). Gate: signed release .apk sideloads; .aab produced; policy checks pass the fixture matrix."
    status: completed
  - id: phase7-doctor-verbs
    content: "Phase 7 — Doctor + remaining verbs: full Android doctor table (JDK/SDK/build-tools/licenses/NDK/wrapper/emulator+virtualization/adb; project: app source, SDL↔Kivy, pyjnius↔bootstrap marker FAIL, 16 KB ELF LOAD + zip-alignment scanner, ABI coverage, icons/splash, find_links, signing, lock-host reachability, app-local .so scan, include_files, manifest XML, manifest policy, implied-features INFO) with a fake-probe test matrix; status/open/upgrade/clean Android behavior."
    status: completed
  - id: phase8-examples-verifier
    content: "Phase 8 — Examples + verifier: [tool.kivy.android] overlay on examples/mobile/hello-kivy; new examples/mobile/pyjnius-deviceinfo (pyjnius autoclass device/Build/battery info, mirrors pyobjus-deviceinfo); new examples/mobile/qr-maven (com.google.zxing:core via [tool.kivy.android.gradle], pyjnius QRCodeWriter → Kivy texture, plus a PythonJavaClass callback exercising invoke0); vendored wheels/ + committed pylock.android.toml per policy; PowerShell verifier (clean/lock/doctor/build/run/run --smoke/package) on the Windows host."
    status: completed
  - id: phase9-docs-promotion
    content: "Phase 9 — Docs, matrix promotion, release readiness: promote compatibility-matrix rows Prototype→Validated from first-party smoke evidence; realized-vs-designed notes on android docs 01–08; README/FAQ/CHANGELOG; document the invoke0 marker as implemented; record deferred items (GitHub Actions emulator CI, SDL3 on-device, cp315 wheels, PyPI publication). Final gate: pytest+ruff green on all hosts; verifier green on the Windows-host emulator for all three examples. Stop for review."
    status: completed
isProject: false
---

# Kivyforge Android Backend

Implementation plan for the Android backend — the fourth platform family,
following the shipped macOS/Linux/Windows desktop backends and the iOS backend.
The design is settled in eight companion specs plus the spike evidence; this
plan sequences the build against them and against the shipped codebase seams.

- [01-pyproject-android.md](../../docs/design/platforms/android/01-pyproject-android.md) — `[tool.kivy.android]` overlay schema + validation rules 1–21.
- [02-pylock-android-spec.md](../../docs/design/platforms/android/02-pylock-android-spec.md) — `pylock.android.toml` (PEP 751 + `[tool.kivyforge]`).
- [03-artifact-distribution-android.md](../../docs/design/platforms/android/03-artifact-distribution-android.md) — the four channels; flat-only `.libs/`.
- [04-gradle-project-generation.md](../../docs/design/platforms/android/04-gradle-project-generation.md) — the generated AGP project; `.so` load model; asset bundle.
- [05-bootstrap-android.md](../../docs/design/platforms/android/05-bootstrap-android.md) — launch sequence, env contract, finder, pyjnius contract.
- [06-cli-android.md](../../docs/design/platforms/android/06-cli-android.md) — verbs, flags, doctor table, `--smoke`.
- [07-signing-prerequisites-android.md](../../docs/design/platforms/android/07-signing-prerequisites-android.md) — keystore checklist.
- [08-compatibility-matrix.md](../../docs/design/platforms/android/08-compatibility-matrix.md) — supported combos + promotion mechanism.
- Evidence: [pyjnius-android-wheel-spike-findings.md](../../docs/design/dev/pyjnius-android-wheel-spike-findings.md) (Steps 2–7), [pyjnius-android-wheel-proposal.md](../../docs/design/dev/pyjnius-android-wheel-proposal.md), [android-wheels-findings.md](../../docs/design/dev/android-wheels-findings.md).

**Template backends.** iOS is the structural template (own `lock/` package with
`builder`/`resolver`/`python_meta` `PythonOrgProvider`/`writer`/`reader`, a
project `generator`, `staging`, `materialize`, an external-toolchain `runner`);
Windows is the process template (prove-first gating, fake-probe doctor matrix,
PowerShell example verifier). The shared pieces to reuse: `platforms/base.py`
`Platform`, the platform registry + `resolve_target`, `cli/lock.py` `_LockOps`
dispatch, `config/model.py`+`loader.py` conventions, `cli/init_writer.py`
table renderers, the doctor `CheckResult` framework, and the download-cache
machinery the desktop/iOS collectors use.

## Settled decisions

- **Wheel production is in scope (Phase 0).** The backend consumes vendored,
  locally cross-built **Kivy 2.3.1** and **pyjnius** Android wheels
  (`find_links` + `path` pins) until first-party wheels reach PyPI. The pyjnius
  wheels rebuild from the spike branch (`ElliotGarbus/pyjnius`,
  `spike/android-universal-wheel`, already productionized: Java-free, 16 KB
  LDFLAGS pinned, cp314 arm64_v8a + x86_64). The Kivy wheel is new work.
- **Validation environment: Windows-host emulator.** Android Studio + SDK/NDK on
  the Windows side; kivyforge drives `gradlew.bat`/`adb`/`emulator` natively —
  this exercises exactly the host path Windows end users will take. The WSL SDK
  stays for wheel *building* only (cibuildwheel needs a POSIX host). GitHub
  Actions emulator CI is **deferred** (recorded in Phase 9), not designed in.
- **Full spec, phased.** Every feature in docs 01–08 is in this plan; nothing is
  silently dropped. The long tail (services/foreground, Kotlin, intent filters,
  manifest raw-XML, R8 posture, include_files) lands in Phases 4 and 6 where the
  generator/packager naturally owns it.
- **Java-library demo = Maven channel.** `com.google.zxing:core` from Maven
  Central via `[tool.kivy.android.gradle]`, driven from Python with pyjnius
  (channel 4 + the gradle-pins machinery). The `.aar`/`.jar` URL channel
  (channel 3) is implemented and unit/integration tested in Phases 2/4 but does
  not get its own example.
- **`.libs/` is flat-only** (per the updated 03/04): a nested `.libs/<abi>/` is
  a malformed wheel and fails the build. No legacy-consumer path.
- **SDL generation:** `sdl = 2` (Kivy 2.3.1) is the exercised path end to end.
  `sdl = 3` is first-class in schema, templates, and unit tests, but on-device
  SDL3 validation stays **Pending** in the matrix until a Kivy 3.0 host exists.
- **`v1_signing` defaults off** (min_sdk floor is 24); **NDK required for every
  build** (compiles the emitted `libmain.so`); **auto `version_code`** formula
  per 01. The `invoke0` compatibility marker (05 "Implementation status") gets
  its concrete mechanism in Phase 3 (below) — this plan closes that work item.
- **Namespace:** `[tool.kivy.android]` stays (sanctioned; see project memory).

## Non-negotiable sequencing

1. **Prove the load model on a device before writing backend code (Phase 0).**
   The spike validated the *wheel* (JNIEnv resolver, invoke0 glue) — but under
   **p4a's** bootstrap and layout. kivyforge's own load model — asset-bundle
   unpack, `sys.meta_path` finder over *flattened* extension `.so`s in
   `nativeLibraryDir`, `site_import=0` init ordering, the multi-ABI-shared
   bundle — has **never run anywhere**. A generator that emits a broken load
   model looks exactly like a generator bug; the hand-built prototype is the
   green light, and it becomes the source the Phase 3 templates are extracted
   from (the same role the Windows clean-VM DLL proof played).
2. **Wheels before lock tests, lock before build.** The lock engine's golden
   tests need real vendored wheels to hash; `build` consumes only pins.
3. **Templates before the generator.** Phase 4's generator emits Phase 3's
   proven templates; never write templates and generator concurrently against
   an unproven contract.
4. **Debug loop before release.** `build --debug` → `run` → `run --smoke` all
   green before any signing/packaging work; the smoke gate is the promotion
   mechanism for the compatibility matrix and must exist before Phase 6 claims
   release readiness.
5. **Doctor last-but-one.** Checks assert against real seams (staged `.so`s,
   generated manifests, the marker gate); most can't be written honestly until
   those exist.

## Module layout (new code)

```
kivyforge/platforms/android/
├── __init__.py            ← AndroidPlatform (registry entry; host_system=None)
├── cli.py                 ← build/run/package/status/open verb impls
├── doctor.py              ← environment + project checks (06 table)
├── adb.py                 ← adb/emulator/avd discovery, install, am start, logcat
├── gradlew.py             ← Gradle wrapper invocation (assembleDebug/Release, bundle, connectedAndroidTest)
├── signing.py             ← keystore preflight, signingConfig values, scheme toggles
├── policy.py              ← release manifest-policy preflight (lint subset + custom checks)
├── smoke.py               ← --smoke orchestration over connectedAndroidTest
├── icons.py               ← adaptive-icon mipmap + splash/theme resource pipeline
├── elf.py                 ← minimal ELF LOAD-segment/alignment + DT_NEEDED reader (hermetic; no NDK tools)
├── bootstrap/
│   ├── templates/…        ← PythonActivity/PythonService/SDLActivity(SDL2|SDL3)/NativeInvocationHandler .java,
│   │                        main.c, CMakeLists.txt, styles/splash XML, androidTest smoke test
│   ├── render.py          ← template rendering + per-`sdl` selection
│   └── contract.py        ← invoke0 contract version + supported pyjnius range (the marker gate)
├── stage/
│   ├── runtime.py         ← python.org runtime extract + soname/lib-dynload split
│   ├── wheels.py          ← per-ABI pip install --no-deps from pins
│   ├── jnilibs.py         ← flattening, deterministic names, flat-.libs enforcement, duplicate policy
│   └── bundle.py          ← asset bundle assembly, byte-compile/strip, ABI-identity assertion, finder manifest
├── generate/
│   ├── project.py         ← settings/root/app build.gradle, gradle.properties, wrapper pin, include_files
│   ├── manifest.py        ← AndroidManifest.xml (permissions/auto_features/services/filters/passthrough)
│   └── gradle_pins.py     ← app/gradle.lockfile + verification-metadata.xml materialization
└── lock/
    ├── python_meta.py     ← PythonOrgAndroidProvider (per-ABI URL+sha256+min_api)
    ├── resolver.py        ← per-ABI pip cross-resolve, fail-fasts, tag-floor rule, exclude
    ├── maven.py           ← scratch-project Gradle resolve → resolved[] pins
    ├── builder.py         ← orchestrates channels 1–4 + include_files hashing
    ├── writer.py / reader.py / model.py
```

Config additions live in the shared `config/model.py` + `loader.py` +
`cli/init_writer.py` (matching how Ios/Macos/Windows/Linux configs are hosted).
Tests mirror the tree under `tests/platforms/android/`.

---

## Phase 0 — Vendored wheels + on-device load-model proof (PROVE FIRST)

**Wheels (WSL, cibuildwheel):**

- Rebuild **pyjnius** cp314 `android_24_{arm64_v8a,x86_64}` from the spike
  branch; verify the productionized invariants (Java-free, no SDL `DT_NEEDED`,
  16 KB LOAD alignment, `dlopen/dlsym`-only) with the findings' ELF checklist.
- Build the **Kivy 2.3.1** Android wheels: cp314, both ABIs, SDL2 family
  (`libSDL2`, `SDL2_image/mixer/ttf`) + Kivy's compiled extensions, native libs
  under a **flat** top-level `.libs/`, `-Wl,-z,max-page-size=16384` pinned
  explicitly (03 §wheel content rules). Baseline the kivy-school build recipe
  as reference material, but the build config is kivyforge-owned and committed
  (a `wheels-build/` recipe dir or a documented sibling repo — decide in-phase
  and record).
- Deliverable: `wheels/` payload for the examples + a SHA-256 manifest +
  reproducibility pins (NDK via cibuildwheel version, API 24, Cython pin).

**Load-model prototype (Windows host):**

- Hand-assemble a minimal Gradle app (no kivyforge involvement) implementing
  the 05 launch sequence *as specified*: SDLActivity static-loads SDL2 →
  libpython3.14 → libmain; `main.c` unpacks an asset bundle, sets the env
  contract (`PYTHONHOME/PYTHONPATH/ANDROID_ARGUMENT/…`), calls
  `Py_InitializeFromConfig` with `site_import=0`/`utf8_mode`/system logger,
  installs the **meta_path finder** from a generated manifest over **flattened**
  stdlib `lib-dynload` + wheel-extension `.so`s in `jniLibs/x86_64/`, runs
  `import site` + `addsitedir`, imports the entry point.
- Prove, on the Windows-host x86_64 emulator: `import _ssl` (stdlib extension
  through the finder), `import kivy` + an SDL window, `import jnius` (tier-2
  JNIEnv), a `PythonJavaClass` round-trip through the app-side
  `NativeInvocationHandler`, and second-launch skip-unpack (version stamp).
- Record **`docs/design/dev/android-loadmodel-findings.md`**: what the finder
  manifest needs, `noCompress` behavior, unpack timing, any deviation forced on
  the 05 spec (feed corrections back into the docs immediately).

**Gate:** all five prototype checks green on the emulator; wheels reproducible
and ELF-verified. *No backend code is written before this gate.*

## Phase 1 — Config, init, platform shell

- `AndroidConfig` (+ `AndroidPythonConfig`, `AndroidPermissions`,
  `AndroidIcons/Splash`, `AndroidNativeDep`, `AndroidGradleDeps`,
  `AndroidService/Activity/IntentFilter`, `AndroidManifestPassthrough`,
  `AndroidSigningConfig`, `AndroidBuildSettings`) in `config/model.py`;
  loader enforcement of **validation rules 1–21** including: package-name
  grammar, `min_sdk ≥ 24` floor, `sdl ∈ {2,3}`, 64-bit-only `abis`,
  `version_code` `"auto"` derivation (formula, final-release-only, ≤99
  components, 2.1 G ceiling) with a worked-example test table, foreground
  service requires type+notification, raw-XML well-formedness, reserved
  manifest/gradle-properties keys, path-escape rejection everywhere.
- `render_android_tables` in `init_writer.py` (seeds per 06 §init: `INTERNET`,
  `exclude` block when kivy is direct, TODO stubs, `--force` preservation set).
- `AndroidPlatform` in `platforms/android/__init__.py` (aliases, formats
  `("apk","aab")`, `check_host_capability` = any OS), registry + `cli/lock.py`
  `_LockOps` + clean/upgrade/status dispatch.
- **Tests:** loader matrix (valid/invalid per rule, one test per rule number),
  version_code table, init golden render, `--force` preservation, resolution
  chain (`-p android`, env var, no-host-default).
- **Gate:** `kivyforge init`+`doctor -p android` (env-mode stub) run on a fresh
  dir; full pytest+ruff green on all three desktop OSes.

## Phase 2 — Lock engine

- `PythonOrgAndroidProvider` modeled on the iOS `PythonOrgProvider`: resolve
  version → per-ABI (`aarch64`, `x86_64`) URL + SHA-256 from the release file
  list; read `min_api` from artifact metadata; error when `min_sdk < min_api`.
- Per-ABI resolver: pip cross-resolve (`--platform android_<min_sdk>_<abi>
  --python-version --implementation --abi --only-binary=:all:`) per ABI;
  **fail-fasts**: missing-ABI slice, inconsistent version across ABIs;
  **tag-floor rule** (`wheel_tag_api ≤ min_sdk`, highest compatible wins);
  `find_links` (repo-relative, → `path` pins) and `extra_index_urls`
  (→ pinned `url` + `source_index`); `exclude` graph pruning (direct deps win).
- Channels 3/4: `android_libs` fetch/hash; `maven.py` writes a scratch
  `build.gradle`, runs `gradlew --write-locks --write-verification-metadata
  sha256`, parses the graph into `[[tool.kivyforge.gradle.resolved]]` (skipped
  when no Maven deps; requires JDK — clean error otherwise). `include_files`
  hashing (directory expansion).
- Writer/reader: PEP 751 `[[packages]]` + `[tool.kivyforge]` per 02, sorted
  deterministic output, atomic write, `pyproject_sha256` drift check,
  `--check`/`--offline`/`--update`.
- **Tests:** golden `pylock.android.toml` against a fixture project with fake
  local wheels (both ABIs + pure-py + a deliberately missing-ABI package + a
  version-skew pair); provider unit tests against a recorded release file
  list; maven parse tests against recorded Gradle outputs; ONE live-boundary
  test each for python.org metadata and a real pip resolve (network-marked).
- **Gate:** `kivyforge lock -p android` is byte-reproducible on the fixture and
  on a real project using the Phase 0 vendored wheels.

## Phase 3 — Bootstrap templates + native launcher

- Extract the Phase 0 prototype into versioned templates under
  `bootstrap/templates/`: `PythonActivity`/`PythonService` (`org.kivy.android`),
  SDL2 Java glue at the Kivy 2.3.1 revision (`org.libsdl.app`), SDL3 glue
  slot (schema-complete, marked unexercised), `NativeInvocationHandler.java`,
  `main.c` + `CMakeLists.txt`, splash/theme XML, the generated `androidTest`
  contract smoke test source.
- `contract.py` — **the invoke0 marker, made real**: the template declares
  `INVOKE0_CONTRACT = 1` + a pyjnius `SpecifierSet`; the build gate fails when
  the locked pyjnius is outside the range (05 hard gate; doctor FAIL reuses
  it). Wheel-side: until upstream carries a machine-readable marker, the
  template's range list IS the enforcement — document the coordination item.
- Extension-module manifest format (dotted-module → flattened filename),
  shared by `stage/jnilibs.py` (writer) and `main.c`/finder (reader).
- **Tests:** render snapshots per `sdl` and per service/notification configs;
  marker-gate matrix (in-range, below, above, missing pyjnius); manifest
  round-trip; C template compiles under a host compiler smoke (syntax-level).
- **Gate:** rendered templates diff-clean against the proven prototype.

## Phase 4 — Build: collect / stage / generate

- **Collect:** download+cache per-ABI runtime and `.aar`/`.jar` from pins
  (SHA-256 verified; reuse the shared cache helper); `--no-cache`.
- **Stage:** per-ABI wheel install (`--no-deps --target`, pins only);
  `stage/runtime.py` splits soname libs (verbatim into `jniLibs/<abi>/`) from
  `lib-dynload` (flattened + manifest); `stage/jnilibs.py` flattens wheel
  extensions, ingests **flat-only** `.libs/` (nested → hard error naming the
  wheel), applies the duplicate-`.so` policy (hash-dedupe / conflict-abort);
  `stage/bundle.py` assembles the ABI-independent bundle (stdlib + pure-py +
  `app-src/` link-or-copy), applies `byte_compile`/`strip_source` per
  build_settings (target-3.14 magic), asserts per-ABI non-`.so` content
  identity (canonical-ABI + per-file SHA-256 comparison).
- **Generate:** `generate/project.py` + `manifest.py` + `icons.py` emit the 04
  layout — root/app `build.gradle` (ABI filters, `externalNativeBuild` +
  pinned `ndkVersion`, `useLegacyPackaging`, `keepDebugSymbols`,
  `debugSymbolLevel`, `noCompress`, signingConfigs slot, deps from channels
  3/4), `gradle.properties` (managed + user, reserved-key rejection), pinned
  wrapper, manifest (managed keys, permissions + auto_features synthesis +
  override precedence, services/foreground permissions, intent filters,
  passthrough attrs + substituted raw XML), adaptive-icon mipmaps + splash
  theme, androidTest smoke source, `include_files` copy (clobber rejection),
  `gradle_pins.py` materialization. Deterministic output (sorted, stable).
- **Tests:** fixture-driven staging tests with fabricated tiny wheels/runtimes
  (flat/nested `.libs/`, duplicates identical+conflicting, ABI-identity
  violation); bundle byte-compile matrix; generator snapshot tests (manifest
  XML per feature combination, build.gradle per settings); idempotency
  (re-run → zero diff); `elf.py` alignment reader against fixture ELFs.
- **Gate:** on the Windows host with SDK+NDK: `kivyforge build --debug` on the
  hello fixture produces a debug APK via `gradlew.bat assembleDebug`; APK
  content assertions (zip inspection: jniLibs present + 16 KB zip-aligned,
  bundle asset present, merged manifest correct).

## Phase 5 — Run + emulator + contract smoke test

- `adb.py`: device/AVD enumeration (`--list-devices`), selection rules
  (`--device`/`--emulator`/`--serial`/`--avd`, single-device auto), AVD boot +
  `wait-for-device` + `sys.boot_completed`, `install -r`, `am start -n
  <pkg>/org.kivy.android.PythonActivity`, app-filtered logcat streaming.
- `run` verb: implicit `build --debug`, host-arch `--abi` default
  (x86_64/arm64 per host), `--no-build`, drift-check propagation.
- `smoke.py`: `run --smoke [--release]` drives the generated instrumented test
  via `gradlew connected<Variant>AndroidTest`; non-zero exit on red; release
  variant exercises byte-compiled/stripped/R8-posture payloads under a test
  signing config.
- **Tests:** adb/emulator logic against a fake-adb probe layer (no device in
  unit CI); an integration marker (`android_device`) for the real-emulator
  path; smoke-result parsing fixtures.
- **Gate:** on the Windows-host emulator: `kivyforge run` shows the Kivy window;
  `kivyforge run --smoke` green — the first first-party validation evidence
  for the matrix.

## Phase 6 — Package, signing, manifest policy

- `signing.py`: preflight (resolve keystore/alias from overlay/flags, env
  passwords present, `keytool -list` alias check) failing before Gradle with
  the 06 error text; emitted `signingConfigs` reading env at Gradle time
  (passwords never written to disk); scheme toggles v1(default off)–v4 for
  `.apk`; `.aab` via `bundleRelease` (jarsigner semantics documented).
- `policy.py`: merged-manifest release preflight — curated `lintRelease`
  subset (exported components, `allowBackup`, cleartext) + hand-rolled checks
  (exactly one LAUNCHER; every intent-filtered component explicit `exported`
  and only bootstrap components exported; `debuggable` not forced;
  `org.example.*` placeholder; deep-link `<data>` conflicts; dangerous
  runtime-permission INFO). FAIL aborts pre-signing.
- `package -f apk|aab` end-to-end; `native-debug-symbols.zip` export per
  `debug_symbols`; outputs under `app/build/outputs/` per 04.
- **Tests:** preflight matrix (missing keystore/alias/env/each); policy fixture
  manifests (one per rule, pass+fail); scheme-toggle → build.gradle snapshot;
  integration: self-generated throwaway keystore, `package -f apk`, verify
  with `apksigner verify --print-certs`, sideload on the emulator; `-f aab`
  produced + `bundletool` spot-check.
- **Gate:** signed release .apk installs and passes `run --smoke --release`.

## Phase 7 — Doctor + remaining verbs

- Full 06 doctor table. Environment: JDK 17+, `ANDROID_HOME`/`sdkmanager`,
  compile_sdk platform + build-tools, licenses, **NDK (every build)**, wrapper
  distribution reachability, emulator/virtualization (WARN + setup pointer),
  adb. Project: app source, SDL↔Kivy WARN, pyjnius↔bootstrap **FAIL** (reuses
  `contract.py`), 16 KB scanner (every staged `.so` LOAD + APK zip alignment
  via `elf.py` — hermetic, no NDK tooling), ABI coverage vs lock, icon/splash
  asset validation, find_links dirs, signing check, lock-host TCP
  reachability, app-local `.so` scan, include_files existence/dest/drift,
  manifest raw-XML parse, release manifest policy, implied-features INFO.
  All hints derived from project config (`platforms;android-<compile_sdk>`),
  never a maintained version manifest.
- `status` (06 snapshot), `open` (Android Studio via `studio`/opener),
  `upgrade` (`--python`/`--libs`/`--name`, re-fetch only), `clean`
  (`--project-only` default, `--cache` + `gradlew --stop`, `--cache-all`).
- **Tests:** fake-probe matrix per check (PASS/WARN/FAIL/SKIP × probe states),
  mirroring the Windows doctor tests; one real project-mode doctor run on the
  Windows host.
- **Gate:** doctor honest on a correctly-configured host (all PASS/SKIP) and on
  a deliberately broken one (each check individually trips).

## Phase 8 — Examples + verifier

Three examples, all committing `pyproject.toml` + `pylock.android.toml` +
vendored `wheels/` (per 04 §ownership; `<app>-android/` is gitignored):

1. **`examples/mobile/hello-kivy`** — add the `[tool.kivy.android]` overlay to
   the existing example: the minimal path (kivy + pyjnius pins, icons/splash,
   INTERNET). Proves the smallest possible config.
2. **`examples/mobile/pyjnius-deviceinfo`** *(new; mirrors
   `pyobjus-deviceinfo`)* — **pyjnius featured**: `autoclass` for
   `android.os.Build` (model/manufacturer/SDK), battery status via
   `BatteryManager`, display metrics; UI shows the values. Exercises
   `kivy.utils.platform` guarding and the `ANDROID_ARGUMENT` contract.
3. **`examples/mobile/qr-maven`** *(new)* — **the downloaded Java library**:
   `[tool.kivy.android.gradle] dependencies = ["com.google.zxing:core:<pin>"]`
   (Maven Central, channel 4 → gradle pins + verification-metadata end to
   end). Python drives `QRCodeWriter.encode()` via pyjnius, converts the
   `BitMatrix` to a Kivy texture, renders the QR code for user-entered text;
   plus a `PythonJavaClass` `Runnable` callback (Java → Python through
   `invoke0`) so the matched-pair path is demonstrated in a *shipped example*,
   not only the smoke test. Lock requires a JDK (documented in the example
   README).

- **Verifier:** `examples/verify-android.ps1` (sibling of the Windows
  verifier): per example — `clean` → `lock --check` → `doctor` → `build
  --debug` → `run` (boot AVD, assert launch marker in logcat) → `run --smoke`
  → `package -f apk` (throwaway keystore). Red exit on any step.
- **Gate:** verifier green for all three examples on the Windows-host emulator.

## Phase 9 — Docs, matrix promotion, release readiness

- Promote [08-compatibility-matrix](../../docs/design/platforms/android/08-compatibility-matrix.md)
  rows from **Prototype** to **Validated** with cited first-party smoke runs
  (CPython 3.14 / Kivy 2.3.1 / SDL2 / both ABIs — arm64 requires one physical
  device run; keep it Prototype if no device session happens, honestly).
- Realized-vs-designed notes on android docs 01–08 (the Windows-spec pattern);
  fold any Phase 0/4 deviations back into the specs.
- README/FAQ/CHANGELOG; `[android]` Pillow extra if the icon pipeline needs it
  (mirror `[windows]`); document the invoke0 marker mechanism in 05.
- Record deferred work explicitly: GitHub Actions KVM emulator CI (the canary
  the docs call for), SDL3 on-device once Kivy 3.0 lands, cp315 wheels,
  upstream pyjnius PyPI publication (spike PR scaffolding exists), physical
  arm64 device in the verifier loop.
- **Final gate:** pytest + ruff green on Windows/macOS/Linux; verifier green on
  the Windows-host emulator; matrix/docs updated. **Stop for review.**

---

## Test plan (cross-phase summary)

**Layer 1 — hermetic unit tests (run everywhere, no SDK):** config loader
rule-by-rule matrix; version_code derivation table; permissions/auto-features
synthesis + override precedence; manifest/build.gradle/styles snapshot tests
per feature combination; raw-XML validation; lock golden files with fabricated
wheels (both-ABI, pure-py, missing-ABI, version-skew, nested-`.libs` reject);
provider/maven parsers against recorded outputs; staging fixtures (duplicate
`.so` dedupe/conflict, ABI-identity assertion, byte-compile matrix); `elf.py`
against hand-built ELF fixtures; marker-gate matrix; doctor fake-probe matrix;
adb logic against a fake-adb layer; policy fixture manifests; determinism
(lock and generate re-runs are byte-identical).

**Layer 2 — host-integration tests (Windows host with JDK+SDK+NDK; pytest
marker `android_sdk`):** `gradlew assembleDebug` on the generated fixture
project + APK zip-content/alignment assertions; scratch-project Maven
lock/verify round-trip; `apksigner verify` on a self-signed package; one live
python.org metadata resolve + one live pip cross-resolve (marker `network`).

**Layer 3 — on-device tests (Windows-host emulator; marker `android_device`):**
`run` launch assertion via logcat marker; `run --smoke` (debug) and
`run --smoke --release` — the contract gates (finder import + invoke0
round-trip); example verifier end-to-end. arm64 hardware session is a manual,
documented checklist until a device is in the loop.

Every phase lands its Layer-1 tests with the code; Layer-2/3 tests land with
their phase's gate and are skipped (not failed) where the toolchain is absent.

## Deferred work (recorded at v1 completion)

All ten phases are implemented and gated on the Windows-host x86_64 emulator
(init → lock → build → run → run --smoke → package, plus three examples). Open
items, each tracked in the docs:

- **First-party Kivy 2.3.1 cibuildwheel wheel** (Phase-0 carryover) — the interim
  p4a-derived Kivy wheel is 4 KB-aligned; `doctor` FAILs its 16 KB check. This is
  the one blocker to a Play-Store-shippable artifact. The pyjnius wheel is already
  first-party.
- **arm64 physical-device validation** — the matrix keeps arm64 at *Prototype*
  (only the spike's earlier p4a Pixel 8a run); no first-party device session this
  cycle. Run `kivyforge run --smoke` on hardware to promote it.
- **SDL3 / Kivy 3.0 on-device** — schema/templates are SDL3-ready but *Pending*
  until a Kivy 3.0 SDL3 host exists.
- **cp315 wheels** — Kivy/pyjnius `android_cp315` wheels are not published yet.
- **Gradle-enforced `verification-metadata.xml`** — v1 records the Maven graph +
  SHA-256 in the lock (audit trail) but does not enforce it via Gradle (needs a
  full-AGP-classpath resolve; see 02 §Gradle pins realized-vs-designed).
- **GitHub Actions KVM emulator CI** — the canary the docs call for; the local
  Windows-host emulator was the validation environment this cycle.
- **Upstream pyjnius PyPI publication** — the spike branch has the PR scaffolding;
  publishing lets `find_links` go quiet.

## Risks

- **The Kivy 2.3.1 Android wheel build (Phase 0) is the largest unknown** —
  Kivy has no upstream Android wheel CI; budget for iteration against the
  kivy-school recipe and record everything. Everything downstream consumes it.
- **The load model is unproven** until Phase 0's prototype runs (the spike used
  p4a's bootstrap); the finder/flatten/unpack design may need adjustment —
  hence prove-first, and the spec is corrected before templates are extracted.
- **Toolchain drift** (AGP/Gradle wrapper/NDK pins) — layer-2 pins move with
  kivyforge releases per 06 §versioning; keep them in one module constant.
- **Windows-host Gradle/emulator quirks** (path length, `gradlew.bat` quoting,
  HAXM/WHPX variance) — surface early because ALL gates run on the Windows
  host by decision; document workarounds in doctor hints as they're found.
