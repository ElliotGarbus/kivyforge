# Fixes for the Mac docs and provisioning findings, on the Mac — findings

Validation run per [`mac-findings-fixes-prompt.md`](mac-findings-fixes-prompt.md),
against `main` @ `95afe2b6`. Date: 2026-09-26. Findings only; no code changed.

**Summary.** All five fixes from PR #20 behave as specified, and this is the
first run with an *available* phone, so two things are proven for the first
time: **`devicectl ... --console` exists and streams** (Xcode 27.0), and **a
pinned manual profile signs, installs and runs** on a device (case H). The
refusals for F and G stop before `xcodebuild` with the right `doctor` FAIL,
`package` now runs the entitlements check, `--arch` suggests `arm64` only, and
the macOS `.app` is `drwxr-xr-x`.

Putting a real phone in the loop found **four defects**, none introduced by
PR #20. Two break `run --device` for anyone with Xcode 27 and a phone, and one
means following kivyforge's own fix hint (unpin the profile) produces a build
Xcode refuses.

Xcode moved from 26.6 to **27.0** since the prompt was written, and the phone
is new (iPhone 18 Pro Max, iOS 27.0). Both matter to defects 2 and 4.

## Environment (Step 0)

| Item | Value |
|---|---|
| macOS | 26.6.2 (Build 25G83), Apple Silicon |
| Xcode | **27.0 (Build 27A266a)**, `xcode-select -p` = `/Applications/Xcode.app/Contents/Developer` |
| Simulator runtimes | iOS 26.5 and iOS 27.0 (the Step 1 simulator was an iOS 27.0 iPhone Air) |
| kivyforge | 3.0.0.dev0 (editable, `.venv`), `main` @ `95afe2b6` |
| Host Python | 3.14.7; `umask` 022 |
| Codesigning identities | `Developer ID Application: ELLIOT DREW GARBUS (R5PKSQLUZY)`, `Apple Development: ELLIOT DREW GARBUS (X83FAZ586W)` |
| Installed profiles | `UserData`: 2, `MobileDevice`: 0 |
| Profile 1 | Name `hello-kivy manual dev`, UUID `25ad797e-9e8a-4160-a20b-77f236cc3c28`, `IsXcodeManaged = false`, App ID `R5PKSQLUZY.org.kivy.hello-kivy`, 1 device (the new phone), certificate `X83FAZ586W`. Created on developer.apple.com for this run. Expires **2026-10-03** (a 7-day profile) |
| Profile 2 | Name `iOS Team Provisioning Profile: org.kivy.hello-kivy`, UUID `95c2fc50-9eae-43ac-bcb9-5f4e40935dbb`, `IsXcodeManaged = true`, 1 device (the **old** phone only), created 2026-09-15 |
| Device | iPhone 18 Pro Max (iPhone19,3), iOS 27.0 (24A437), wired, paired, Developer Mode enabled, **available**. UDID `00008160-0001192601A0000A`, CoreDevice identifier `0F7D0110-FDC1-5CB2-8880-8D1E626C7C0F` |
| Team ID | `team_id = "R5PKSQLUZY"` in the Step 2 scratch copy (`/tmp/pf`); the example's stays blank |
| Terminal | Every `run` was driven under a **pty** (Python `pty.fork`); Ctrl+C was a real `0x03` written to the pty, not a signal sent to a PID |

## Defects

### 1. Unpinning a profile leaves it in the generated project, so the build fails

**Contradicts:** kivyforge's own fix hint for case G ("Set auto_signing = true
and remove provisioning_profile, then re-lock"), and the `provisioning_profile`
reference ("Empty means Xcode chooses").

Case I (no `provisioning_profile`, `auto_signing = true`) run right after case
H, in the same scratch project:

```
=== case I: provisioning_profile="" auto_signing=true
{'name': 'Provisioning profile', 'status': 'PASS', 'detail': 'not set'}
--- build --device:
exit=5
xcodebuild build lines: 2
/tmp/pf/hello-kivy-ios/hello-kivy.xcodeproj: error: hello-kivy has conflicting provisioning settings. hello-kivy is automatically signed, but provisioning profile hello-kivy manual dev has been manually specified. Set the provisioning profile value to "Automatic" in the build settings editor, or switch to manual signing in the Signing & Capabilities editor. (in target 'hello-kivy' from project 'hello-kivy')
Error: xcodebuild build failed (exit 65); its output is above.
```

The `.pbxproj` had just been rewritten (mtime 17:17:40, the moment of the
build) and still said, in all four configurations:

```
CODE_SIGN_STYLE = Automatic;
PROVISIONING_PROFILE_SPECIFIER = "hello-kivy manual dev";
```

After `rm -rf hello-kivy-ios`, the identical config built (exit 0, 4 ×
`CODE_SIGN_STYLE = Automatic`, no specifier). So the config is right and the
regenerated project is stale.

**Cause.** `IOSProjectGenerator._apply_build_settings`
(`kivyforge/platforms/ios/generator.py:129`) loads the existing project and
calls `set_flags` for every key in the current settings. Nothing removes a key
that has *left* the settings. `buildsettings.signing_settings` omits
`PROVISIONING_PROFILE_SPECIFIER` when no profile is pinned, so the old value
survives. The same applies to any key removed from `[tool.kivy.ios]
build_settings`. The reverse move (from automatic to a pin) is unaffected,
because `set_flags` overwrites. Pre-existing, not from PR #20. It is on the
path users will take now that F and G refuse and tell them to unpin.

### 2. `run --device` refuses a single phone on Xcode 27: simulators count as paired devices

**Contradicts:** `guides/ios/run.md` "Run on a device" (`kivyforge run -p ios
--device` with one connected device).

```
$ kivyforge run -p ios --device --no-build
Error: command failed (1): devicectl
multiple paired iOS devices found ('Elliot’s iPhone', 'iPhone 17', 'iPhone Air', 'iPhone Air') — pass one explicitly, e.g. `kivyforge run --device --destination 'NAME'`
```

One phone was connected. The other three are simulators. Xcode 27's
`devicectl list devices -j` reports them with the fields kivyforge filters
on:

```
'Elliot’s iPhone' | platform= iOS | reality= physical  | pairingState= paired | tunnelState= connected    | transport= wired
'iPhone 17'       | platform= iOS | reality= simulated | pairingState= paired | tunnelState= disconnected | transport= sameMachine
'iPhone Air'      | platform= iOS | reality= simulated | pairingState= paired | tunnelState= connected    | transport= sameMachine
'iPhone Air'      | platform= iOS | reality= simulated | pairingState= paired | tunnelState= disconnected | transport= sameMachine
```

`pick_device` (`kivyforge/platforms/ios/xcode/runner.py:266`) keeps
`platform == "iOS" and pairing_state == "paired"`. `parse_devicectl_devices`
does not read `hardwareProperties.reality`, the field that separates them.
Not every simulator is listed (there are 20+), so which ones appear, and
whether Xcode 26.6 listed any, is unknown. The 2026-09-24 run did not record
devicectl's JSON. Two smaller problems in the same message: the prefix
`command failed (1): devicectl` blames a tool that succeeded, and the
`--destination 'NAME'` it suggests hits defect 3 if you copy the UDID
instead.

### 3. `--destination` rejects the UDID that `--list-devices` prints

**Contradicts:** `guides/ios/run.md` ("pass `--destination` with a device name
or identifier from `kivyforge run -p ios --list-devices`"; for simulators, "a
simulator name or UDID from the list").

```
$ kivyforge run -p ios --device --no-build --destination 00008160-0001192601A0000A
Error: command failed (1): devicectl
no device matches '00008160-0001192601A0000A' (run `kivyforge run --list-devices`)

$ kivyforge run -p ios --list-devices     # devices section, verbatim
Elliot’s iPhone                   00008160-0001192601A0000A (UDID)              connected     iPhone 18 Pro Max (iPhone19,3)   physical
```

`_match_device` compares against devicectl's JSON `identifier`, which is the
CoreDevice UUID (`0F7D0110-…`) and is never shown to the user. The UDID is
under `hardwareProperties.udid`. The name worked: `--destination "Elliot’s
iPhone"` (typographic apostrophe, copied from the list). A substring such as
`Elliot` would pick the **Apple Watch**, which is listed first.

### 4. Automatic signing builds for the device, then install fails: the profile does not cover the phone

Case I from a clean project built (exit 0) and was signed with the existing
Xcode-managed profile `95c2fc50-…`. That profile was created 2026-09-15 and
covers only the old phone. Installing it:

```
$ kivyforge run -p ios --device --no-build --destination "Elliot’s iPhone"
Installing on device Elliot’s iPhone (0F7D0110-FDC1-5CB2-8880-8D1E626C7C0F) ...
Error: command failed (1): xcrun devicectl device install app --device 0F7D0110-FDC1-5CB2-8880-8D1E626C7C0F /private/tmp/pf/hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphoneos/hello-kivy.app
ERROR: Failed to install the app on the device. (com.apple.dt.CoreDeviceError error 3002 (0xBBA))
           Unable to Install “Hello Kivy” (IXUserPresentableErrorDomain error 14 (0x0E))
           NSLocalizedFailureReason = This app cannot be installed because its integrity could not be verified.
           NSLocalizedRecoverySuggestion = Failed to install embedded profile for org.kivy.hello-kivy : 0xe8008012 (This provisioning profile cannot be installed on this device.)
```

The phone *was* registered on developer.apple.com (done by hand for case H),
so this is not device registration. `xcodebuild` is given `-sdk iphoneos` and
`-allowProvisioningUpdates` but **no `-destination`**
(`kivyforge/platforms/ios/xcode/commands.py`, the device branch of the build
command). With no concrete device, Xcode has no reason to refresh a managed
profile that lacks it. Likely fix: pass `-destination id=<UDID>` when `run
--device` builds, and maybe `-allowProvisioningDeviceRegistration`. **Not
tried**, because it would regenerate the account's real Xcode-managed profile.
Anyone whose managed profile predates their phone hits this. The last run's
phone was unavailable, so it never got this far.

## Notes (not defects)

- **Ctrl+C on the device prints a Python traceback and "bootstrap fatal".**
  `devicectl --console` forwards SIGINT to the app (as its `--help` says),
  Kivy raises `KeyboardInterrupt` in `time.sleep`, and the iOS bootstrap
  (`templates/kivyforge_bootstrap.m`, `_crash`) reports it as
  `kivyforge bootstrap fatal: failed to run entry module "main"`. The app
  exits 1. It is the right outcome (the app stops, `run` exits 1), but it
  reads like a crash. The simulator's Ctrl+C prints no traceback.
- **Double-clicking the `.mobileprovision` did not install it** under Xcode
  27.0. After the owner double-clicked it, it was still only in `~/Downloads`
  and in neither directory kivyforge searches. It was copied by hand to
  `~/Library/Developer/Xcode/UserData/Provisioning Profiles/<UUID>.mobileprovision`.
  Seen once; what Xcode did with the double-click was not observed. The
  `provisioning_profile` note in `reference/pyproject/ios.md` says "install
  the file too (double-click it)".
- **Refusals are unclassified.** F, G and `--arch` give `KF-ERROR` (exit 1).
  That is correct under the "unspecific, never wrong" rule, but a signing code
  would let an agent branch on it.
- The `--json` envelope carries no `exit_code` field. The prompt asked for
  one, and it is the process exit status (1) by design.
- Second user account for the `.app`: not tried.
- `security unlock-keychain` (macOS signing troubleshooting): not run, because
  it prompts for a password. `signing.keychain-db` was already unlocked
  (`lock-on-sleep no-timeout`).

## Step 1 — `run -p ios` streams the console

Simulator, in `examples/mobile/hello-kivy`, under a pty. `build -p ios
--simulator`: exit 0. The first `run` got Ctrl+C at 15 s, **during install**
(a cold simulator boot), so it proved nothing. It was re-run with a 45 s wait:

```
[  0.35s] Installing on simulator iPhone Air (8C884479-6E70-49B5-8896-954B7E4954B0) ...
[ 10.98s] Launching org.kivy.hello-kivy ...
[ 11.22s] org.kivy.hello-kivy: 91184
[ 11.76s] [WARNING] [Config      ] Older configuration version detected (0 instead of 29)
[ 11.76s] [WARNING] [Config      ] Upgrading configuration in progress.
[ 11.76s] [DEBUG  ] [Config      ] Upgrading from 0 to 1
[ 11.76s] [INFO   ] [Logger      ] Record log in /Users/.../Documents/.kivy/logs/kivy_26-09-26_0.txt
[ 11.76s] [INFO   ] [Kivy        ] v3.0.0.dev202607301604, git-71407bc, 2026-07-30T16:04:19+00:00
[ 11.76s] [INFO   ] [Python      ] v3.15.0b4 (tags/v3.15.0b4-dirty:0a6fa62, Jul 18 2026, 08:07:19) [Clang 15.0.0 (clang-1500.3.9.4)]
...
[ 16.34s] [INFO   ] [WindowSDL   ] Window display scale changed
[ 45.16s] >>> sent Ctrl+C (0x03) to the pty
[ 45.18s] ^C
[ 45.20s] Aborted!
>>> exit=1 after 45.22s
```

The lines arrive live, under a second after launch, while the app runs for another 30 s.
Ctrl+C prints click's `Aborted!` and exits 1. **The app is not running
afterwards** (`simctl spawn booted launchctl list` shows no
`UIKitApplication:org.kivy.hello-kivy`. The check was validated by launching
the app without a console: it lists `UIKitApplication:org.kivy.hello-kivy[acff][rb-legacy]`,
and the entry is gone after `simctl terminate`).

The device flag:

```
$ xcrun devicectl device process launch --help | grep -n -A2 -- --console
20:--console bridges the app's stdout to devicectl's stdout, so '--json-output -'
21:is not supported with --console; pass '--json-output <path>' instead.
72:  --console               Attaches the application to the console and waits for
73-                          it to exit.
74-        devicectl will wait for the app to terminate. Catchable signals sent to
```

The rest of the help text: "Catchable signals sent to devicectl are forwarded
to the app. If the app is not already running, its standard streams will be
connected to devicectl's standard streams." kivyforge passes no
`--terminate-existing`, so if the app is already running, the console is
probably not attached. Not tried.

Device run, with case H's build (see Step 2). The plain `--device` hit defect
2. The run below is by name:

```
[  0.15s] Installing on device Elliot’s iPhone (0F7D0110-FDC1-5CB2-8880-8D1E626C7C0F) ...
[ 16.11s] Launching org.kivy.hello-kivy ...
[ 16.39s] Launched application with org.kivy.hello-kivy bundle identifier.
[ 16.39s] Waiting for the application to terminate…
[ 16.60s] [INFO   ] [Kivy        ] v3.0.0.dev202607301604, git-71407bc, 2026-07-30T16:04:19+00:00
[ 16.60s] [INFO   ] [Python      ] v3.15.0b4 (tags/v3.15.0b4-dirty:0a6fa62, Jul 18 2026, 08:05:07) [Clang 15.0.0 (clang-1500.3.9.4)]
[ 19.31s] [INFO   ] [GL          ] OpenGL renderer <b'ANGLE (Apple, ANGLE Metal Renderer: Apple A20 Pro GPU, Version 27.0 (Build 24A437))'>
[ 19.39s] [INFO   ] [Base        ] Start application main loop
[ 45.03s] >>> sent Ctrl+C (0x03) to the pty
[ 45.05s] ^C[INFO   ] [Base        ] Leaving application in progress...
[ 45.08s]  Traceback (most recent call last):
            ... (kivy/app.py run -> base.py mainloop -> clock.py _usleep)
[ 45.08s]      time.sleep(microseconds / 1000000.)
[ 45.08s]  KeyboardInterrupt
[ 45.08s] 2026-09-26 17:17:02.776 hello-kivy[937:87104] kivyforge bootstrap fatal: failed to run entry module "main"
[ 45.10s] The app terminated with the exit code 1.
[ 45.20s] Aborted!
>>> exit=1 after 45.18s
```

The console streams live from the phone, and Ctrl+C stops the app (no
`hello-kivy` in `devicectl device info processes` afterwards).

## Step 2 — pinned profiles Xcode refuses

Scratch copy `/tmp/pf` (with `hello-kivy-ios/` removed), `team_id =
"R5PKSQLUZY"`. The cases ran sequentially, each edit followed by `lock -p ios`
(exit 0 every time).

| Case | `provisioning_profile`, `auto_signing` | `doctor` Provisioning profile | `build --device` | `xcodebuild build` lines |
|---|---|---|---|---|
| F | `iOS Team Provisioning Profile: org.kivy.hello-kivy`, `true` | **FAIL** "… is pinned, but auto_signing is on" | exit 1 | 0 |
| G | same, `false` | **FAIL** "… is an Xcode-managed profile, which manual signing refuses" | exit 1 | 0 |
| H | `hello-kivy manual dev`, `false` | **PASS** "hello-kivy manual dev (installed)" | exit 0, signed | 1 |
| I | none, `true` | **PASS** "not set" | exit 5 after H (**defect 1**); exit 0 from a clean project, but won't install (**defect 4**) | 2 / 1 |

F, verbatim:

```
Error: provisioning_profile is set, but auto_signing is on, and Xcode refuses a pinned profile under automatic signing.
  Fix one of these ways:
    - Set [tool.kivy.ios.signing].auto_signing = false to sign with the pinned profile, then re-lock
    - Remove provisioning_profile to let Xcode manage signing, then re-lock
```

G, verbatim:

```
Error: the pinned provisioning profile 'iOS Team Provisioning Profile: org.kivy.hello-kivy' is managed by Xcode, and Xcode will not sign with it under manual signing.
  Fix one of these ways:
    - Create a manual profile for this App ID at developer.apple.com, install it, and pin that one
    - Set auto_signing = true and remove provisioning_profile, then re-lock
```

G with `--json`: exit 1, one envelope on stdout, the same message on stderr.
`ok: false`, `diagnostics[].code = ["KF-ERROR"]`, `data.artifacts = []`.

H, the signed product:

```
embedded Name=hello-kivy manual dev
embedded UUID=25ad797e-9e8a-4160-a20b-77f236cc3c28
embedded IsXcodeManaged=false
Authority=Apple Development: ELLIOT DREW GARBUS (X83FAZ586W)
TeamIdentifier=R5PKSQLUZY
codesign verify: OK
CODE_SIGN_STYLE = Manual
PROVISIONING_PROFILE_SPECIFIER = "hello-kivy manual dev"
```

It installed and ran on the phone (Step 1). **This is the first proof that a
pinned profile signs at all.**

**Package runs the entitlements check.** H's settings plus
`[tool.kivy.ios.entitlements] "aps-environment" = "development"`, re-locked.
`doctor`: Provisioning profile PASS; Entitlements vs. profile **FAIL** "not
granted by hello-kivy manual dev: aps-environment".

```
$ kivyforge package -p ios --export-method development; echo "exit=$?"
Error: entitlements declared in pyproject.toml are not granted by the provisioning profile.
  Profile: hello-kivy manual dev  (App ID: R5PKSQLUZY.org.kivy.hello-kivy)
  Not granted:
    - aps-environment
  Fix one of these ways:
    - Enable the matching capability on this App ID at developer.apple.com,
      then regenerate and re-download the profile
    - Remove the key from [tool.kivy.ios.entitlements], then re-lock
exit=1
xcodebuild archive lines: 0
```

## Step 3 — iOS `--arch`

In `examples/mobile/hello-kivy`:

```
=== --arch aarch64
Error: --arch aarch64 is not an iOS simulator arch.
  The simulator slice is arm64 only; pass --arch arm64 or omit --arch.
exit=1
=== --arch x86_64
Error: --arch x86_64 is not an iOS simulator arch.
  The simulator slice is arm64 only; pass --arch arm64 or omit --arch.
exit=1
=== --arch x86_64 --json
{ "schema": 1, "command": "build", "platform": "ios", "ok": false,
  "data": { "artifacts": [] },
  "diagnostics": [ { "code": "KF-ERROR", "severity": "error",
    "message": "--arch x86_64 is not an iOS simulator arch.\n  The simulator slice is arm64 only; pass --arch arm64 or omit --arch." } ] }
exit=1
=== --arch arm64
Built hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/hello-kivy.app
exit=0
```

No `Collecting artifacts` line and no traceback on the three refusals. The
`--json` stdout is one document (shown condensed, with `kivyforge` omitted).
The example's `git status` stayed clean.

## Step 4 — bundle permissions

Scratch `/tmp/drp` (dice-roller, `[tool.kivy.macos.signing]` removed,
re-locked), `umask` 022:

```
build exit=0
drwxr-xr-x build/macos/Dice Roller.app
drwxr-xr-x build/macos/Dice Roller.app/Contents
package exit=0
drwxr-xr-x build/macos/Dice Roller.app
drwxr-xr-x build/macos/Dice Roller.app/Contents
dirs in the .app not group/other-readable: 0
Packaged build/macos/Dice Roller.app (ad-hoc signed).
```

## Step 5 — the corrected docs

- `guides/ios/signing.md`: the "Pinning a profile requires manual signing"
  warning and the Entitlements section match F, G, H and the `package`
  check exactly.
- `reference/pyproject/ios.md`: the `provisioning_profile` row and note match,
  except for the double-click note (Notes) and defect 1 ("Empty means Xcode
  chooses" is true only for a fresh project).
- `guides/macos/signing.md`: `codesign --verify --deep --strict --verbose=2`
  on the ad-hoc app gives "valid on disk / satisfies its Designated
  Requirement", exit 0. `security unlock-keychain` was not run (Notes).
- `get-started/quickstart-ios.md`: "`run` then streams the app's console
  output to your terminal until you stop it with Ctrl+C" is now **true** on
  the simulator and the device.

## Doc corrections

| Page | Wrong text | What is true |
|---|---|---|
| `guides/ios/run.md`, Run on a device | `kivyforge run -p ios --device` (implied to work with one phone) | With Xcode 27 it fails with "multiple paired iOS devices" whenever simulators exist (defect 2). Until fixed, pass `--destination "DEVICE NAME"` |
| `guides/ios/run.md`, Run on a device | "a device name or identifier from `kivyforge run -p ios --list-devices`" | Only the name works. The UDID the list prints is rejected (defect 3) |
| `reference/pyproject/ios.md`, `provisioning_profile` | "Empty means Xcode chooses" | Only for a newly generated project. After unpinning, delete `<app>-ios/` first (defect 1) |
| `reference/pyproject/ios.md`, note | "install the file too (double-click it)" | With Xcode 27.0, the double-click left the file in `~/Downloads` once. Copying it to `~/Library/Developer/Xcode/UserData/Provisioning Profiles/<UUID>.mobileprovision` works. Seen once |
| `get-started/quickstart-ios.md` | "until you stop it with Ctrl+C" | True. Ctrl+C also quits the app, and on a device the app's log ends in a `KeyboardInterrupt` traceback and "kivyforge bootstrap fatal" (Notes) |

No change needed: `guides/ios/signing.md`, `guides/macos/signing.md`.
