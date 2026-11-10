# Agent prompt — check the iOS half of the permissions guide, on the Mac

> **Run this on the Mac**, from the repo root, on branch
> `android-permission-attributes`. Written 2026-11-10 from the Windows host,
> where none of it can run.
>
> Point the agent at this file, or copy the "Prompt" section. Results go in
> `permissions-docs-ios-findings.md` beside it, in the shape of
> [`macos-ios-validation-findings.md`](macos-ios-validation-findings.md):
> environment table, per-step commands and verbatim output, defects first.

## Background — what changed, and what only a Mac can prove

Issue [#222](https://github.com/ElliotGarbus/kivyforge/issues/222) asked for a
shared `[tool.kivy.permissions]` table that kivyforge would expand into Android
manifest entries and iOS `Info.plist` keys. It was not built: Bluetooth,
background location and photos do not map cleanly between the platforms. Two
things landed instead:

1. **Android `uses` entries can carry attributes**
   (`{ name, max_sdk_version, uses_permission_flags }`). Verified on a Pixel 8a
   (API 37) and an API 30 emulator, 2026-11-10 (`test-matrix.md` §7).
   Nothing for the Mac to do here.
2. **A guide,
   [`docs/guides/guides/cross-platform/permissions.md`](../../guides/guides/cross-platform/permissions.md)**,
   pairing each capability's Android `uses` entries with its iOS
   `[tool.kivy.ios.info_plist]` keys, and a short "Declare permissions" section
   in [`docs/guides/guides/ios/configure.md`](../../guides/guides/ios/configure.md).
   **No iOS code changed.** The iOS claims were written from Apple's
   documentation and have not been run. This prompt checks them.

The claims to confirm or refute, each tied to a step below:

| # | Claim in the guide | Step |
|---|---|---|
| C1 | Each iOS key in the capability and photo tables reaches the built app's `Info.plist` as written, including `NSLocationDefaultAccuracyReduced = true` and `UIBackgroundModes = ["location"]`. | 1 |
| C2 | The Verify section's commands and paths are right: `kivyforge build -p ios --simulator`, then `<app>-ios/<app>-Info.plist`. | 1 |
| C3 | "The system asks the first time your app uses the protected API", and the prompt shows the usage description. | 2 |
| C4 | `NSLocationDefaultAccuracyReduced = true` makes approximate location the default (the prompt's Precise switch starts off). | 2 |
| C5 | "An app that uses a protected API without its description key is stopped by iOS when it calls the API." Suspected to be **too broad**: true for the camera, probably not for location, where iOS is believed to ignore the request and log a warning. | 3 |
| C6 | The same behaviours on a device. | 4 (optional) |

Read [`test-matrix.md`](test-matrix.md) §7 before starting.

---

## Prompt

You are checking the iOS claims in kivyforge's permissions guide on the Mac.
Work through the steps in order. Record the actual output of each check; do
not summarise a step as passing without the evidence in front of you. If a step
fails, capture the full error and continue with the independent steps.
**Report defects first.** Do not change code or docs in this run; findings
only. Propose each doc correction as text in the findings.

### Step 0 — environment, as evidence

```bash
git fetch && git switch android-permission-attributes && git pull
git log -1 --oneline
sw_vers; xcodebuild -version
.venv/bin/kivyforge --version; .venv/bin/python -V
xcrun simctl list devices booted
```

### Step 1 — the keys reach the app (C1, C2)

Work on a scratch copy of `examples/mobile/rubicon-deviceinfo`. Its lock is
gitignored, so re-locking the copy is fine:

```bash
rm -rf /tmp/kfperm && cp -R examples/mobile/rubicon-deviceinfo /tmp/kfperm && cd /tmp/kfperm
rm -rf rubicon-deviceinfo-ios
```

Append to `/tmp/kfperm/pyproject.toml` every iOS key the guide names:

```toml
[tool.kivy.ios.info_plist]
NSCameraUsageDescription = "KFPERM camera: scan the QR code on your ticket."
NSMicrophoneUsageDescription = "KFPERM microphone: record a voice note."
NSLocationWhenInUseUsageDescription = "KFPERM location: show your position on the map."
NSLocationAlwaysAndWhenInUseUsageDescription = "KFPERM background location: log your route."
NSLocationDefaultAccuracyReduced = true
UIBackgroundModes = ["location"]
NSBluetoothAlwaysUsageDescription = "KFPERM bluetooth: connect to your heart-rate monitor."
NSContactsUsageDescription = "KFPERM contacts: invite a friend."
NSPhotoLibraryAddUsageDescription = "KFPERM photo add: save the picture you took."
NSPhotoLibraryUsageDescription = "KFPERM photo read: choose a background."
```

Then:

```bash
kivyforge lock -p ios
kivyforge build -p ios --simulator; echo "exit=$?"
ls rubicon-deviceinfo-ios/*-Info.plist
plutil -p rubicon-deviceinfo-ios/rubicon-deviceinfo-Info.plist | grep -E "Usage|Accuracy|UIBackgroundModes" -A2
APP=$(find rubicon-deviceinfo-ios/build -name "*.app" -path "*iphonesimulator*" | head -1); echo "$APP"
plutil -p "$APP/Info.plist" | grep -E "Usage|Accuracy|UIBackgroundModes" -A2
```

Expected: the build exits 0; the generated plist sits at
`rubicon-deviceinfo-ios/rubicon-deviceinfo-Info.plist`, as the guide's Verify
section says; and both it and the built app's `Info.plist` hold all ten keys,
with `NSLocationDefaultAccuracyReduced` a boolean `true` and `UIBackgroundModes`
an array holding `location`. Record any warning Xcode prints about
`UIBackgroundModes`. If the `.app` is not under that path, find it and record
where it is.

### Step 2 — the prompts on the simulator (C3, C4)

Replace `/tmp/kfperm/src/main.py` with an app that asks for location and then
the camera a few seconds after it starts, so no tap is needed to trigger them.
A starting point; adjust the Rubicon calls if they do not work as written, and
record what you changed:

```python
"""KFPERM: request location, then the camera, and log the result."""

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.label import Label
from rubicon.objc import Block, ObjCClass
from rubicon.objc.runtime import load_library

load_library("CoreLocation")
load_library("AVFoundation")
CLLocationManager = ObjCClass("CLLocationManager")
AVCaptureDevice = ObjCClass("AVCaptureDevice")
VIDEO = "vide"  # AVMediaTypeVideo


class PermApp(App):
    def build(self):
        self.manager = CLLocationManager.alloc().init()  # keep a reference
        return Label(text="KFPERM")

    def on_start(self):
        Clock.schedule_once(self.ask_location, 3)
        Clock.schedule_once(self.ask_camera, 10)

    def ask_location(self, _dt):
        print("KFPERM location status before", self.manager.authorizationStatus)
        self.manager.requestWhenInUseAuthorization()
        print("KFPERM location requested")

    def ask_camera(self, _dt):
        print("KFPERM camera status before",
              AVCaptureDevice.authorizationStatusForMediaType(VIDEO))
        AVCaptureDevice.requestAccessForMediaType(
            VIDEO,
            completionHandler=Block(
                lambda granted: print("KFPERM camera granted", granted), None, bool
            ),
        )
        print("KFPERM camera requested")


PermApp().run()
```

Reset the app's privacy state so the prompts appear, then run:

```bash
xcrun simctl privacy booted reset all org.kivy.rubicon-deviceinfo
kivyforge run -p ios --simulator
```

While it runs, take a screenshot once each alert is up (about 4 s and 11 s
after launch):

```bash
xcrun simctl io booted screenshot /tmp/kfperm-location.png
xcrun simctl io booted screenshot /tmp/kfperm-camera.png
```

Record: the `KFPERM` lines from the console; whether each alert appeared; the
alert text, word for word, which should contain the `KFPERM ...` usage string;
and for location, whether the alert shows a **Precise** switch and whether it
starts **off** (C4). Attach or describe the screenshots. If the camera alert
does not appear on the simulator (it has no camera), record that and leave the
camera to Step 4. Answering the alerts is not needed.

Then set `NSLocationDefaultAccuracyReduced = false`, re-lock and re-run with
the privacy reset, and record whether Precise now starts **on**.

### Step 3 — a missing usage description (C5)

Restore `NSLocationDefaultAccuracyReduced = true`. Then, one at a time:

1. Delete `NSCameraUsageDescription`, re-lock, reset privacy, run. Record
   whether the app terminates when `ask_camera` runs, and the log line iOS
   gives as the reason. Expected: a crash with "attempted to access
   privacy-sensitive data without a usage description" or similar. Use
   `xcrun simctl spawn booted log show --last 2m --predicate 'process == "rubicon-deviceinfo"'`
   if the console does not show it. Put the key back.
2. Delete `NSLocationWhenInUseUsageDescription` (keep the camera key), re-lock,
   reset privacy, run. Record whether the app terminates, whether any alert
   appears, and any warning logged. Put the key back.

If location does **not** terminate the app, the guide's sentence "an app that
uses a protected API without its description key is stopped by iOS when it
calls the API" is wrong as written. Propose a correction in the findings. The
same claim appears in
[`09-native-sidecar-contract.md`](../common/09-native-sidecar-contract.md)
§"Why kivyforge wants it" ("a missing usage-description string terminates the
app"); the correction covers both.

### Step 4 — on a device (C6, optional)

Only if a device and signing are available (see
[`docs/guides/guides/ios/signing.md`](../../guides/guides/ios/signing.md)). Add
your team to the scratch copy's `[tool.kivy.ios.signing].team_id` or pass
`--team-id`, then:

```bash
kivyforge run -p ios --device
```

Record, on the phone: the location alert's text and its Precise switch; the
camera alert's text; and that answering each logs `KFPERM` status lines. Repeat
Step 3.1 (camera key removed) if you can. If no device is available, say so and
stop here.

### Step 5 — read the iOS half of the guide

Read `docs/guides/guides/cross-platform/permissions.md` and the "Declare
permissions" section of `docs/guides/guides/ios/configure.md` as a reader would.
Record anything wrong or missing for iOS, for example a key named differently
in Apple's current documentation, a capability whose iOS row needs more than
the key (an entitlement or a capability in the Xcode project), or a claim
contradicted by Steps 1 to 4.

### Step 6 — report

Write `docs/design/dev/permissions-docs-ios-findings.md`:

1. Environment table.
2. **Defects** first: for each, the claim number, the command, the verbatim
   output, and the page it contradicts.
3. Per step: commands and verbatim output (trim build logs to the relevant
   lines; keep every error in full).
4. Doc corrections as a list of page, wrong text, and what is true.

Then add a dated entry to [`test-matrix.md`](test-matrix.md) §7 for what ran,
and commit **only** the findings doc and the test-matrix entry. Do not commit
anything from `/tmp/kfperm`. Ask before pushing.
