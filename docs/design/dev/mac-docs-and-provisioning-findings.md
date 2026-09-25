# End-user docs and provisioning-profile fix, on the Mac — findings

Validation run per [`mac-docs-and-provisioning-prompt.md`](mac-docs-and-provisioning-prompt.md),
against `main` @ `6ba44674`. Date: 2026-09-24. Findings only; no code changed.

**Summary.** The four changes behave as specified: `provisioning_profile` by
name, UUID and path (A–E) all produce the expected `doctor` result and Xcode
specifier; the entitlements pre-flight now fires for a pinned name; `--arch
aarch64` is refused on iOS; `uv tool install` and `pipx install` both ship pip
and lock. Walking the docs found **five defects**, none introduced by this
change set — two of them sit directly in the provisioning path the fix was
about, and one (`run` never streaming the console) has been true since July.
Every Mac-side page's commands and paths are otherwise correct.

## Environment (Step 0)

| Item | Value |
|---|---|
| macOS | 26.6.2 (Build 25G83), Apple Silicon |
| Xcode | 26.6 (Build 17F113), `xcode-select -p` = `/Applications/Xcode.app/Contents/Developer` |
| Simulator runtime | iOS 26.5 (23F77) |
| kivyforge | 3.0.0.dev0 (editable, `.venv`), `main` @ `6ba44674` |
| Host Python / pip | 3.14.7 / 26.2.1 |
| Codesigning identities | `Developer ID Application: ELLIOT DREW GARBUS (R5PKSQLUZY)` (in a dedicated `signing.keychain-db`), `Apple Development: ELLIOT DREW GARBUS (X83FAZ586W)` |
| Installed profiles | `UserData`: 1, `MobileDevice`: 0 |
| Profile used | Name `iOS Team Provisioning Profile: org.kivy.hello-kivy`, UUID `95c2fc50-9eae-43ac-bcb9-5f4e40935dbb`, App ID `R5PKSQLUZY.org.kivy.hello-kivy`, **`IsXcodeManaged = true`**, grants only `application-identifier`, `team-identifier`, `get-task-allow`, `keychain-access-groups` |
| Device | iPhone 13 Pro Max (iPhone14,3) paired but **unavailable** to CoreDevice all session — device builds ran, nothing installed |
| Team ID for device builds | `KIVYFORGE_TEAM_ID=R5PKSQLUZY` (the example's `team_id` is blank on purpose) |

## Defects

### 1. `run -p ios` never streams the app's console

`quickstart-ios.md`: "`run` then streams the app's console output to your
terminal until you stop it with Ctrl+C." It does not — not to a file, and not
to a real pseudo-terminal:

```
$ kivyforge run -p ios --simulator --no-build        # under a Python pty.fork, 30 s
Installing on simulator iPhone Air (BEFCED45-631C-41C5-B79B-8778D99F38E3) ...
Launching org.kivy.hello-kivy ...
                                                     # nothing further; app is running and rendered
^C
Aborted!                                             # exit 1
```

The identical `simctl` command, run directly under the same pty, streams
immediately (57 lines in 15 s):

```
$ xcrun simctl launch --console-pty booted org.kivy.hello-kivy
org.kivy.hello-kivy: 44712
[INFO   ] [Logger      ] Record log in .../Documents/.kivy/logs/kivy_26-09-24_4.txt
[INFO   ] [Kivy        ] v3.0.0.dev202607301604, git-71407bc, 2026-07-30T16:04:19+00:00
...
```

**Cause:** `_run_simulator` (`platforms/ios/cli.py:556`) launches through
`run_command` (`platforms/ios/xcode/runner.py:32`), which spawns every tool with
`capture_output=True, stdin=subprocess.DEVNULL`. The console is buffered and
shown only if the launch *fails*; Ctrl+C discards it. `capture_output` dates to
2026-07-10 (`66bdf6cb`), so `run -p ios` has never streamed through kivyforge;
`stdin=DEVNULL` was added 2026-09-17 (`19e318ab`). This also contradicts
AGENTS.md, which names `run`'s app launch as the deliberate exception that
keeps the user's stdin. `_run_device` (`cli.py:559`) uses the same helper for
`devicectl`, so the device path very likely has the same defect — not observed,
the phone was unavailable.

### 2. `auto_signing = true` plus a pinned `provisioning_profile` never builds, and `doctor` passes it

Cases A–D all used the example's default `auto_signing = true`. Every one got a
PASS (or the expected FAIL for D) from `doctor`, and every device build failed
the same way:

```
/tmp/pp/hello-kivy-ios/hello-kivy.xcodeproj: error: hello-kivy has conflicting provisioning settings. hello-kivy is automatically signed, but provisioning profile iOS Team Provisioning Profile: org.kivy.hello-kivy has been manually specified. Set the provisioning profile value to "Automatic" in the build settings editor, or switch to manual signing in the Signing & Capabilities editor. (in target 'hello-kivy' from project 'hello-kivy')
Error: xcodebuild build failed (exit 65); its output is above.
```

`xcode_signing_settings()` (`platforms/ios/buildsettings.py:158`) writes
`PROVISIONING_PROFILE_SPECIFIER` whenever `provisioning_profile` is set,
regardless of `CODE_SIGN_STYLE = Automatic`. **Pre-existing:** the code at
`53a4bbd0` wrote the raw string the same way; the fix only changed *which*
value is written. It contradicts `guides/ios/signing.md` §Entitlements and
`diagnostics.ENTITLEMENTS_UNGRANTED`'s own comment, both of which describe
auto-signing with a pinned profile as a supported setup that merely warns —
in practice that warning (Step 2) is always followed by this build failure.

### 3. `doctor` passes an Xcode-managed profile under manual signing; Xcode refuses it

With `auto_signing = false`, cases C and A:

```
[PASS] Provisioning profile: iOS Team Provisioning Profile: org.kivy.hello-kivy (installed)
...
/tmp/pp/hello-kivy-ios/hello-kivy.xcodeproj: error: Provisioning profile "iOS Team Provisioning Profile: org.kivy.hello-kivy" is Xcode managed, but signing settings require a manually managed profile. (in target 'hello-kivy' from project 'hello-kivy')
```

The profile carries `IsXcodeManaged = true`; `grep -rn IsXcodeManaged
kivyforge/` finds nothing. Combined with defect 2, **no value of `auto_signing`
builds with an Xcode-managed profile pinned** — and that is the only kind of
profile Xcode's automatic signing ever installs, i.e. the one a reader of the
docs is most likely to find in `~/Library/.../Provisioning Profiles` and pin.

### 4. The new iOS `--arch` refusal recommends `x86_64`, which crashes with a traceback

```
$ kivyforge build -p ios --simulator --arch aarch64
Error: --arch aarch64 is not an iOS simulator arch.
  Use one of: arm64, x86_64, or omit --arch to use the host's.
exit=1

$ kivyforge build -p ios --simulator --arch x86_64
Collecting artifacts for ios_16_0_x86_64_iphonesimulator ...
Traceback (most recent call last):
  ...
  File ".../kivyforge/artifacts/wheels.py", line 82, in select_wheel
kivyforge.artifacts.wheels.WheelSelectionError: Kivy has no compatible wheel for slice ios_16_0_x86_64_iphonesimulator (have: ios_13_0_arm64_iphoneos, ios_13_0_arm64_iphonesimulator).
exit=1
```

`_SIMULATOR_ARCH_CHOICES` in `platforms/ios/cli.py` still lists `x86_64`, while
`VALID_SIMULATOR_ARCHS` in `config/model.py:188` is `{"arm64"}` (x86_64
simulator support was removed). Two faults: the message advertises an arch
config no longer supports, and `WheelSelectionError` escapes unclassified — no
`KF-*` code, and under `--json` no envelope. The docstring beside it ("The lock
pins both simulator arches") is stale for the same reason.

### 5. The built macOS `.app` is mode `0700` — owner-only

```
$ stat -f "%Sp %N" "build/macos/Dice Roller.app" "build/macos/Dice Roller.app/Contents"
drwx------ build/macos/Dice Roller.app
drwxr-xr-x build/macos/Dice Roller.app/Contents
$ umask
022
```

Same on the ad-hoc quickstart build and on the Developer-ID-notarized build,
and it survives into a DMG (`cp -R` preserves it). `macos/bundle.py:148`
assembles into `tempfile.mkdtemp(...)` — always `0700` — and swaps it into
place without resetting the mode. Consequence, **inferred, not tested** (needs
a second user account): an app copied to `/Applications` by one user cannot be
opened by other users on that Mac. `linux/bundle.py:149` uses the identical
pattern for the AppDir; not checked from this host.

### Notes — not defects

- **Manual-signing entitlements refusal is `KF-ERROR`, exit 1.** Unspecific but
  never wrong (AGENTS.md). The only entitlements code,
  `KF-ENTITLEMENTS-UNGRANTED`, is defined as a warning.
- **`run --device` picks an `unavailable` device**, does a full signed build,
  then fails at install with CoreDevice's raw error (`unable to locate a device
  matching the requested device identifier ... error 1011`). Correct outcome;
  could fail before the build.
- **`errSecInternalComponent` troubleshooting omits the common cause.** The
  first Developer-ID `package` attempt failed with it because
  `signing.keychain-db` was locked (`security show-keychain-info` → "Unable to
  obtain authorization"); after `security unlock-keychain` the identical
  command succeeded. `guides/macos/signing.md` attributes the error only to a
  corrupted key ACL.
- **Not proven, and why:** a manually signed device build/install (the only
  installed profile is Xcode-managed — defect 3 — and creating a manual one
  needs developer.apple.com; the phone was unavailable). Whether Xcode registers
  HealthKit under auto-signing (blocked by defect 2; not worked around by
  unpinning, because `-allowProvisioningUpdates` would modify the real App ID).
  The desktop window title (the shell has no screen-recording permission;
  launch confirmed by "Start application main loop" only). The two `sudo`
  Xcode setup commands were not run — they prompt; their end state was
  verified instead (`xcode-select -p`, `xcodebuild -license check` exit 0).

## Step 1 — `provisioning_profile` by name, UUID, and path

Scratch copy `/tmp/pp` of `examples/mobile/hello-kivy`; each case re-locked,
then `doctor --json` (provisioning/entitlement checks), `build --device`, and
the specifier grepped from the generated `project.pbxproj`. The `--json` shape
matched the prompt's filter.

| Case | Value | `doctor` (observed) | Specifier in pbxproj | Build |
|---|---|---|---|---|
| A | profile `Name` | `PASS` `iOS Team Provisioning Profile: org.kivy.hello-kivy (installed)` | the name, verbatim | exit 5 — defect 2 |
| B | profile `UUID` | `PASS` `95c2fc50-9eae-43ac-bcb9-5f4e40935dbb (installed)` | the UUID | exit 5 — defect 2 |
| C | `dev.mobileprovision` (copy in project) | `PASS` `iOS Team Provisioning Profile: org.kivy.hello-kivy (dev.mobileprovision)` | **the UUID**, not the path | exit 5 — defect 2 |
| D | `Nobody At All` | `FAIL` `no installed profile has the name or UUID 'Nobody At All'` + hint | `Nobody At All`, verbatim | exit 5 — defect 2 (`build` does not gate on `doctor`) |
| C, manual | same, `auto_signing = false` | `PASS` | the UUID | exit 5 — defect 3 |
| A, manual | name, `auto_signing = false` | `PASS` | the name | exit 5 — defect 3 |
| E | path, profile **not installed** | `WARN` `... (dev.mobileprovision) is not installed`, hint `Xcode signs only with installed profiles; double-click dev.mobileprovision to install it.` | — | not run |

Every `doctor` result and specifier matches the prompt's expectation table.

**Case E method:** rather than moving the real profile out of `~/Library`, `doctor`
ran with `HOME=/tmp/emptyhome`. The lookup builds both directories from
`Path.home()` (`platforms/ios/entitlements.py:76`), so this exercises the same
code against a real `.mobileprovision` file with no installed profiles, and
left the user's Xcode state untouched.

## Step 2 — the entitlements pre-flight fires for a pinned name

Pinned by name, `"com.apple.developer.healthkit" = true` added.

`auto_signing = false`:

```
[PASS] Provisioning profile: iOS Team Provisioning Profile: org.kivy.hello-kivy (installed)
[FAIL] Entitlements vs. profile: not granted by iOS Team Provisioning Profile: org.kivy.hello-kivy: com.apple.developer.healthkit
       hint: enable the matching capability on App ID R5PKSQLUZY.org.kivy.hello-kivy at developer.apple.com and regenerate the profile, or remove the key from [tool.kivy.ios.entitlements].

$ kivyforge build -p ios --device; echo "exit=$?"
Error: entitlements declared in pyproject.toml are not granted by the provisioning profile.
  Profile: iOS Team Provisioning Profile: org.kivy.hello-kivy  (App ID: R5PKSQLUZY.org.kivy.hello-kivy)
  Not granted:
    - com.apple.developer.healthkit
  Fix one of these ways:
    - Enable the matching capability on this App ID at developer.apple.com,
      then regenerate and re-download the profile
    - Remove the key from [tool.kivy.ios.entitlements], then re-lock
exit=1
```

`xcodebuild` invocations in that log: **0** — stopped before Xcode, as
specified. Under `--json`: `ok: false`, `KF-ERROR`, `artifacts: []`.

`auto_signing = true`:

```
[WARN] Entitlements vs. profile: not granted by iOS Team Provisioning Profile: org.kivy.hello-kivy: com.apple.developer.healthkit
       hint: ... auto_signing is on, so Xcode may register it at build time.

$ kivyforge build -p ios --device
Warning: entitlements not granted by the pinned provisioning profile: com.apple.developer.healthkit
/tmp/pp/hello-kivy-ios/hello-kivy.xcodeproj: error: hello-kivy has conflicting provisioning settings. ...
Error: xcodebuild build failed (exit 65); its output is above.
```

WARN and proceed, as specified; whether Xcode registers the capability is
unobservable because of defect 2.

## Step 3 — `--arch aarch64` on iOS

In `examples/mobile/hello-kivy`: `--arch aarch64` → the refusal above, exit 1,
no "Collecting artifacts" line. `--arch arm64` → `Built
hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/hello-kivy.app`,
unchanged behaviour. The refusal's `x86_64` suggestion is defect 4.

## Step 4 — install paths

`uv` 0.12.19 and `pipx` 1.17.6 were not installed on this Mac; both were put in
a throwaway venv (`/tmp/tools`), not on the system.

```
$ UV_TOOL_DIR=/tmp/uvt UV_TOOL_BIN_DIR=/tmp/uvb uv tool install "$PWD"
Installed 2 executables: kf, kivyforge
$ /tmp/uvt/kivyforge/bin/python -m pip --version
pip 26.2.1 from /private/tmp/uvt/kivyforge/lib/python3.14/site-packages/pip (python 3.14)

$ PIPX_HOME=/tmp/px PIPX_BIN_DIR=/tmp/pxb pipx install "$PWD"
$ /tmp/px/venvs/kivyforge/bin/python -m pip --version
pip 26.2.1 from /private/tmp/px/venvs/kivyforge/lib/python3.14/site-packages/pip (python 3.14)
```

`lock -p macos --json` on a scratch `dice-roller` with `[tool.kivy.macos.signing]`
removed: **uv `ok: true`, `diagnostics: []`; pipx `ok: true`, `diagnostics: []`.**
Both pips sit in the tool's own `site-packages`, i.e. the new dependency
supplies them; this run cannot separately confirm the docs' claim that a pipx
venv would have had pip without it. `/tmp/uvt /tmp/uvb /tmp/px /tmp/pxb` and
`/tmp/tools` removed afterwards.

## Step 5 — the Mac-side docs, walked literally

On a fresh `git clone https://github.com/ElliotGarbus/kivyforge.git`
(`6ba44674`) in `/tmp/qs`.

**`get-started/quickstart-ios.md`** — `doctor -p ios` exit 0 (the two expected
WARNs: byte-compile, privacy manifest); `build -p ios --simulator` produced the
`.app` at the stated path; `run -p ios --simulator` booted/installed/launched
and "Hello Kivy" rendered (screenshot). **Console streaming: false** — defect 1.
Verify step: `build --json` → `ok: true`, artifacts
`{"path": "hello-kivy-ios", "kind": "project"}` and
`{"path": "hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/hello-kivy.app", "kind": "app"}`.
Clone's `git status` clean afterwards (committed lock not rewritten).

**`get-started/quickstart-desktop.md`, macOS path** — deleted
`[tool.kivy.macos.signing]` as Step 2 instructs; `doctor` (no `-p`) picked macOS,
exit 0, signing checks `SKIP` ("ad-hoc floor applies"); `lock` wrote
`pylock.macos.toml` (2 packages); `run` reached `Start application main loop`;
build at **`build/macos/Dice Roller.app` — correct**. `package` → stdout
`Packaged build/macos/Dice Roller.app (ad-hoc signed).`, `codesign -dv` →
`Signature=adhoc`; `package --json` → one `app` artifact at that path plus the
expected `KF-SIGNING-UNCONFIGURED` warning. All as documented.

**`guides/ios/run.md`** — `--list-devices` lists simulators and physical devices;
`run -p ios --no-build --destination "iPhone 17"` (no `--simulator`: the default
holds) booted that shut-down simulator by name, installed, launched, rendered
(screenshot); it was shut down again afterwards. `build -p ios` with no target:
`Project ready. Open it with kivyforge open ...` — stops after generation, as
stated. Symlink tip: `hello-kivy-ios/app -> ../src` — correct. `run --device`:
see Notes (device unavailable).

**`guides/macos/signing.md`** — on a scratch `dice-roller` with the signing table
intact: `doctor` PASS on identity, identity type, and notary setup. First
`package` failed with `errSecInternalComponent` on a locked keychain (Notes);
after unlocking:

```
Developer ID signing with 'Developer ID Application: ELLIOT DREW GARBUS (R5PKSQLUZY)' ...
Zipping Dice Roller.app for notarization ...
Submitting to the Apple notary service (this can take minutes) ...
Notarization accepted (submission fdfbfa63-876c-42a1-979d-63f861f856ce).
Stapling the notarization ticket ...
Packaged build/macos/Dice Roller.app (Developer ID notarized + stapled).     # 1:26 total
```

Verify:

```
$ codesign --verify --deep --strict --verbose=2 "build/macos/Dice Roller.app"
build/macos/Dice Roller.app: valid on disk
build/macos/Dice Roller.app: satisfies its Designated Requirement
$ spctl --assess --type execute --verbose "build/macos/Dice Roller.app"
build/macos/Dice Roller.app: accepted
source=Notarized Developer ID
$ xcrun stapler validate "build/macos/Dice Roller.app"
The validate action worked!
```

The page's final-line example matches verbatim. (The page's Verify section
lists `spctl` and `stapler` only; `codesign` was added here per the prompt.)

**`guides/macos/dmg.md`** — every step as written, around the notarized app:
`hdiutil create` → `created: .../Dice Roller.dmg`; mounted (`hdiutil attach
-nobrowse -readonly`) it shows `Dice Roller.app` and `Applications ->
/Applications`, and `codesign --verify --deep --strict` on the app inside it
passes; `codesign --sign ... --timestamp` exit 0; `notarytool submit --wait` →
`Accepted` (id `ba767cfe-7566-4496-9ede-f271fb36821b`); `stapler staple` → `The
staple and validate action worked!`; the page's Verify:

```
$ spctl --assess --type open --context context:primary-signature --verbose "Dice Roller.dmg"
Dice Roller.dmg: accepted
source=Notarized Developer ID
```

Not done: opening the DMG on a second Mac, which the page also suggests.

**`guides/ios/signing.md`** — `package -p ios --export-method development
--json` → `ok: true`, artifact `{"path": "hello-kivy-ios/build/hello-kivy.ipa",
"kind": "ipa"}`, file present — **matches `<app>-ios/build/<app>.ipa`**. Two
distinct `KF-BYTECOMPILE-NO-INTERP` warnings (app sources, pip-deps — the 3.15
pre-release). The default (`app-store`) on this Mac, which has no distribution
certificate: `ok: false`, `KF-BUILD-TOOL-FAILED`, `artifacts: []`, `error:
exportArchive No signing certificate "iOS Distribution" found` — a clean,
correctly classified failure.

## Doc corrections

| Page | Wrong text | What is true |
|---|---|---|
| `get-started/quickstart-ios.md` | "`run` then streams the app's console output to your terminal until you stop it with Ctrl+C." | `run` prints `Installing ...`/`Launching ...` and nothing else; Ctrl+C prints `Aborted!` (exit 1). True only once defect 1 is fixed. |
| `guides/ios/signing.md` §Entitlements; `reference/pyproject/ios.md` `provisioning_profile` | Auto-signing with a pinned profile is presented as supported, with ungranted entitlements "a warning". | Xcode refuses any pinned profile under `CODE_SIGN_STYLE = Automatic` (defect 2). Until the build stops emitting the specifier under automatic signing, the docs should say pinning requires `auto_signing = false`. |
| `guides/ios/signing.md` step 1 (manual signing bullet) | "set `provisioning_profile` to the name or UUID of an installed profile" | Not any installed profile: an Xcode-managed one (`iOS Team Provisioning Profile: ...`, the kind automatic signing installs) is rejected under manual signing (defect 3). It must be a manually created profile. |
| `guides/macos/signing.md` Troubleshooting | `errSecInternalComponent` "... may be corrupted" ACL | Check first that the signing keychain is unlocked (`security unlock-keychain <keychain>`); a locked keychain produces the same error, and that is what happened here. |
| `guides/macos/signing.md` Verify | `spctl` + `stapler` only | Optional: add `codesign --verify --deep --strict`, which checks the seal independently of Gatekeeper. |

No corrections needed in `quickstart-desktop.md` (macOS path), `guides/ios/run.md`,
or `guides/macos/dmg.md`: every command and path was correct as written.
