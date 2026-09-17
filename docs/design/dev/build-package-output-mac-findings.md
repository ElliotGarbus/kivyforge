# `build`/`package` output on the Mac — findings

Validation run against `modernization-rfc` @ `5eb28e07` per
[`build-package-output-mac-prompt.md`](build-package-output-mac-prompt.md).
Date: 2026-09-16/17.

Fifth in the cross-host chain that began with
[`macos-ios-validation-prompt.md`](macos-ios-validation-prompt.md). One real
defect found and fixed (Step 4); everything else the four commits changed
behaved exactly as designed, including the highest-risk item (Step 2).

## Environment

| Item | Value |
|------|-------|
| Host | macOS 26.6.2 (`25G83`) |
| Xcode | 26.6 (build 17F113) |
| Host Python | 3.14.7 |
| kivyforge | 3.0.0.dev0 (editable install) |
| Examples | `examples/desktop/dice-roller`, `examples/mobile/hello-kivy` |
| Signing identities available | `Developer ID Application: ELLIOT DREW GARBUS (R5PKSQLUZY)`, `Apple Development: ELLIOT DREW GARBUS (X83FAZ586W)` — **no distribution cert**, so Step 3d used `--export-method development` (the same combination the 2026-09-14 device run used), not `app-store`/`ad-hoc` |
| Android SDK | not installed on this Mac — Step 5 skipped |

## Step 0 — environment and the suite

`git pull` landed `5eb28e07`, well past the required `89798096`. Full suite:
**green**, 92.68% coverage — this is the first real run of
`tests/cli/test_build.py`, `test_package.py`, and `test_build_run_open.py`
against the Step 1–4 changes (they are `requires_symlinks` and skip on
Windows, where all four commits were authored).

`pyright kivyforge` is **not 0 errors** here, but not for a reason related to
today's changes: it was never installed (`pip show pyright` → not found, and
it is absent from `[dev]` extras and every CI workflow), so this Mac had
apparently never run it before. Installed it ad hoc; it reports 3 errors, all
`winreg.OpenKey`/`HKEY_LOCAL_MACHINE`/`QueryValueEx` "not a known attribute"
in `doctor/probe.py`'s Windows-only `long_paths_enabled()`. `pyrightconfig.json`
does not pin `pythonPlatform`, so pyright infers it from the host — on macOS
that narrows `winreg`'s typeshed stub to nothing, exactly as `if sys.platform
== "win32"`-guarded code would. Not a regression, not fixed here: `pyright`
isn't part of CI or `[dev]`, so nothing currently depends on this passing on a
Mac. Worth a `pyrightconfig.json` follow-up (`"pythonPlatform": "All"` or
similar) but out of scope for this prompt.

## Step 1 — macOS, human mode then `--json`

`kivyforge build -p macos` on `dice-roller`: stdout is exactly `Built
build/macos/Dice Roller.app`; stderr carries staging/signing progress. Piped
through `cat`, byte-checked for `0x1b` — no escape codes. `--json` parses to
one document with `ok: true` and `data.artifacts == [{"path": "build/macos/Dice
Roller.app", "kind": "app"}]`, matching the prompt's assertion exactly.

`package -p macos --json` was more informative than the prompt expected:
`dice-roller/pyproject.toml` already has `[tool.kivy.macos.signing]` fully
configured (Developer ID identity, team, `kivyforge-notary` profile) from the
2026-09-14 validation run, so the "no identity" default path is not actually
reachable on this checkout without deliberately clearing it. Ran both halves:

- **With the identity** (the checked-in default): one `app` artifact, real
  Developer ID signing, real notarization (`Notarization accepted`), stapling
  — all on stderr, `ok: true`, no `KF-SIGNING-UNCONFIGURED`. Confirms the inner
  `build` is never double-recorded.
- **Without an identity**: temporarily blanked
  `[tool.kivy.macos.signing]` to `schema_version = 1` only. Editing
  `pyproject.toml` changes its hash, so `pylock.macos.toml` (gitignored for
  this example) needed `kivyforge lock -p macos --update` to stay in sync —
  used that instead of `--no-verify-lock`, since the lock file costs nothing
  to regenerate and isn't committed anyway. Result: one `app` artifact,
  `KF-SIGNING-UNCONFIGURED` warning present, `ok: true`, exit `0` — exactly
  per spec. `pyproject.toml` and the lock were restored to their original
  contents afterward; `git status` on the example directory is clean.

No `KF-BYTECOMPILE-NO-INTERP` on macOS `dice-roller` — CPython 3.13.14 is
final, so byte-compiling actually ran (visible in stderr as `[stage]
byte-compiling the Python payload with .../python3 (.pyc only)`).

## Step 2 — iOS simulator: the DerivedData change

**The highest-risk item in the set, and it works.** With
`hello-kivy-ios/build/DerivedData` removed first:

```
Generated hello-kivy-ios
Built hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/hello-kivy.app
```

`ls -d hello-kivy-ios/build/DerivedData/Build/Products/*/*.app` confirms the
`.app` really is there. `--json` re-run: `data.artifacts` is `project` then
`app`, in that order, path identical to the human line. No
`KF-ARTIFACT-MISSING` anywhere in this run.

`run -p ios --simulator --no-build` found the same `.app` and launched it
(`Installing on simulator iPhone Air ... Launching org.kivy.hello-kivy ...`);
`run` blocks on `simctl launch --console-pty` to stream logs, which is out of
scope for this change and not a defect, per the prompt. `status -p ios --json`
agrees: the simulator artifact reads `"built": true` at that exact path, the
device artifact `"built": false`.

## Step 3 — iOS failure classification

**a. Tool fails** (`build -p ios --device --signing-identity "No Such
Identity"`): first hit missing `team_id` — `KF-ERROR`, exit `1`, exactly the
signing-preflight case the prompt anticipated. Retried with
`KIVYFORGE_TEAM_ID=R5PKSQLUZY`: exit `5`, `KF-BUILD-TOOL-FAILED`, `context =
{"tool": "xcodebuild", "task": "build"}`, message one line (`xcodebuild build
failed (exit 65); its output is above.`). The 70-line `xcodebuild` transcript
is in `/tmp/kf.err`, not the diagnostic message. `artifacts` still names
`project` even on failure, per the "a build that fails after generating the
project still names the project" contract.

**b. Tool missing** (`PATH=.venv/bin` only, `build -p ios --simulator`): exit
`3`, `KF-TOOLCHAIN-MISSING`, `context.tool == "xcodebuild"`, structured
envelope — no traceback. Confirms the fix the prompt called out: "before today
this was a Python traceback with nothing on stdout."

**c. Lock drift**: appended `# drift` to `hello-kivy/pyproject.toml`, ran
`build -p ios --json` → exit `4`, `KF-LOCK-DRIFT`. Restored the file
immediately after; `git status` on the example directory is clean.

**d. `--release` / `package -p ios`**: no distribution identity on this Mac,
so used `--export-method development` with `KIVYFORGE_TEAM_ID` — the same
combination that worked in the 2026-09-14 device-validation run.
`build -p ios --release --export-method development --json`: `ok: true`,
`artifacts` is `project` then `ipa` at `hello-kivy-ios/build/hello-kivy.ipa`,
plus two `KF-BYTECOMPILE-NO-INTERP` warnings (`app-sources`, `pip-deps` — the
project still pins pre-release CPython 3.15.0b4, per the known, structural
2026-09-14 finding), `ok: true` throughout, matching the documented
"`byte_compile = "release"`, no compatible interpreter → warning, exit 0" row.
`package -p ios --export-method development --json`: `artifacts` is `ipa`
alone — no `project` — exactly per spec.

## Step 4 — macOS spawn handling: **one real defect, found and fixed**

```
cd examples/desktop/dice-roller
env PATH="$PWD/../../../.venv/bin" kivyforge build -p macos --json
```

Expected `KF-TOOLCHAIN-MISSING`/exit `3` on the first missing tool
(`clang`/`codesign`, per the prompt). Got a structured envelope — no
traceback, so the headline requirement held — but the wrong classification:

```json
{"code": "KF-ERROR", "diagnostics": [{"message": "required macOS tool 'sips' not found (ships with macOS)."}]}
```

exit `1`, not `3`. `sips` is hit before `clang`/`codesign`, generating the
`.icns` while staging the icon. The four commits widened
`codesign`/`otool`/`clang`/`notarytool` from `FileNotFoundError` to `OSError`
handling (per the prompt's own background section) but never touched
`platforms/macos/icns.py`, which predates that work: it pre-checks
`shutil.which(cmd[0]) is None` and raises a bare `AppBundleError` with no
`code`/`exit_code`, which defaults to `ClassifiedError`'s `KF-ERROR`/`1` — it
never reaches `spawn_failure()` at all. Confirmed this is macOS-specific:
Linux's and Windows' icon generators (`platforms/{linux,windows}/icons.py`)
use Pillow in-process, so they have no external-tool spawn site to get this
wrong; only macOS spawns real subprocesses (`sips`, `iconutil`) for icons.

**Fixed**: `icns.py`'s `_run` now attempts the spawn and catches `OSError`
directly, classifying through `spawn_failure(cmd[0], exc)` — the exact
pattern `machotools.py`/`notarize.py`/`launcher.py` already use — instead of
pre-checking with `shutil.which`. Re-ran the same repro: `exit=3`,
`KF-TOOLCHAIN-MISSING`, `context: {"tool": "sips"}`. Added
`test_run_unusable_tool_is_toolchain_unusable` alongside the updated
`test_run_missing_tool_is_toolchain_missing` (now asserting `.code`/
`.exit_code`/`.context`, not just the message) in
`tests/platforms/macos/test_icns.py`. Full suite green (92.70%), `ruff check`
and `ruff format --check` both clean, and a normal `kivyforge build -p macos`
(full `PATH`) still succeeds after the change.

## Step 5 — Android from the Mac

`kivyforge doctor -p android` is red on this Mac (`ANDROID_HOME` unset, no SDK
at the conventional location) — **skipped**, per the prompt.

## Conclusions

1. **The highest-risk change (Step 2, iOS simulator DerivedData) works
   exactly as designed.** `build`, `run`, and `status` all agree on where the
   simulator `.app` lands; no `KF-ARTIFACT-MISSING` anywhere in this run.
2. **All four failure-classification paths (Step 3a–d) matched spec exactly**
   once each precondition (`team_id`, a real `PATH`, an unmodified
   `pyproject.toml`, a usable export method) was met — including the
   `--release`/`package -p ios` artifact-list distinction (`project`+`ipa` vs.
   `ipa` alone).
3. **One real defect, in `icns.py`, not the four commits under test.** A
   missing `sips`/`iconutil` classified as `KF-ERROR`/exit `1` instead of
   `KF-TOOLCHAIN-MISSING`/exit `3`, because macOS icon generation predates
   this work and was never migrated to `spawn_failure()`. Fixed and tested;
   no other platform's icon path has an equivalent gap (Linux/Windows use
   Pillow in-process, not a subprocess).
4. **`pyright` has apparently never run on this Mac.** It reports 3 errors
   that are a `pyrightconfig.json` platform-inference artifact
   (`winreg` on a non-Windows `pythonPlatform`), not a code defect — and
   nothing currently enforces it here, since it's absent from CI and
   `[dev]`. Left as-is; noted for a follow-up.
5. **Signing-tier coverage on this Mac is asymmetric with the prompt's
   assumptions**: a real Developer ID identity is checked into
   `dice-roller`'s `pyproject.toml` (so the *default* `package -p macos`
   path notarizes for real), and no distribution identity exists for iOS (so
   Step 3d used `--export-method development`, not `app-store`/`ad-hoc`).
   Both paths were still exercised — the "no identity" case by deliberately
   and temporarily clearing the config, restored afterward with a clean
   `git status`.
