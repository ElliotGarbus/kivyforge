# macOS and iOS validation findings

Validation run against `modernization-rfc` per
[`macos-ios-validation-prompt.md`](macos-ios-validation-prompt.md), on the Mac.
Date: 2026-09-14/15 (session spanned across midnight UTC).

## Environment (Step 0)

| Item | Value |
|------|-------|
| macOS | 26.6.2 (Build 25G83) |
| Xcode | 26.6 (Build 17F113) |
| Swift | Apple Swift 6.3.3 (swiftlang-6.3.3.1.3, clang-2100.1.1.101) |
| Host Python | 3.14.7 |
| pip | 26.2.1 |
| kivyforge | 3.0.0.dev0 (editable install) |
| Developer ID identity | `Developer ID Application: ELLIOT DREW GARBUS (R5PKSQLUZY)` |
| Team ID | `R5PKSQLUZY` |
| Branch | `modernization-rfc` @ `036fb3ff9d7a649e091697943c7441585e9efd11` |

Two commands (`xcrun stapler validate`, `spctl -a -vvv -t exec`) initially
failed inside this session's sandboxed shell with generic "internal error" /
"file does not exist" messages — both are sandbox artifacts (these tools talk
to `syspolicyd`/LaunchServices, which the sandbox blocks) and both passed
cleanly once re-run unsandboxed. Noted because the failure text gives no hint
that it's an environment issue rather than a real one.

## Step 1 — macOS `dice-roller` artifact (already notarized by hand)

The maintainer had, before this session, built, Developer-ID-signed, and
submitted `examples/desktop/dice-roller` for notarization. This step captured
that artifact's evidence.

```
codesign --verify --deep --strict --verbose=2  → "valid on disk", satisfies Designated Requirement
codesign -dvvv                                 → Authority=Developer ID Application: ELLIOT DREW GARBUS (R5PKSQLUZY)
                                                   Runtime Version=26.5.0, Notarization Ticket=stapled
codesign -d --entitlements -                   → allow-unsigned-executable-memory, disable-library-validation
xcrun stapler validate                         → "The validate action worked!"
spctl -a -vvv -t exec                          → accepted, source=Notarized Developer ID
lipo -archs .../dice-roller                    → arm64
```

**`spctl` accepting a stapled build — the strongest single signal this
exercise can produce — passed.** So did `stapler validate`. Both are firsts
for this repo.

### `notarytool history` — a correction to §6/Background

Once a keychain profile was set up (`xcrun notarytool store-credentials`),
history showed **five `Accepted` submissions**, not zero:

| Date (UTC) | Name | Status |
|---|---|---|
| 2026-09-14T23:45:42Z | Dice Roller.zip | Accepted |
| 2026-07-14T03:18:07Z | Dice Roller.zip | Accepted |
| 2026-07-14T03:08:34Z | Dice Roller.zip | Accepted |
| 2026-07-11T21:11:05Z | Dice Roller.zip | Accepted |
| 2026-07-07T02:57:11Z | Dice Roller.zip | Accepted |

**This contradicts both `test-matrix.md` §6 ("Notarization — needs an Apple
ID, app-specific password, and network", unchecked) and this prompt's own
Background section** ("Notarization... on §6's manual checklist as never
attempted"). Notarization has actually succeeded five times since July.
Nobody had looked at `notarytool history` before now — the same shape of
mistake §3.2 already documents twice for iOS (a true capability read as
untried because nobody checked the evidence).

### `pylock.macos.toml` — false alarm, self-corrected

Mid-session this was flagged as "committed, should be untracked" based on
`git ls-files <path> && echo TRACKED || echo not tracked` — but `git ls-files`
exits 0 even with no matches, so the check was always true. `git log
--diff-filter=D` confirmed the file was correctly untracked in `5d4d908c` when
the gitignore policy landed, and `git check-ignore -v` confirms it is
gitignored today. No action was needed; recorded here so the correction is on
the record rather than silently dropped.

## Step 2 — is the macOS payload already stripped? Yes — free win confirmed

| Location | `.py` | `.pyc` | `__pycache__` |
|---|---|---|---|
| `Contents/Resources/app` (app source) | 0 | 1 (`main.pyc`) | 0 |
| `Contents/Resources/lib` (Kivy + third-party deps) | 0 | 335 | 0 |
| `Contents/Resources/python/lib/python3.13` (embedded stdlib) | 1037 | some (framework-shipped) | n/a |

The embedded-stdlib `.py` files are **not** a bug: per
[`macos-x86-removal-and-desktop-stripping.md`](macos-x86-removal-and-desktop-stripping.md)
§"Settled decisions", strip scope is deliberately "app + site-packages only.
stdlib is not stripped" — confirmed by re-reading that doc rather than assumed.

**Magic-number check, against the bundle's own runtime, not the host's:**

```
bundled python3 -V              → Python 3.13.14
bundled MAGIC_NUMBER             → f30d0d0a
host python (NOT compared)      → Python 3.14.7
all 336 shipped .pyc files      → f30d0d0a (single, consistent value)
```

macOS `strip_source` is real, working, and correctly scoped.

## Step 3 — iOS simulator regression check: no drift since July

```
doctor -p ios                    → exit 0 (2 expected WARNs: no final CPython 3.15; no privacy manifest)
build -p ios --simulator         → exit 0
run   -p ios --simulator         → exit 0, launched on iPhone Air / iOS 26.5
screenshot                       → "Hello Kivy" rendered correctly
```

`hello-kivy/pylock.ios.toml` unchanged (working tree clean) — no lock drift
from this regression check alone.

## Step 4 — iOS `strip_source`: still unverified, and now we know precisely why

`package -p ios` (materializing a real copy of `app_dir`, per
[`ios-source-stripping.md`](ios-source-stripping.md)) degraded to shipping
source, verbatim matching `doctor`'s warning:

```
[stage] not byte-compiling app sources: no final CPython 3.15 found (this project ships 3.15.0b4).
```

**Every iOS example in the repo pins `[tool.kivy.ios.python].version =
"3.15.0b4"`** (`hello-kivy`, `hello-world`, `keychain-spm`, `mobile-geometry`,
`pyobjus-ball`, `pyobjus-deviceinfo`, `svg-explorer` — checked all of them).
CPython 3.15 final is not expected until ~Oct 2026. So this is not merely
"never run" — it is **currently unexercisable on any example in this repo**
until either 3.15 ships or an example is deliberately pinned to an
already-final minor.

**The one thing that matters most here — data safety — passed.**
`hello-kivy-ios/app` was materialized as a **real directory copy**, not a
symlink (confirmed via `[ -L ... ]`), and `git status`/mtime on
`examples/mobile/hello-kivy/src/main.py` showed **zero changes** to the real
working tree. The hazard the design doc warns about did not occur.

## Step 5 — macOS T3 artifact assertions (new; Android's shape, mirrored)

Added, hermetic-first:

- `kivyforge/platforms/macos/machotools.py` — `read_macho_cpu_type()`,
  `cpu_type_name()`, `CPU_TYPE_ARM64`/`CPU_TYPE_X86_64` (pure, no `lipo`
  subprocess — needed so the hermetic suite runs on non-macOS CI hosts too).
- `tests/artifact_checks.py` — `macos_app_problems()` + helpers: required
  entries, Mach-O arch (flags any binary not matching the build's arch),
  payload stripping (scoped to `app/`+`lib/` only, per Step 2's finding —
  explicitly *not* the stdlib), `.pyc` magic, `Info.plist` structural +
  optional exact-match checks.
- `tests/test_artifact_checks.py` — 44 hermetic tests (Android + macOS) against
  synthetic `.app` trees.
- `tests/conftest.py` — `--macos-app`, `--macos-arch`, `--macos-stripped`.
- `tests/platforms/macos/test_app_artifact.py` — the thin driver, plus a
  `codesign_verify` check (test-matrix.md §5.1's "signatures verify" item, macOS
  half). Derives expected `.pyc` magic by **running the bundle's own
  `python3`**, not the test runner's.

**Ran against the real, notarized `Dice Roller.app` from Step 1 — both tests
pass.** Full hermetic suite (unfiltered `pytest`, matching the `unit_tests` CI
job exactly): exit 0, coverage 91.96% (≥80% required). Lint clean.

## Step 6 — device validation: real hardware, and a real bug found+fixed

An iPhone (`iPhone14,3`, "Elliot's iPhone") was connected mid-session.
`examples/verify-ios-device.sh` had never had a logged run (§3.2/§6); this
step ran the actual on-device path by hand.

### Bug found: `--team-id` / `KIVYFORGE_TEAM_ID` never reached the built project

`kivyforge doctor -p ios` passed and `--list-devices` saw the phone
immediately. But `build -p ios --device` (and, earlier, `package -p ios
--team-id ...`) both failed:

```
error: Signing for "hello-kivy" requires a development team.
```

...**even with `KIVYFORGE_TEAM_ID=R5PKSQLUZY` exported**, which
`preflight_signing()` correctly resolves and validates (the error message
never fires) — but `signing_settings()`, which writes the generated
`.xcodeproj`'s `DEVELOPMENT_TEAM` build setting, read **only**
`config.ios.signing.team_id` (i.e., `pyproject.toml`) and had no path to
receive the resolved override at all. So `--team-id`/`KIVYFORGE_TEAM_ID`
silently satisfied the preflight check while having *zero effect* on whether
the actual build could succeed — functional only if `team_id` happened to
already be hardcoded in `pyproject.toml`.

**Fixed** by threading the already-resolved team_id through the existing call
chain (`ios_build`/`ios_run`/`ios_package` → `prepare_build` →
`materialize_project` → `XcodeProjectGenerator` → `signing_settings()`), so the
flag/env-resolved value — not just the pyproject default — reaches the
project Xcode actually builds. Two regression tests added
(`test_signing_settings_team_id_override`,
`test_signing_settings_no_override_keeps_pyproject_value`); full iOS suite
(494 tests) + lint pass after the fix.

This also resolves Step 4's archive failure retroactively — that failure was
the same bug, hit from the `package` path.

**Note deliberately not committed:** `hello-kivy/pyproject.toml`'s
`team_id` was **not** hardcoded to the maintainer's personal team ID, since
other users of this shared example would need their own. Signing used
`KIVYFORGE_TEAM_ID` for this session only; `pyproject.toml` is unchanged from
`HEAD`.

### Result, after the fix

```
build -p ios --device                        → exit 0
run   -p ios --device                          → installed; first launch attempt correctly
                                                  failed on a locked screen (the documented
                                                  gotcha), succeeded after unlock
package -p ios --export-method development     → exit 0, hello-kivy.ipa exported (95.6 MB,
                                                  app/main.py present — matches Step 4's
                                                  unstripped finding)
```

**Visual confirmation: "Hello Kivy" rendering on the physical iPhone** — the
first physical-iOS-device run in this repo's history. `examples/verify-ios-
device.sh`'s pre-flight checklist (Apple ID in Xcode, device paired, unlocked
at launch) was followed live and each item's failure mode was reproduced
exactly as the script's own comments describe.

`hello-kivy/pylock.ios.toml` was re-locked and **kept** (not restored) — it
is one of the three on-device-gate example locks
([`common/03-lockfile-concept.md`](../common/03-lockfile-concept.md)
§"Example-repo lock policy"), so recording the exact Kivy build
(`3.0.0.dev202607301604`, up from `dev202606221936`) that passed *this*
validated device run is the intended use of a committed lock, not drift to
suppress.

## Conclusions

1. **macOS as a target is no longer the empty half.** A real, Developer-ID
   signed, notarized, stapled `.app` exists and now has T3 artifact assertions
   behind it — ahead of Windows and Linux, which still have no CI build job at
   all.
2. **Notarization has succeeded five times since July**, not zero — §6 and
   this prompt's Background were both stale on this point specifically because
   nobody had run `notarytool history` before.
3. **macOS `strip_source` is real and correctly scoped** — accurate about
   *scope*, and not retracted. What this run's static checks (`codesign`,
   `stapler`, `spctl`, `lipo`, `macos_app_problems`) could not answer, and
   didn't claim to, was whether the correctly stripped bundle actually
   *starts*. It didn't: a Linux (WSL2) agent inferred from this file's own
   Step 2 table that the macOS launcher execs an absolute `main.py` path
   `strip_source` had just deleted — the identical defect independently found
   and fixed on Linux's `AppRun` on 2026-09-13 — and queued the fix as
   [`macos-launcher-strip-source-prompt.md`](macos-launcher-strip-source-prompt.md).
   Run on 2026-09-14: confirmed verbatim (exit 2, `can't open file
   '.../app/main.py'`), fixed (`execv`s `python3 -P -m <entry>`), and this time
   actually launched — rendering, visually confirmed, for the first time in
   this repo's history. That launch immediately surfaced a second, previously
   unreachable defect: importing the deliberately-unstripped embedded stdlib
   wrote `__pycache__` into the signed bundle, invalidating its own code
   signature. Fixed with `PYTHONDONTWRITEBYTECODE=1` in the same launcher.
   **The corollary from `test-matrix.md`'s Known-unverified list stands as the
   sharpest lesson of this whole exercise: a signed, notarized, T3-passing
   artifact was not, in fact, evidence it could start.** iOS `strip_source` is
   not just unproven but currently *unprovable* on any example in this repo
   until a final CPython 3.15 exists.
4. **The materialize-a-real-copy safety mechanism for iOS release builds works
   as designed** — no source was ever at risk.
5. **iOS now has a real, logged device run** — build, install, launch, and a
   signed `.ipa` export, all against physical hardware — which surfaces and
   fixes a genuine bug (`--team-id`/`KIVYFORGE_TEAM_ID` not reaching the
   generated Xcode project) that no simulator-only testing could have found,
   since the simulator path never signs at all.
6. Two self-corrected false alarms are recorded above in the interest of
   accuracy over narrative — this file follows the same "read the evidence"
   discipline `test-matrix.md` asks of itself.
