# Android backend retrospective + carry-forward

**Scope.** A post-implementation retrospective on building the Android backend
(wheel-assembly model: python.org Android runtime + per-ABI `android_*` wheels,
kivyforge-owned SDL bootstrap, generated Gradle/AGP project, signed `.apk` /
`.aab`, `doctor`, on-device contract smoke). The goal is to capture what
surprised us, what we would do differently, and — most usefully — to translate
each lesson into a **carry-forward checklist** for the next piece of work
(publishing first-party wheels to PyPI, keeping the Android contract honest as
AGP/NDK drift, and any future platform backend).

This is a developer note, not a spec. For *what* the Android backend does, see
the [platforms/android](../platforms/android/01-pyproject-android.md) design
set; for the Phase-0 evidence trail, see
[android-wheels-findings](android-wheels-findings.md),
[pyjnius-android-wheel-spike-findings](pyjnius-android-wheel-spike-findings.md),
and [android-loadmodel-findings](android-loadmodel-findings.md). The Windows
retrospective that seeded Android's pre-flight checklist is
[windows-backend-retrospective](windows-backend-retrospective.md).

---

## TL;DR

- The **architectural bet was right**: assemble prebuilt wheels + a python.org
  runtime into a Gradle project; never compile Python or the Kivy stack on the
  build host. The pyjnius-wheel spike and the load-model prototype were the
  correct phase gates — without them the backend would have been another
  recipe-driven p4a.
- Almost every *runtime* surprise was a **silent-failure class** unique to
  Android (SDL C/Java mismatch black screen, AAPT dropping `_python_bundle`,
  entry-point module imported with the wrong `__name__`, Kivy autoclassing
  `org.renpy.android.Hardware`). The recurring theme: **"it launched" ≠ "it
  ran," and Android often leaves no traceback.**
- The biggest *process* surprise was not Android itself: a late code+docs
  review found **21 findings** because the implementation had drifted from its
  published contract (CLI flags documented but unreachable, settings accepted
  but inert, policy checked the wrong manifest). The design docs were strong;
  the acceptance criteria for "v1 complete" were not.
- The Windows carry-forward checklist largely paid off (toolchain pins, ELF
  ABI checks, 16 KB alignment, signing/`doctor`). What it did *not* cover —
  and what Android taught us — is **docs/CLI/behavior lockstep**, **merged
  vs. source manifests**, and **silent on-device failure modes**.

---

## What went well (keep doing this)

- **Spike before commit.** The pyjnius Android-wheel spike
  ([brief](pyjnius-android-wheel-spike.md) →
  [findings](pyjnius-android-wheel-spike-findings.md)) answered the one
  blocking unknown — *can pyjnius be a self-contained, SDL-agnostic wheel?* —
  before the backend was written. The load-model prototype
  ([findings](android-loadmodel-findings.md)) then proved *kivyforge's*
  bootstrap, not p4a's. Both converted existential risk into a known contract.
- **Wheel-assembly model held.** No per-app C compilation of the Kivy stack;
  first-party cibuildwheel builds (Kivy + pyjnius, 16 KB-aligned) from
  [`kivy-mobile-wheels`](https://github.com/ElliotGarbus/kivy-mobile-wheels)
  until PyPI. Same shape as desktop/iOS: lock → fetch → stage → native
  toolchain.
- **Matched-pair contracts as hard gates.** `invoke0` (bootstrap Java ↔
  pyjnius wheel) and SDL glue ↔ `libSDL*.so` are checked at build time
  (`bootstrap/contract.py`) and content-synced in CI
  (`scripts/check_sdl_glue_sync.py`). The silent black-screen failure that
  motivated them would have been undiagnosable in the field.
- **`doctor` as a first-class surface.** Environment (JDK/SDK/NDK/licenses/
  adb/devices), project health (icons, splash, include_files, manifest
  policy, implied features, 16 KB alignment, SDL/Kivy pairing), and lock-host
  reachability repeatedly turned "mysterious Gradle/device failure" into an
  actionable message before the user wasted a build.
- **Honest compatibility matrix.** [08](../platforms/android/08-compatibility-matrix.md)
  distinguishes Validated (emulator *and* hardware, cited) from Prototype /
  Pending, and names revalidation triggers. Both SDL2 and SDL3 rows are
  Validated on an x86_64 API-31 emulator and a Pixel 8a (API 36).
- **Design docs written before/with the code**, then corrected when the
  prototype proved the Activity owns unpack (not `libmain`), stock SDL glue
  is mandatory, and AAPT's `ignoreAssetsPattern` must be overridden. The
  findings docs made this retrospective cheap.
- **Windows carry-forward applied.** Toolchain pins in `toolchain.py`, ELF
  machine/alignment checks in `elf.py`, mandatory signing with env-sourced
  passwords, atomic-ish artifact paths, and a Gradle-only CI gate without
  pretending hosted CI replaces on-device smoke.

---

## Biggest surprises

Each is written as: **what bit us → root cause → the fix → the transferable
lesson.**

### 1. SDL C/Java version mismatch → silent black screen (the worst class)

- **What bit us.** After swapping the first-party Kivy wheel (SDL 2.32.10)
  against bootstrap templates still holding 2.30.11 Java glue, the app
  launched, unpacked, reached `RESUMED`, and then did nothing: no Python, no
  `SDL_main`, no traceback, empty logcat, black screen.
- **Root cause.** Stock `SDLActivity.onCreate` compares
  `nativeGetVersion()` to its compiled-in constants; on mismatch it sets
  `mBrokenLibraries` and **returns before creating the surface**, writing
  nothing useful to logcat. `SDL_main` — kivyforge's entire launcher — never
  runs.
- **The fix.** Vendor the stock `org.libsdl.app` glue from the *same* SDL
  release tarball as the wheel's `libSDL*.so`; hard-fail at build
  (`check_sdl_glue_contract`); CI byte-diff against `kivy-mobile-wheels`
  (`check_sdl_glue_sync.py`). Both SDL2 and SDL3 are gated.
- **Lesson.** **Any failure mode that leaves no logcat is a hard build gate,
  not a doctor WARN.** Prefer "refuse to ship" over "hope the user notices a
  black screen."

### 2. AAPT silently drops `assets/_python_bundle`

- **What bit us.** The APK could ship without the Python asset bundle; the
  app then failed at unpack with a cryptic missing-assets path.
- **Root cause.** AGP's default `ignoreAssetsPattern` excludes asset
  directories starting with `_`. The name `_python_bundle` matched it.
- **The fix.** Generated `aaptOptions.ignoreAssetsPattern` overrides the
  default (or the bundle must not start with `_`). Documented in the load-
  model findings and the Gradle generation doc.
- **Lesson.** **Platform defaults that silently drop payload are worse than
  hard errors.** Anything the build stages into assets must be verified in
  the packaged APK (CI unzip assert on `assets/_python_bundle/` is the right
  shape).

### 3. Published contract drifted from implementation (21 findings)

- **What bit us.** A code+docs review after "v1 complete" found blockers:
  configured `entry_point` ignored (hardcoded `import main`); documented
  `build --debug`/`--abi` and `package` signing overrides unreachable from
  the public CLI; services named in the manifest with no Java classes;
  custom icon removed `@mipmap/ic_launcher` (AAPT failure); Maven repos
  resolved at lock then omitted from Gradle; SDL3 bypassed the glue check;
  release smoke had no real release variant; plus inert settings
  (`multidex`, `byte_compile`, `strip_source`, `splash`), unverified
  `include_files` hashes, source-manifest-only policy, no Gradle CI gate,
  and stale README/status claims.
- **Root cause.** Features and docs were written to a design contract;
  implementation landed in slices; "done" was judged by unit tests and
  on-device smoke of the happy path, not by **diffing behavior against every
  documented surface**.
- **The fix.** Implement the contract rather than trim it (services +
  `PythonBundle`, icons, Maven repos, SDL3 gate, release smoke, multidex/
  byte_compile/splash, include_files drift, merged-manifest + `lintRelease`
  + `allow_exported`, Gradle CI job, the eight missing doctor checks, the
  six missing CLI behaviors, docs honesty pass).
- **Lesson.** **"Green tests + on-device smoke" is not "matches the published
  contract."** Treat every documented CLI flag, config key, and doctor row as
  an acceptance criterion; run a contract audit before flipping status
  banners. Prefer implementing over quietly narrowing the docs.

### 4. Manifest policy must see the *merged* release manifest

- **What bit us.** Policy initially linted the manifest kivyforge generated.
  Library `.aar` manifests (and our own hardcoded Material Components
  dependency) contribute components AGP merges in. CI's first real
  `package` path then failed on
  `androidx.profileinstaller.ProfileInstallReceiver` — exported by AndroidX
  by design, gated by `DUMP`, present in *every* generated project.
- **Root cause.** Source manifest ≠ packaged manifest. Escape hatches that
  only edit pyproject.toml cannot remove library-contributed components.
- **The fix.** Two-pass policy: generated manifest (fail before Gradle), then
  AGP `SingleArtifact.MERGED_MANIFEST` export + curated `lintRelease`
  subset; `[manifest].allow_exported` for user-chosen deps; bake our own
  transitive baseline (`ProfileInstallReceiver`) into `BOOTSTRAP_EXPORTED`.
- **Lesson.** **When a toolchain merges manifests, policy the merge output.**
  Anything *we* always pull in belongs in the tool's baseline allowlist, not
  in every user's `pyproject.toml`.

### 5. Namespace preservation was incomplete for Kivy itself

- **What bit us.** First-party `kivyforge run` reached Kivy import and then
  failed: `autoclass('org.renpy.android.Hardware')` and
  `PythonActivity.mActivity` were missing — surfaces the load-model prototype
  never exercised because its Kivy probe was narrower.
- **Root cause.** Design preserved `org.kivy.android.*` for app code; Kivy's
  own Python still autoclasses the *legacy* `org.renpy.android.Hardware` and
  the `mActivity` static.
- **The fix.** Vendor p4a's MIT `Hardware.java`; expose
  `public static PythonActivity mActivity`. Diff-clean + compat tests.
- **Lesson.** **Satisfy every Java class the framework autoclasses, not only
  the ones app authors call.** Framework startup paths are part of the
  bootstrap contract.

### 6. Entry point is imported, not run as `__main__` — and was ignored

- **What bit us.** (a) Apps ported from buildozer/p4a with
  `if __name__ == "__main__": App().run()` imported cleanly and never started
  — no error. (b) Independently, the launcher hardcoded `import main` and
  ignored `[tool.kivy].entry_point` until the review found it.
- **Root cause.** Common bootstrap contract is *import* the entry module
  (`__name__` ≠ `"__main__"`). Buildozer runs as `__main__`. Separately, the
  template never wired the configured name.
- **The fix.** Honor `entry_point` in Java/`main.c` via `KF_ENTRY_POINT`;
  document the no-guard requirement in examples/`init`; catch (a) with
  example gates that assert app markers in logcat.
- **Lesson.** **Migration traps from the predecessor toolchain must be
  explicit in `init` and examples.** And config that the launcher reads must
  be substitution-tested, not assumed.

### 7. Stock SDL glue vs. p4a's patched glue

- **What bit us.** Early prototypes using p4a's `SDLActivity` never started
  the SDLMain thread — p4a omits `loadLibraries()` / surface setup from
  `onCreate` because it does that in its own activity after unpack.
- **Root cause.** p4a's glue is not a drop-in for a bootstrap that *is* the
  SDL activity.
- **The fix.** Vendor stock `org.libsdl.app` from the SDL release; treat p4a
  as historical reference only.
- **Lesson.** **Vendoring a predecessor's patch set is not compatibility —
  match the load model you actually run.**

### 8. Host Python ≠ target Python for `byte_compile`

- **What bit us.** Enabling `byte_compile` on a project shipping CPython 3.14
  while kivyforge ran on 3.13 failed (wrong `.pyc` magic) or was documented
  as if the host interpreter were enough.
- **Root cause.** `.pyc` format is interpreter-version-specific; Android's
  runtime is not the host's.
- **The fix.** Discover an interpreter whose version matches the locked
  Android Python (or warn and ship source); deterministic `stripdir` for
  reproducible stamps; CI pins Python 3.14 so the release path exercises
  `.pyc`.
- **Lesson.** **Any host-side transform of target bytecode must use the
  target's own interpreter.** Document discovery, not "run compileall."

### 9. Hosted CI cannot replace on-device smoke — but must still compile

- **What bit us.** Claiming "complete" without a real Gradle assemble left
  generated Groovy/CMake/Java unconsumed by AGP. Adding `android_gradle`
  then hit Node-20 action deprecations and the ProfileInstallReceiver policy
  miss on first run.
- **Root cause.** Unit tests assert strings; only AGP proves the project.
  Emulators in hosted CI are expensive and flaky; we chose Gradle-only
  deliberately — then had to own the first-run fallout of that gate.
- **The fix.** `android_gradle` job: `assembleDebug`, APK content asserts,
  throwaway-keystore `package` (lintRelease + merged manifest). On-device
  `run --smoke` stays a local/Validated-matrix gate. Bump Actions off Node
  20.
- **Lesson.** **Split hermetic compile gates from live device gates; run the
  compile gate in CI from day one; never mark a matrix row Validated without
  a cited device run.**

### 10. Small Android papercuts that cost real time

- **AGP auto-decompresses `.gz` assets** — rename-dance or exclude; decide
  explicitly in the stager.
- **`PyConfig.use_system_logger` missing on the 3.14 Android build** —
  logcat redirection is automatic; blank lines after prints are newline
  splits.
- **Logcat ring-buffer races** — assert on the dump captured *during*
  `run`, not a second independent `logcat -d`.
- **Deprecated APIs in vendored Java** (`Hardware`, SDL glue) — suppress
  only what we own; SDL glue stays byte-identical to upstream (sync CI).
- **Material Components as a hardcoded dependency** pulls ProfileInstaller
  — own the transitive baseline in policy.

---

## Windows carry-forward: scorecard

How the [Windows retrospective's Android checklist](windows-backend-retrospective.md#carry-forward-for-the-android-backend)
actually landed:

| Pre-empt item | Outcome |
|---|---|
| Gradle / AGP / build-tools / NDK pin + re-pin path | **Done** — `toolchain.py` pins; bump is a deliberate PR. No automated re-vendor job (unlike MSVC launcher); AGP/NDK bumps are still manual. |
| Bundle Python + `.so`; validate ABI | **Done** — runtime stage + `elf.py` machine / 16 KB checks; doctor FAILs misaligned libs. |
| ABI matrix + ELF `e_machine` | **Done** — `arm64_v8a` + `x86_64` only (64-bit); validated on device + emulator. |
| APK/AAB signing mandatory + doctor | **Done** — signing config, env passwords, v1–v4, prerequisites doc. |
| Atomic stage-then-swap for outputs | **Partial** — Gradle owns most output paths; we don't replace a previous good APK mid-failure the way `fsswap` does. Lower risk on Linux CI hosts. |
| Explicit UTF-8 at tool boundaries | **Mostly** — less painful than Windows; Gradle/adb still need care. |
| `.so` load order / 16 KB / extractNativeLibs mindset | **Done** — matched-pair gates + alignment scanner. |
| Explicit entry / `__main__` contract | **Done late** — import contract documented; `entry_point` wiring was a review catch. |
| Service lifecycle policy | **Done late** — `PythonService` + subclasses + smoke; arrived with the contract audit. |
| Clean emulator / device phase gate | **Done** — Validated rows cite both; not in hosted CI. |
| Assert smoke actually ran (no silent skip) | **Partial** — local `--smoke` is real; CI deliberately has no emulator, so Validated ≠ "CI green." |
| Pin tool locations (`sdkmanager`, `adb`) | **Done** — doctor + explicit resolution. |

**Android-specific items the Windows note called out:** two formats (apk/aab)
scoped correctly; manifest surface was budgeted but policy on the *merged*
manifest arrived late; SDK licenses are a doctor check; hermetic-vs-live split
matches the intent (Gradle CI + manual/device Validated).

---

## What we'd do differently next time

1. **Define "v1 complete" as a contract checklist**, not a feeling: every
   documented CLI flag, config key, doctor row, and status banner claim maps
   to a test or a cited on-device run. Run that checklist *before* flipping
   Status banners and README.
2. **Keep a living "silent failure" register** for the platform (black
   screens, dropped assets, import-without-run) and require a hard gate or an
   example marker for each entry.
3. **Stand up the compile-only CI gate in the same PR as project
   generation**, even if device smoke stays local — generated Gradle is not
   tested until AGP consumes it.
4. **Policy the merged artifact whenever the native toolchain merges**
   (manifests, resources, native libs). Source-only checks are necessary but
   not sufficient.
5. **Bake first-party transitive allowlists** when the generator hardcodes a
   Maven coordinate (Material → ProfileInstaller).
6. **Exercise framework startup on-device early** (full Kivy `App().run()`,
   not only `import kivy`), so legacy autoclass shims surface before
   "Phase 5."
7. **Wire every template substitution (`entry_point`, package, ABI) through
   a render test** that fails if the placeholder survives.
8. **For vendored third-party Java (SDL), never local-patch** without
   updating the sync peer; for *our* shims (`Hardware`), document intentional
   deprecations with `@SuppressWarnings`.

---

## Carry-forward (next work)

Android v1 is implemented and on-device Validated. The open frontier is
distribution, drift, and process — not another bootstrap redesign.

| Next concern | Pre-empt |
|---|---|
| **Publish Kivy / pyjnius Android wheels to PyPI** | Keep `kivy-mobile-wheels` as the interim index; when publishing, re-run the Validated matrix and the SDL glue sync against the PyPI artifacts; update example locks and docs in the same PR. |
| **AGP / NDK / compileSdk drift** | Treat `toolchain.py` bumps like the Windows MSVC re-vendor: one PR, regenerate example projects, run `android_gradle` + local `--smoke` on both SDL generations. |
| **Play `target_sdk` deadlines** | [08](../platforms/android/08-compatibility-matrix.md) already tracks them; bump defaults before Play rejects uploads, not after. |
| **Emulator in hosted CI (optional)** | Only if Validated regressions keep escaping Gradle-only CI. Prefer a scheduled workflow over every-PR cost; never skip silently — fail if the AVD didn't boot. |
| **Docs/CLI/behavior lockstep** | Any new Android config key or CLI flag ships with: loader validation, a unit test, a doctor row *or* an explicit "not a doctor check" note, and a docs update in the same PR. |
| **Predecessor migration (`buildozer.spec`)** | `init` already detects and maps; keep the map honest as buildozer keys evolve; never claim automatic conversion. |
| **Future platforms / large backends** | Reuse this retrospective's process lessons (contract checklist, silent-failure register, compile CI from day one) the way Android reused Windows' host-reality checklist. |

---

## Pointers (where the lessons live in code)

- Matched-pair gates: `platforms/android/bootstrap/contract.py`,
  `scripts/check_sdl_glue_sync.py`.
- Bootstrap templates: `platforms/android/bootstrap/templates/`
  (`PythonActivity`, `PythonService`, `PythonBundle`, `Hardware`,
  `sdl2/`/`sdl3/` glue, `cpp/main.c`).
- Staging + byte_compile: `platforms/android/stage/bundle.py`,
  `stage/jnilibs.py`, `elf.py`.
- Manifest policy + Lint subset: `platforms/android/policy.py`,
  `generate/project.py` (`lint {}`, merged-manifest export task).
- CLI orchestration: `platforms/android/cli.py`, public flags in
  `cli/build.py` / `package.py` / `run.py` / `clean.py` / `upgrade.py` /
  `init.py`.
- Doctor: `platforms/android/doctor.py`.
- CI compile gate: `android_gradle` job in `.github/workflows/kivyforge.yml`.
- On-device evidence:
  [android-loadmodel-findings](android-loadmodel-findings.md),
  [08-compatibility-matrix](../platforms/android/08-compatibility-matrix.md).
- Prior carry-forward that seeded this backend:
  [windows-backend-retrospective](windows-backend-retrospective.md).
