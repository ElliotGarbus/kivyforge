# iOS half of the permissions guide — findings (Mac)

Run per [`permissions-docs-ios-prompt.md`](permissions-docs-ios-prompt.md) on
the Mac, 2026-11-10, against branch `android-permission-attributes`. Findings
only: no code or docs were changed. All scratch work was in `/tmp/kfperm`, a
copy of `examples/mobile/rubicon-deviceinfo`.

## Environment (Step 0)

| Item | Value |
|---|---|
| Branch | `android-permission-attributes` @ `d011b660` (matches `origin`) |
| macOS | 26.6.2 (25G83), arm64 |
| Xcode | 27.0 (27A266a) |
| kivyforge | 0.1.0, editable install in `.venv` (CPython 3.14.7) |
| App runtime | CPython 3.15.0, Kivy 3.0.0.dev202610251128, rubicon-objc 0.5.7 (from the scratch copy's lock) |
| Simulator | iPhone 17e, iOS 27.0 (24A434), UDID `DC05E5FB-...`; none was booted at the start |
| Device | iPhone 18 Pro Max (iPhone19,3), **iOS 27.2 (24B119)** (from the crash report), team `R5PKSQLUZY` via `KIVYFORGE_TEAM_ID`; the alerts were read by the owner on the phone |

`xcrun simctl` fails inside the agent's sandboxed shell ("CoreSimulatorService
connection became invalid"); every simulator and device command was run
unsandboxed.

## Defects

### D1 (C5): a missing location key does not stop the app

The guide says an app without a description key "is stopped by iOS when it
calls the API". That holds for the camera and is wrong for location.

**Camera, key removed (Step 3.1).** Simulator: the app was killed when
`ask_camera` ran. Crash report
`~/Library/Logs/DiagnosticReports/rubicon-deviceinfo-2026-11-10-163416.000.ips`:

```
exception {"type": "EXC_CRASH", "signal": "SIGABRT"}
termination {
 "namespace": "TCC",
 "details": [
  "This app has crashed because it attempted to access privacy-sensitive data without a usage description. The app's Info.plist must contain an NSCameraUsageDescription key with a string value explaining to the user how the app uses this data."
 ]
}
TCC __TCC_CRASHING_DUE_TO_PRIVACY_VIOLATION__
```

and in the simulator log:

```
2026-11-10 16:34:15.851 E  tccd[73372:7be49b0] [com.apple.TCC:access] Refusing authorization request for service kTCCServiceCamera and subject Sub:{org.kivy.rubicon-deviceinfo}... without NSCameraUsageDescription key
2026-11-10 16:34:15.852 Df launchd_sim[73357:7be494a] [...] exited with exit reason (namespace: 11 code: 0x0) - OS_REASON_TCC | This app has crashed because it attempted to access privacy-sensitive data without a usage description. [...], ran for 10451ms
```

On the device (run 4 below) the result was the same: `run` printed
`App terminated due to signal 6.` and exited 1. The crash report copied from
the phone (`devicectl device copy from --domain-type systemCrashLogs`) has the
same `TCC` termination and the same `NSCameraUsageDescription` sentence,
`iPhone OS 27.2 (24B119)`.

**Location, `NSLocationWhenInUseUsageDescription` removed (Step 3.2),
simulator.** The app did not terminate and no alert appeared (screenshot: the
app's `KFPERM` label, nothing over it). iOS logged one warning and the app
went on to the camera request 7 s later, whose alert appeared normally. No new
crash report; the process was still listed by `launchctl` afterwards.

```
KFPERM location status before 0
2026-11-10 16:35:46.060 rubicon-deviceinfo[78096:129921604] This app has attempted to access privacy-sensitive data without a usage description. The app's Info.plist must contain an “NSLocationWhenInUseUsageDescription” key with a string value explaining to the user how the app uses this data
KFPERM location requested
KFPERM camera status before 0
KFPERM camera requested
```

(`log show` attributes that line to `(CoreLocation)`, at the default level,
not an error.) The built plist had `NSLocationAlwaysAndWhenInUseUsageDescription`
and `NSLocationDefaultAccuracyReduced` but not the when-in-use key, so the
request was refused even though another location key was present.

Contradicts: `docs/guides/guides/cross-platform/permissions.md` lines 59 to 61,
and `docs/design/common/09-native-sidecar-contract.md` lines 27 to 29 ("a
missing usage-description string terminates the app"). Not checked: the
microphone, contacts, photos and Bluetooth without their keys.

### D2 (C4, C6): `NSLocationDefaultAccuracyReduced = true` did not make approximate location the default

Apple's page for the key
([`NSLocationDefaultAccuracyReduced`](https://developer.apple.com/documentation/bundleresources/information-property-list/nslocationdefaultaccuracyreduced),
read 2026-11-10) says that with `true`, "the location authorization prompt will
show a map with an approximate location, and your app will have the Precise
Location toggled off in Settings". The guide says the same in fewer words.
Neither happened on iOS 27.2.

The installed app's `Info.plist` had the key as a real boolean in every run
(`plutil -p .../Debug-iphoneos/rubicon-deviceinfo.app/Info.plist` gives
`"NSLocationDefaultAccuracyReduced" => true`, and `plutil -type` gives `bool`).
kivyforge's part, putting the key in the app, works (C1). What iOS does with it
is the problem.

The app was modified to print `CLLocationManager.authorizationStatus` and
`accuracyAuthorization` every time they change (`accuracyAuthorization`: 0 is
full accuracy, 1 is reduced). The owner tapped **Allow While Using App**
without touching the Precise control. Before each run, the app was uninstalled
with `devicectl device uninstall app`, and each run started from
`status before 0`.

| Device run | Bundle ID | Key | Other location keys | Alert, as read on the phone | Logged after Allow | Settings > Precise Location |
|---|---|---|---|---|---|---|
| 1 (16:42) | `org.kivy.rubicon-deviceinfo` | `true` | Always + `UIBackgroundModes` | "no Precise switch, a map" (the owner was not yet looking for the small label) | `status 4 accuracy 0` | not checked |
| 2 (16:48) | same | `false` | Always + `UIBackgroundModes` | **"Precise: On"**, map zoomed in | `status 4 accuracy 0` | not checked |
| 3 (16:53) | same | `true` | Always + `UIBackgroundModes` | **"Precise: On"**, map zoomed in | `status 4 accuracy 0` | **On** |
| 4 (16:57) | same | `true` | none | **"Precise: On"**, map zoomed in | `status 4 accuracy 0`, then the camera crash of D1 | not checked |
| 5 (17:03) | `org.kivy.kfperm-fresh`, never installed before | `true` | none | **"Precise: On"**, map zoomed in | `status 4 accuracy 0` | **On** |

Run 4 rules out the background-location keys as the cause. Run 5 rules out iOS
remembering an earlier choice for the bundle ID. Run 1's description of the
alert is the only one that differs, and its logged accuracy was full like the
others.

On the simulator the question cannot be asked at all. The location alert has
**no map and no Precise control** with the key `true` or `false` (Step 2
screenshots: title, the usage string, and *Allow Once* / *Allow While Using
App* / *Don't Allow*, identical in both). After the owner tapped Allow While
Using App in the Device Hub window, the app logged
`KFPERM location poll status 4 accuracy 0` with the key `true` and again with
`false`.

Not determined: whether this is iOS 27.2 ignoring the key or something about
this app. Before rewriting the guide, the check that decides it is a native app
from Xcode's iOS App template with the same key on the same phone.

Contradicts: `permissions.md` line 36 (the Approximate location row) and lines
70 to 72 ("`NSLocationDefaultAccuracyReduced = true` makes approximate location
the default").

## Incidental defect, not in the guide

**`run -p ios --device` cannot choose between two paired devices with the same
name, and counts an offline one.** `devicectl list devices` showed
`Elliot's iPhone` (iPhone19,3) `available (paired)` and a second
`Elliot's iPhone` (iPhone14,3) `unavailable`. The first `run --device` failed
with:

```
Error: command failed (1): devicectl
multiple paired iOS devices found ('Elliot’s iPhone', 'Elliot’s iPhone') — pass one explicitly, e.g. `kivyforge run --device --destination 'NAME'`
```

The advice cannot work, because both have that name. `--destination` with the
UDID did work. In `kivyforge/platforms/ios/xcode/runner.py`, the no-destination
path keeps every device whose `pairing_state == "paired"`, whether or not it
is reachable, and the message suggests a name rather than the UDID.
Suggestion, not applied: prefer reachable devices, and name UDIDs in the
message when names collide.

## Step 1 — the keys reach the app (C1, C2): PASS

The ten keys from the prompt were appended to `/tmp/kfperm/pyproject.toml`.

```
$ kivyforge lock -p ios
pylock.ios.toml is already in sync with pyproject.toml.
  (use --update to force re-resolution)
$ kivyforge build -p ios --simulator; echo "exit=$?"
Collecting artifacts for ios_16_0_arm64_iphonesimulator ...
Generated rubicon-deviceinfo-ios
xcodebuild build (simulator) ...
Built rubicon-deviceinfo-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/rubicon-deviceinfo.app
exit=0
$ ls rubicon-deviceinfo-ios/*-Info.plist
rubicon-deviceinfo-ios/rubicon-deviceinfo-Info.plist
```

`plutil -p` on the generated plist and on the built `.app`'s `Info.plist` gave
identical lines for all ten keys:

```
  "NSBluetoothAlwaysUsageDescription" => "KFPERM bluetooth: connect to your heart-rate monitor."
  "NSCameraUsageDescription" => "KFPERM camera: scan the QR code on your ticket."
  "NSContactsUsageDescription" => "KFPERM contacts: invite a friend."
  "NSLocationAlwaysAndWhenInUseUsageDescription" => "KFPERM background location: log your route."
  "NSLocationDefaultAccuracyReduced" => true
  "NSLocationWhenInUseUsageDescription" => "KFPERM location: show your position on the map."
  "NSMicrophoneUsageDescription" => "KFPERM microphone: record a voice note."
  "NSPhotoLibraryAddUsageDescription" => "KFPERM photo add: save the picture you took."
  "NSPhotoLibraryUsageDescription" => "KFPERM photo read: choose a background."
  "UIBackgroundModes" => [
    0 => "location"
  ]
```

`plutil -type` on the built plist: `NSLocationDefaultAccuracyReduced` is `bool`,
`UIBackgroundModes` is `array`. The `.app` is at the path the prompt's `find`
expects, `rubicon-deviceinfo-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/rubicon-deviceinfo.app`.

**Xcode warnings:** none about `UIBackgroundModes`. kivyforge prints only its
own four lines, so the activity log
(`rubicon-deviceinfo-ios/build/DerivedData/Logs/Build/*.xcactivitylog`) was
decompressed and searched. It holds no warning, only one notice: "Run script
build phase 'Run Script' will be run during every build because the option to
run the script phase "Based on dependency analysis" is unchecked.", and
`Build succeeded`.

**Note for the prompt:** `[tool.kivy.ios.info_plist]` is not a lock input, so
every "re-lock" step in Steps 2 and 3 is a no-op (`already in sync` each time).
Editing the key and rebuilding is enough.

## Step 2 — the prompts on the simulator (C3: PASS; C4: cannot be checked here)

The prompt's `main.py` worked as written; no Rubicon change was needed. Run
with `xcrun simctl privacy booted reset all org.kivy.rubicon-deviceinfo`, then
`kivyforge run -p ios --simulator`:

```
KFPERM location status before 0
KFPERM location requested
KFPERM camera status before 0
KFPERM camera requested
```

**Location alert** (about 4 s after launch), word for word:

> Allow "Rubicon Device Info" to use your location?
> KFPERM location: show your position on the map.
> [Allow Once] [Allow While Using App] [Don't Allow]

No map and no Precise control.

**Camera alert** (about 11 s), word for word, with a camera icon:

> Allow "Rubicon Device Info" to access your camera?
> KFPERM camera: scan the QR code on your ticket.
> [Don't Allow] [Allow]

The simulator has no camera, but it shows the camera alert anyway.

With `NSLocationDefaultAccuracyReduced = false` (built plist:
`"NSLocationDefaultAccuracyReduced" => false`) the location alert was the same,
to the word, still with no map and no Precise control. C4 cannot be checked on
the simulator; see D2 for the device.

**Two things that confused the first attempt:**

- An unanswered alert outlives the app. After `simctl terminate`, the next
  run's first screenshot showed the *previous* run's camera alert over the new
  location alert. In Step 3.1 the location alert was still on screen over the
  home screen after iOS had killed the app. Shutting the simulator down and
  booting it again before each run (with the privacy reset) gave clean
  screenshots.
- Kivy's clock kept running while the location alert was up. The camera
  request fired on schedule at 10 s, so the camera alert stacked on top of the
  location alert.

For C4 the app was changed to print `authorizationStatus` and
`accuracyAuthorization` whenever they change. The camera delay was moved to
`KFPERM_CAMERA_DELAY` (passed as `SIMCTL_CHILD_KFPERM_CAMERA_DELAY=600`, which
`simctl launch` forwards). For the device, the app asks for the camera 3 s
after the location answer instead, because `devicectl` does not forward that
variable. The owner answered the alert in the Device Hub window (opened with
`open devices://device/open?id=<udid>`), because Computer Use needs Screen
Recording, which is not granted.

## Step 3 — a missing usage description (C5): FAIL for location

See D1. The camera crashes, as the guide says. Location does not.

## Step 4 — on a device (C6): C3 and C5 PASS on the device; C4 FAIL

`kivyforge run -p ios --device --destination 00008160-0001192601A0000A`, with
the phone unlocked (the first launch failed with `BSErrorCodeDescription =
Locked`, the known gotcha). Typical output:

```
Installing on device Elliot’s iPhone (0F7D0110-FDC1-5CB2-8880-8D1E626C7C0F) ...
Launching org.kivy.rubicon-deviceinfo ...
Launched application with org.kivy.rubicon-deviceinfo bundle identifier.
Waiting for the application to terminate…
KFPERM location poll status 0 accuracy 0
KFPERM location status before 0
KFPERM location requested
KFPERM location poll status 4 accuracy 0
KFPERM camera status before 0
KFPERM camera requested
KFPERM camera granted True
```

- **Location alert:** showed the `KFPERM location: ...` string and a map with
  a "Precise: On" label. For the key `true`, see D2.
- **Camera alert:** the owner confirmed `KFPERM camera: scan the QR code on
  your ticket.` word for word in runs 2 and 3. In run 1 the owner did not
  notice it.
- **Answering logs status:** `status 4` once location was allowed, and
  `KFPERM camera granted True` from the completion block, which Rubicon's
  `Block(..., None, bool)` delivered as a Python `bool`.
- **Step 3.1 repeated** (run 4): killed with `signal 6`; reason as in D1.

## Step 5 — reading the iOS half of the guide

Read `permissions.md` and `ios/configure.md`'s "Declare permissions". The key
names match Apple's current documentation. None of the capabilities in the
tables needs an entitlement or an Xcode capability on top of its key, except
as noted below. Apart from D1 and D2:

- **"the system asks the first time your app uses the protected API"** (line
  139). Every prompt in this run came from an explicit request
  (`requestWhenInUseAuthorization`, `requestAccessForMediaType:`). Whether
  merely *using* the API prompts was not tested. For location, Apple has the
  app call a request method. The answer also stuck: each run needed an
  uninstall or a privacy reset to see the prompt again.
- **Verify, iOS tab:** "use each capability once, to confirm that the system
  asks" only works on a fresh install. The page does not say how to reset, and
  it does not say that the simulator's location prompt has no map or Precise
  control.
- **Notifications, "Nothing to declare":** right for `info_plist`, but remote
  push needs `aps-environment` under `[tool.kivy.ios.entitlements]` (see
  [`lifecycle-hooks.md`](../../guides/guides/ios/lifecycle-hooks.md)). Not
  tested here; a pointer would help.
- **Bluetooth:** background Bluetooth also needs
  `UIBackgroundModes = ["bluetooth-central"]` (or `-peripheral`). Not in the
  guide and not tested; worth a sentence if the page aims to cover background
  use, as it does for location.
- Not exercised at run time: the microphone, Bluetooth, contacts and photo
  keys, the background-location row and the photo picker. Only their presence
  in `Info.plist` (Step 1) was checked.

## Doc corrections (proposed, not applied)

1. **`docs/guides/guides/cross-platform/permissions.md`, lines 59 to 61.**
   Wrong: "an app that uses a protected API without its description key is
   stopped by iOS when it calls the API." True: "if the description key is
   missing, iOS does not ask. For the camera it terminates the app when the app
   requests access. For location it logs a warning and the request does
   nothing, so the app never gets access." (The camera and location were
   checked; other capabilities were not.)
2. **`docs/design/common/09-native-sidecar-contract.md`, lines 27 to 29.**
   Wrong: "a missing usage-description string terminates the app." True: "a
   missing usage-description string terminates the app (the camera) or
   silently withholds access (location, with only a log warning)". The
   paragraph's point, that the gap is sharper on iOS, still stands; a silent
   no-op is, if anything, harder to notice.
3. **`permissions.md`, line 36 and lines 70 to 72.** Wrong, as observed on iOS
   27.2: "`NSLocationDefaultAccuracyReduced = true` makes approximate location
   the default." True: Apple documents that effect, but on iOS 27.2 the prompt
   still started at "Precise: On" and iOS granted full accuracy (D2). Hold the
   rewrite until the native-app check in D2 says whether the key or this app is
   at fault. Until then, the lowest-risk text is to keep the key, attribute the
   behaviour to Apple's documentation, and add that the user picks the accuracy
   in the prompt and can change it in Settings.
4. **`permissions.md`, line 139.** Wrong in its implication: "the system asks
   the first time your app uses the protected API." True: "the system asks
   when your app first requests access (for location, the app calls
   `requestWhenInUseAuthorization`), and only once; after that the answer
   stands until the app is deleted or the user changes it in Settings."
5. **`permissions.md`, Verify, iOS tab (after line 159).** Missing: "The
   system asks only once per install. To see the prompt again, delete the app,
   or on the simulator run
   `xcrun simctl privacy booted reset all <bundle_id>`. The simulator's
   location prompt has no map or Precise control, so check location accuracy
   on a device."
6. **`permissions.md`, line 41 (Notifications).** Optional: link to the push
   entitlement in [`lifecycle-hooks.md`](../../guides/guides/ios/lifecycle-hooks.md).

No correction is needed for C1 or C2: the Verify commands and the
`<app>-ios/<app>-Info.plist` path are right as written.

## Clean-up

Both scratch apps (`org.kivy.rubicon-deviceinfo` and `org.kivy.kfperm-fresh`)
were uninstalled from the phone and the simulator was shut down. `/tmp/kfperm`
is outside the repo and nothing from it was committed.
