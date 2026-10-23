# Findings — `include_files` spikes for iOS

> 2026-10-22, macOS host. Spikes for
> [`include-files-proposal.md`](include-files-proposal.md), all done:
> 1 (incremental pruning), 2 (iOS file placement; the Settings app's pane
> for `Settings.bundle` was not seen, only the bundle itself), 3 (macOS
> signing per `Contents/` location), 4 (forcing top-level files into Copy
> Bundle Resources), 5 (iOS signing and installation on a phone),
> 6 (macOS notarization), 7 (iOS Release archive and IPA export) and
> 8 (iOS reading unprocessed includes).

## Defects and design changes first

1. **`pbxproj` decides a file reference's build phase by extension**, and not
   every extension goes to Copy Bundle Resources. A top-level `helper.py`
   include was put in Sources; Xcode warned "no rule to process file" and
   the build **succeeded without it in the `.app`**. `.c`, `.m`, `.swift`
   and nine more go to Sources too, `.h` to Headers, `.a` and `.dylib` to
   Frameworks, and an extension `pbxproj` does not know (`.caf`, the usual
   notification-sound format) raises `ValueError` unless
   `ignore_unknown_type=True`. The proposal's wiring must put every top-level
   file in Copy Bundle Resources itself (spike 2).
2. **`PkgInfo` is a generated name.** Add it to the reserved list (spike 2).
3. **A top-level `.plist` or `.strings` is converted to a binary plist**
   when the reference's type comes from its extension. Files inside a folder
   reference are copied verbatim (spikes 1 and 2). Finding 6 shows how to
   avoid the conversion.

4. **The proposal's reason for the macOS allowed roots was wrong, and its
   rule is right.** A data file in `Contents/MacOS/` does not "sign and then
   break when a zip drops its extended attributes": it makes signing fail,
   with an error naming the main executable rather than the include. Every
   place outside `Resources/`, `SharedSupport/` and `Library/` that was tried
   failed the same way (spike 3).
5. **A Mach-O under `Resources/` signs and verifies**, ad hoc and with
   Developer ID, so refusing native code in a macOS include is a design
   choice, not a `codesign` constraint (spike 3).
6. **Putting a top-level file in Copy Bundle Resources is not enough.**
   Xcode still picks the action by extension: `.swift`, `.c` and `.m` were
   dropped with only a warning, and the build exited 0. Setting
   `explicitFileType` on the reference makes Xcode copy every non-code file
   byte for byte, `.plist` and `.strings` included, which replaces finding 3:
   the bundle's copy can be checked against the pinned SHA-256. A `.a` is
   run through `strip` whatever the type says (spike 4).
7. **A top-level folder named `*.framework` gets a binary.** Xcode compiles
   a stub dylib into a codeless framework folder, even one copied as a
   resource. Refuse code-bundle extensions on a top-level iOS `dest`, and
   reserve `PlugIns/` (spike 5).
8. **On iOS a Mach-O include is stripped and left unsigned**, so refusing
   native code is required there, not just a choice. iOS signing itself
   accepted every placement tried, on a phone too (spike 5).
9. **Apple notarized a bundle with an include in each allowed macOS root**,
   plus a Mach-O under `Resources/`, with no issues logged (spike 6). No
   change to the proposal.
10. **A Release archive and every IPA export method keep the includes byte
    for byte** and verify; the development IPA installed on the phone
    (spike 7). **iOS reads the unprocessed XML plist and text `.strings`**
    (spike 8). No change to the proposal.

Nothing found argues against the proposal's placement rule: every file
landed where `dest` said, and iOS read each one (spike 2).

## Environment

| Item | Value |
|---|---|
| Host | macOS 26.6.2 (25G83), arm64 |
| Xcode | 27.0 (27A266a), iPhoneSimulator SDK 27.0 |
| `pbxproj` | 4.3.3, from the repo's `.venv` |
| kivyforge | `main` at `87d1475d`, for `skeleton_pbxproj()` only |
| Signing (spike 3) | `codesign` from macOS 26.6.2; Apple clang 21.0.0; the owner's Developer ID Application identity, and ad hoc; Apple's timestamp server reached |
| Simulators (spike 2) | iPhone Air, iOS 27.0, already booted; iPhone 17, iOS 27.0, booted fresh for the Settings attempt and shut down after |
| Notary (spike 6) | the `kivyforge-notary` keychain profile for the owner's team; Apple's notary service and timestamp server reached |
| Device (spike 5) | iPhone 18 Pro Max (iPhone19,3), iOS 27.0.1, paired; the owner's Apple Development identity, automatic signing; iPhoneOS SDK 27.0 |

## Spike 1 — does an incremental build prune deleted resources?

**Question.** The proposal's verification step 3 flagged a risk: if Xcode does
not remove a resource from the built `.app` when its input goes away, a
removed include would keep shipping until a clean build, and `build` would
have to delete the stale path itself. The same question applies to `app/`
today, since it is also a folder reference.

**Setup.** A scratch project, not in the repo (`/tmp/kf-prune-spike/spike.py`).
It parses kivyforge's own `skeleton_pbxproj()` and wires resources with the
same `pbxproj` calls the generator uses: `add_file(..., tree="SOURCE_ROOT",
file_options=FileOptions(embed_framework=False))`, then
`set_last_known_file_type("folder")` for a folder reference, as
`_sync_bundle_folders` does for `app/`. Settings added for a bare app:
`GENERATE_INFOPLIST_FILE=YES`, `CODE_SIGNING_ALLOWED=NO`,
`IPHONEOS_DEPLOYMENT_TARGET=15.0`. Built the way
`xcode/commands.py` builds a simulator app:

```bash
xcodebuild -project proj/Spike.xcodeproj -scheme Spike -configuration Debug \
  -sdk iphonesimulator -derivedDataPath dd ARCHS=arm64 ONLY_ACTIVE_ARCH=NO build
```

Inputs:

- file references `Include/top.plist` and `Include/extra.json`, which land at
  the bundle root;
- folder references `Include/Folder/` (holding `a.txt`, `b.txt`, `sub/c.txt`)
  and `Include/Gone/` (holding `g.txt`);
- a folder reference `app`, a symlink to `../src`, exactly as `<app>-ios/app`
  is, with `main.py`, `old.py` and `pkg/mod.py`.

**Build 1** (clean) put every file in the `.app`.

**Build 2** (incremental), after:

- removing the `extra.json` file reference and the `Gone` folder reference
  from the project, and deleting both from disk;
- deleting `Folder/b.txt` and `Folder/sub/`, editing `Folder/a.txt` and adding
  `Folder/new.txt`;
- deleting `src/old.py` and `src/pkg/`.

`main.m` was not recompiled and the binary was not re-linked, so the build
was incremental. The log shows how the removed references were handled:

```
note: Removed stale file 'dd/Build/Products/Debug-iphonesimulator/Spike.app/Gone'

note: Removed stale file 'dd/Build/Products/Debug-iphonesimulator/Spike.app/extra.json'
```

and `CpResource` re-ran for `Folder` and for `app`. The bundle afterwards:

```
Folder/a.txt        (content "a v2")
Folder/new.txt
Info.plist
PkgInfo
Spike
app/main.py
top.plist
```

Nothing that was deleted survived.

**Build 3** (incremental), after deleting only `Folder/new.txt`, so that a
real (not symlinked) folder had a deletion and no other change. `CpResource`
re-ran for `Folder` alone, and `Folder/` in the bundle held only `a.txt`.

### Result

**The risk does not exist on Xcode 27.** Xcode removes the output of a
reference that is no longer in the project ("Removed stale file"), and
re-copies a folder reference as a whole whenever anything under it changes,
deletions included, symlinked or not. So:

- `build` needs no pruning of the built product. Removing a reference for an
  include that is gone is enough.
- `app/` does not keep a deleted `.py` in an incremental build. No defect in
  the current backend.

Not covered: any Xcode before 27 (the documented minimum is Xcode 15), device
and Release builds. An archive is built in its own intermediates, so it is not
exposed to an incremental product anyway.

### Observed along the way

A top-level `.plist` file reference is **not copied byte for byte**. Xcode
runs `CopyPlistFile` on it, and the bundle's `top.plist` is an
`Apple binary property list` with the same content (`plutil -p` gives
`{"K" => "v1"}`). Anything that reads it with `NSDictionary` or
`PropertyListSerialization`, which includes Firebase, is unaffected. But it
means "the bundle's copy matches the pinned SHA-256" is not a valid check for
a top-level plist, and the proposal's verification step 1 ("the plist
unchanged") has to say "the same content". Files inside a folder reference
were copied verbatim (`CpResource`). Spike 2 covers `.strings`, which Xcode
also converts.

## Spike 2 — does iOS read the files where the proposal puts them?

**Question.** With the proposal's wiring (each top-level entry of `Include/`
becomes a file reference, or a folder reference if it is a directory), do the
files the section 4.2 use cases need actually work on iOS: Firebase's plist,
translated `Info.plist` strings, `Settings.bundle`, a sound file? And does
Xcode refuse an include named like a generated file?

**Setup.** A scratch project, not in the repo (`/tmp/kf-place-spike/spike.py`),
built as in spike 1, with code signing on (ad hoc, `CODE_SIGN_IDENTITY=-`).
The app is a small UIKit app with a scene delegate and an explicit
`Info.plist` (not in Copy Bundle Resources): `CFBundleDisplayName` =
`SpikeBASE`, `NSLocationWhenInUseUsageDescription` =
`BASE reason from Info.plist`, `CFBundleDevelopmentRegion` = `en`. Its
`KF_MODE` environment variable picks one of three modes: print what
`NSBundle` finds and exit, request location permission, or open its own
Settings pane.

| Include (under `Include/`) | `dest` in proposal terms | Reference |
|---|---|---|
| `GoogleService-Info.plist` (XML, `API_KEY`, `BUNDLE_ID`) | `.` | file |
| `TopLevel.strings` (text) | `.` | file |
| `chime.caf` | `.` | file |
| `helper.py` | `.` | file |
| `en.lproj/InfoPlist.strings`, `en.lproj/Localizable.strings` (text, UTF-8) | `en.lproj` | folder |
| `Settings.bundle/Root.plist`, `Settings.bundle/en.lproj/Root.strings` | `Settings.bundle` | folder |

### What `pbxproj` did with them

```
ref Include/chime.caf: type=None phases=['PBXResourcesBuildPhase']
ref Include/TopLevel.strings: type=text.plist.strings phases=['PBXResourcesBuildPhase']
ref Include/Settings.bundle: type=folder phases=['PBXResourcesBuildPhase']
ref Include/en.lproj: type=folder phases=['PBXResourcesBuildPhase']
ref Include/GoogleService-Info.plist: type=text.plist.xml phases=['PBXResourcesBuildPhase']
ref Include/helper.py: type=sourcecode.python phases=['PBXSourcesBuildPhase']
```

The first run stopped at `chime.caf`:

```
ValueError: Unknown file extension: .caf. Please add the extension and Xcode type to ProjectFiles._FILE_TYPES
```

so the run above used `FileOptions(embed_framework=False,
ignore_unknown_type=True)`, which leaves the type unset and puts the file in
Copy Bundle Resources. `pbxproj`'s map
(`ProjectFiles._FILE_TYPES`) sends `.S .as .asm .c .cpp .d .j .m .mlmodel .mm
.py .swift .xcconfig .xcdatamodeld` to Sources, `.h .hpp .inl .pch` to
Headers and `.a .dylib .framework .tbd .xcframework` to Frameworks. A
directory becomes `folder` unless its extension is one of `.bundle
.framework .xcframework .xcodeproj .xcassets .xcdatamodeld .storyboardc`;
the spike set `folder` on every directory, as the proposal does.

### The build

`xcodebuild` exited 0, with one warning:

```
warning: no rule to process file '/tmp/kf-place-spike/proj/Include/helper.py' of type 'text.script.python' for architecture 'arm64' (in target 'Spike2' from project 'Spike2')
```

The `.app`, without `_CodeSignature/`:

```
GoogleService-Info.plist
Info.plist
PkgInfo
Settings.bundle/Root.plist
Settings.bundle/en.lproj/Root.strings
Spike2
TopLevel.strings
chime.caf
en.lproj/InfoPlist.strings
en.lproj/Localizable.strings
```

`helper.py` is missing: a top-level include with a source-code extension
does not ship, and the build does not fail.

Compared with the inputs:

| File in the `.app` | Copy |
|---|---|
| `GoogleService-Info.plist` | Apple binary property list |
| `TopLevel.strings` | Apple binary property list |
| `en.lproj/InfoPlist.strings` | verbatim |
| `en.lproj/Localizable.strings` | verbatim |
| `Settings.bundle/Root.plist` | verbatim |
| `Settings.bundle/en.lproj/Root.strings` | verbatim |

### At runtime

Report mode, via `simctl launch --console-pty`:

```
KF-SPIKE preferredLocalizations=en localizations=en
KF-SPIKE GoogleService-Info found=yes BUNDLE_ID=org.kivyforge.spike2 API_KEY=AIzaSpikeKey
KF-SPIKE CFBundleDisplayName=SpikeEN
KF-SPIKE NSLocationWhenInUseUsageDescription=TRANSLATED reason from en.lproj
KF-SPIKE localizedInfoDictionary=CFBundleDisplayName,NSLocationWhenInUseUsageDescription
KF-SPIKE Localizable.greeting=hello from en.lproj
KF-SPIKE TopLevel.k=top-level strings file
KF-SPIKE Settings.bundle found=yes specifiers=2
KF-SPIKE chime.caf found=yes
```

- **Firebase's plist** is found the way `FirebaseApp.configure()` finds it
  (`pathForResource:@"GoogleService-Info" ofType:@"plist"`), and reads back
  with its values despite the binary conversion.
- **Translated `Info.plist` strings** in a verbatim-copied text
  `en.lproj/InfoPlist.strings` override the base values.
- **`Localizable.strings`** in the same folder, and a top-level
  (binary-converted) `.strings`, both resolve.
- **`Settings.bundle`** is found and its `Root.plist` parses, with both
  specifiers.

Location mode, after `simctl privacy booted reset location`: the system
prompt read **Allow "SpikeEN" to use your location?** with the reason
**TRANSLATED reason from en.lproj**. So iOS itself, not just `NSBundle` in
the app, uses the translated strings, for the app name and for the
permission reason.

Settings mode: `openURL:UIApplicationOpenSettingsURLString` opened the
Settings app at its root page, not at the app's pane, four times: twice on
the iPhone Air (where the location alert from the previous run also stayed on
screen) and twice on a freshly booted iPhone 17. Stopped there. Whether the
Settings app shows the pane built from `Settings.bundle` is **not
verified**. That needs someone to tap Settings, then Apps, then SpikeEN.

### Generated names as includes

`spike.py collide` added a top-level `Info.plist`, then a top-level `PkgInfo`,
each as a file reference. Both builds failed with exit 65:

```
error: Multiple commands produce '/tmp/kf-place-spike/dd/Build/Products/Debug-iphonesimulator/Spike2.app/Info.plist'
error: Multiple commands produce '/tmp/kf-place-spike/dd/Build/Products/Debug-iphonesimulator/Spike2.app/PkgInfo'
```

As the proposal expected, Xcode refuses the collision, and the error does not
mention the include. `PkgInfo`, written by `ProcessInfoPlistFile`, was not in
the proposal's reserved list.

### Result

The placement rule works for every use case tried. Three changes to the
proposal: wire every top-level file into Copy Bundle Resources whatever its
extension, add `PkgInfo` to the reserved names, and compare content, not
bytes, for converted files. Not covered: the Settings pane, a real sound
played by a notification, a device build, an Xcode before 27.

## Spike 3 — which places under `Contents/` survive signing?

**Question.** The proposal limits a macOS `dest` to `Resources`,
`SharedSupport` and `Library`, on the theory that data elsewhere signs but
then breaks when a zip drops its extended attributes. Is that the right set,
and the right reason? And does a Mach-O under `Resources/` sign, given that
the proposal refuses one?

**Setup.** A scratch script, not in the repo (`/tmp/kf-sign-spike/spike.py`).
For each placement it builds a fresh minimal `.app`:

- `Contents/Info.plist`;
- `Contents/MacOS/Spike3`, a `clang -arch arm64` build of
  `int main(void) { return 0; }`;
- `Contents/Resources/app/main.py`;
- plus one included file: a small JSON file, a `.strings` for the `.lproj`
  case, or a copy of the executable for the Mach-O case.

It signs with kivyforge's own `sign_bundle_adhoc()` and
`sign_bundle_developer_id()` (every Mach-O inside out, then the bundle;
Developer ID with `--options runtime --timestamp` and the default
entitlements). It then runs `codesign --verify --deep --strict --verbose=2`
on the bundle, and again after two round trips: `zip -qry` then `unzip`
(Info-ZIP, which drops extended attributes), and `ditto -c -k --keepParent`
then `ditto -x -k` (which keeps them). The only extended attribute on any
included file was `com.apple.provenance`.

### Results

Ad hoc and Developer ID gave the same result in every row. The Developer ID
run took about three minutes, all of it secure timestamps.

| Included file | Sign | Verify | After `zip` | After `ditto` |
|---|---|---|---|---|
| `Contents/Resources/data.json` | ok | pass | pass | pass |
| `Contents/Resources/en.lproj/InfoPlist.strings` | ok | pass | pass | pass |
| `Contents/Resources/dir.with.dots/data.json` | ok | pass | pass | pass |
| `Contents/SharedSupport/data.json` | ok | pass | pass | pass |
| `Contents/Library/data.json` | ok | pass | pass | pass |
| `Contents/data.json` | **fails** | | | |
| `Contents/MacOS/data.json` | **fails** | | | |
| `Contents/Frameworks/data.json` | **fails** | | | |
| `Contents/PlugIns/data.json` | **fails** | | | |
| `<app>.app/data.json`, beside `Contents/` | **fails** | | | |
| `Contents/Resources/helper`, a Mach-O | ok | pass | pass | pass |

Each failure came from the `codesign` call on the main executable, which
seals the bundle. For the four inside `Contents/`, for example:

```
codesign failed (1): Spike3.app/Contents/MacOS/Spike3: replacing existing signature
Spike3.app/Contents/MacOS/Spike3: code object is not signed at all
In subcomponent: Spike3.app/Contents/MacOS/data.json
```

and beside `Contents/`:

```
Spike3.app/Contents/MacOS/Spike3: unsealed contents present in the bundle root
```

### Result

**The allowed set is right, and the reason is not.** Nothing signed and then
broke: every placement either failed to sign or passed every check, zip
included. Outside the three allowed roots, `codesign` treats anything it finds
as a nested code object, and a data file is not one. So the backend must
refuse these placements before signing. Otherwise the user gets a signing
error about the main executable, with no mention of `include_files`.

**A Mach-O under `Resources/` is fine as far as `codesign` is concerned**, with
either identity, which matches the existing `Resources/bin/` channel. The
proposal's refusal stands as a choice: native binaries already have a channel
with pinning, `PATH` registration and an arch check.

Not covered here: notarization (spike 6 did it), Hardened Runtime launch of an app that reads an
include, an Intel or universal binary, and `Contents/Library/LoginItems`,
`Contents/PlugIns` or `Contents/Helpers` holding real code.

## Spike 4 — can every top-level file be forced into Copy Bundle Resources?

**Question.** Spike 2 found that `pbxproj` picks a build phase by extension, so
a top-level `helper.py` went to Sources and never reached the `.app`. The
proposal's answer is to put every top-level file in Copy Bundle Resources
itself. Does Xcode then copy each one, whatever its extension?

**Setup.** A scratch script, not in the repo (`/tmp/kf-wire-spike/spike.py`).
It starts from `skeleton_pbxproj()` plus an empty `main.m`, then adds each
include with
`add_file(rel, tree="SOURCE_ROOT", file_options=FileOptions(create_build_files=False, ignore_unknown_type=True, embed_framework=False))`,
creates a `PBXBuildFile` for the reference with `PBXBuildFile.create(ref)`,
and adds it to the target's `PBXResourcesBuildPhase` with `add_build_file()`.
After saving and reloading, the Resources phase held every include, and the
Sources, Headers and Frameworks phases held none. It builds with the same
`xcodebuild ... -sdk iphonesimulator` line as spike 1, then compares each file
in the `.app` with its input.

Three variants of the file reference:

- **typed**: `lastKnownFileType` as `pbxproj` set it (`sourcecode.python`,
  `sourcecode.c.h`, `archive.ar`, and so on, or none for `.caf` and `.sh`);
- **neutral**: `lastKnownFileType = file` on every reference;
- **explicit**: no `lastKnownFileType`, and `explicitFileType` set to `text`,
  then rerun with `file`.

### Results

`typed` and `neutral` gave identical output: Xcode ignores `lastKnownFileType`
here and decides from the extension.

| Top-level file | typed / neutral | explicit (`text` or `file`) |
|---|---|---|
| `model.json`, `helper.py`, `notes.h`, `chime.caf`, `run.sh`, `config.xcconfig` | verbatim | verbatim |
| `Extra.swift` | **missing**, warning | verbatim |
| `util.c`, `Thing.m` | **missing**, warning | verbatim |
| `GoogleService-Info.plist`, `TopLevel.strings` | binary plist (spike 2) | **verbatim** |
| `pic.png`, `Main.storyboard` | not tried | verbatim |
| `libfoo.a` | **build fails** | **build fails** |

The warnings, verbatim, with the build still exiting 0 once `.a` was removed:

```
warning: The Swift file "proj/Include/Extra.swift" cannot be processed by a Copy Bundle Resources build phase (in target 'Spike4' from project 'Spike4')
warning: unexpected C compiler invocation with specified outputs: 'dd/Build/Products/Debug-iphonesimulator/Spike4.app/Thing.m' (for input: 'proj/Include/Thing.m') (in target 'Spike4' from project 'Spike4')
warning: unexpected C compiler invocation with specified outputs: 'dd/Build/Products/Debug-iphonesimulator/Spike4.app/util.c' (for input: 'proj/Include/util.c') (in target 'Spike4' from project 'Spike4')
```

The `.a` input was a stub archive (just the `!<arch>` magic). In every variant
Xcode ran `strip` on it in place of a copy, and the build failed with exit 65:

```
error: The command `.../usr/bin/strip -D -S -no_atom_info proj/Include/libfoo.a -o dd/Build/Products/Debug-iphonesimulator/Spike4.app/libfoo.a` exited with status 1.
```

### Result

**Forcing the Resources phase is necessary but not enough; the file type has
to be explicit too.** With `explicitFileType` set, every top-level non-code file
tried was copied byte for byte with no warning, including the `.plist` and
`.strings` that spike 2 saw converted. That removes two caveats at once: a
top-level include is never silently dropped, and the bundle's copy always
matches the pinned SHA-256, so the build can verify it like any other
artifact. Whether `text` or `file` is used made no difference; `file` says
less about the content.

A static library is stripped whatever the reference says, which is one more
reason to refuse native code rather than copy it.

Not covered: an XML `GoogleService-Info.plist` read by the Firebase SDK at
runtime (Foundation reads XML and binary plists alike, but this run did not
launch the app). Top-level *directories* are folder references, and spikes 1
and 2 showed plain ones and `Settings.bundle` copied verbatim; a directory
named `*.xcassets` or `*.storyboardc` was not tried.

## Spike 5 — what survives iOS signing and installation?

**Question.** Spike 3 found that macOS signing refuses data in most of the
bundle. An iOS bundle is flat, so does any top-level include placement make
signing, `codesign --verify --deep --strict`, or installation on a phone
fail? And what does Xcode do with a folder whose name looks like code?

**Setup.** A scratch script, not in the repo (`/tmp/kf-iossign-spike/spike.py`).
One bundle per case, wired as spike 4 found works: every top-level entry in
Copy Bundle Resources, files with `explicitFileType = file`, directories with
`explicitFileType = folder`. Each case is built twice:

- for the simulator, signed ad hoc (`CODE_SIGN_IDENTITY=-`), as in spike 4;
- for the phone, with automatic signing, an Apple Development identity,
  `-allowProvisioningUpdates` and `-destination id=<udid>`, the way
  `xcode/commands.py` builds for a device. This registered one App ID,
  `org.kivyforge.spike5`, on the development team.

Then `codesign --verify --deep --strict --verbose=2` on the `.app`, and for
the device build `xcrun devicectl device install app`, since installation
is where iOS checks the signature. The app was uninstalled afterwards. Each
Mach-O was a `clang -target arm64-apple-ios17.0[-simulator]` build of
`int main(void) { return 0; }`.

### Results

Every case built, verified and installed, on the simulator and on the phone.

| Top-level include | Build | Verify | Install | Note |
|---|---|---|---|---|
| `data.json` and `assets/a.txt` (control) | ok | pass | ok | |
| `my.data/a.txt` | ok | pass | ok | |
| `Foo.bundle/a.txt`, no `Info.plist` | ok | pass | ok | |
| `X.framework/a.txt` | ok | pass | ok | **Xcode added a Mach-O** |
| `X.appex/a.txt` | ok | pass | ok | |
| `PlugIns/data.json` | ok | pass | ok | |
| `My Data é.json` | ok | pass | ok | |
| `helper`, a Mach-O | ok | pass | ok | **stripped, unsigned** |
| `tools/helper`, a Mach-O | ok | pass | ok | **stripped, unsigned** |

**`X.framework` gained a binary.** The folder held only `a.txt`; the built
one also held `X.framework/X`, a `Mach-O 64-bit dynamically linked shared
library arm64` that Xcode compiled and inserted, logging

```
note: Injecting stub binary into codeless framework (in target 'Spike5' from project 'Spike5')
```

`X.appex` and `Foo.bundle` were copied as plain folders.

**A Mach-O is stripped and stays unsigned.** Xcode's resource copy is
`builtin-copy ... -strip-unsigned-binaries ... -strip-tool .../strip`, and
for `helper` it ran `strip -D -S -no_atom_info`, so the bundle's copy differs
from the input. `codesign -dv` on it says `code object is not signed at all`;
the app's `CodeResources` seals it under `files2` with only a `hash2`, the
same as any data file. This is also what broke spike 4's stub `.a`.

### Result

**iOS signing constrains no placement, and the risks are elsewhere.** Unlike
macOS, `codesign` seals anything in an iOS bundle as a resource, and the
phone installed every variant. What the spike did find, for the proposal:

- A top-level directory named `*.framework` does not arrive as the user's
  files: Xcode adds a dylib to it. The proposal should refuse a top-level
  `dest` ending in a code-bundle extension (`.framework`, `.xcframework`,
  `.appex`, `.app`), and reserve `PlugIns/` alongside `Frameworks/`; App Store
  validation, which this spike did not reach, is where these would be
  rejected.
- A Mach-O include is modified by the copy and left unsigned, so it could
  neither be pinned nor run on a device. The proposal's refusal is no longer
  only a choice on iOS.

Not covered: App Store or TestFlight validation, launching the installed app
(it was a stub `main` that returns at once), and older iOS or Xcode.

## Spike 6 — does Apple notarize includes in the allowed roots?

**Question.** Spike 3 showed that the three allowed macOS roots sign and
verify. Notarization runs Apple's own checks on top of that. Does a bundle
with includes in every allowed root, and a Mach-O under `Resources/`, get
accepted?

**Setup.** A scratch script, not in the repo (`/tmp/kf-notary-spike/spike.py`),
reusing spike 3's bundle builder. **One** bundle holding every placement
spike 3 passed:

- `Contents/Resources/data.json`
- `Contents/Resources/en.lproj/InfoPlist.strings`
- `Contents/Resources/dir.with.dots/data.json`
- `Contents/SharedSupport/data.json`
- `Contents/Library/data.json`
- `Contents/Resources/helper`, a copy of the `arm64` executable

Signed with kivyforge's `sign_bundle_developer_id()`, then notarized and
stapled with kivyforge's own `notarize_and_staple()` (`ditto -c -k
--keepParent`, `notarytool submit --wait`, `stapler staple`), using the
`kivyforge-notary` keychain profile. Then `notarytool log` for the
submission, `stapler validate`, `spctl -a -t exec -vv`, and both executables
run directly.

### Results

```
notarize: Notarization accepted (submission 122eac18-5b10-4e1d-8be3-ca2bc28dbe4b).
latest submission: {'name': 'Spike3.zip', 'status': 'Accepted', 'createdDate': '2026-10-23T04:14:09.844Z'}
log status: Accepted | summary: Ready for distribution
log issues: null
ticketContents paths: ['Spike3.zip/Spike3.app', 'Spike3.zip/Spike3.app/Contents/MacOS/Spike3', 'Spike3.zip/Spike3.app/Contents/Resources/helper']
stapler validate: The validate action worked!
spctl: accepted
source=Notarized Developer ID
```

Both executables exited 0. The round trip, from submission to acceptance, took
about 25 seconds.

### Result

**Notarization accepts every allowed root, with no issues logged.** Spike 3's
rule now holds through Apple's service as well as `codesign`. The notary
ticket lists `Resources/helper` as code alongside the main executable, so
notarization also has no objection to a Mach-O under `Resources/`: the macOS
refusal of native code stays a design choice, as spike 3 found.

Not covered: a real kivyforge `package -p macos` with includes (the
proposal's verification step 5), an app that *reads* an include under the
Hardened Runtime, and a quarantined download opened through Finder.

## Spike 7 — do includes survive a Release archive and IPA export?

**Question.** Spikes 1 to 5 used Debug builds from `xcodebuild build`.
`kivyforge package -p ios` ships something else: a Release `xcodebuild
archive`, then `-exportArchive`, which re-signs the app for the export
method. Does every include still arrive byte for byte, and does the export
add or drop anything?

**Setup.** A scratch script, not in the repo (`/tmp/kf-archive-spike/spike.py`).
The project sits at `Spike7-ios/Spike7.xcodeproj`, the layout kivyforge
generates, so kivyforge's own `XcodeBuild`, `archive_command()`,
`export_command()` and `export_options_plist()` drive it, with
`-allowProvisioningUpdates` and the team passed as kivyforge passes them.
Wiring as spike 5. The includes, in one bundle: an XML
`GoogleService-Info.plist`, `data.json`, `helper.py`, `Extra.swift`,
`chime.caf`, `TopLevel.strings`, `assets/a.txt`, `Settings.bundle/Root.plist`,
`en.lproj/InfoPlist.strings` and `Foo.bundle/a.txt`. Exported once per
`--export-method`: `development`, `ad-hoc`, `app-store`. Each IPA was
unpacked with `ditto -x -k`, every include compared with its input,
`codesign --verify --deep --strict` run, and the file list diffed against the
archive's `.app`. The development IPA's app was installed on the phone and
uninstalled after.

### Results

| Product | Signed by | Includes | Verify | vs archive |
|---|---|---|---|---|
| archive (`Release`) | Apple Development | all 10 verbatim | pass | |
| `development` IPA | Apple Development | all 10 verbatim | pass | nothing added or removed; installed on the phone |
| `ad-hoc` IPA | Apple Distribution | all 10 verbatim | pass | nothing added or removed |
| `app-store` IPA | Apple Distribution | all 10 verbatim | pass | nothing added or removed |

No Apple Distribution certificate is installed on this Mac. The two
distribution exports were signed with a certificate Xcode obtained through
`-allowProvisioningUpdates` (cloud-managed signing). Nothing warned.

### Result

**The shipped IPA carries the includes exactly as the Debug build does**, for
every export method, so the byte-for-byte check `build` can make holds for
`package` too. Not covered: an App Store Connect upload or validation.

## Spike 8 — does iOS read includes that arrive unprocessed?

**Question.** Spike 4's explicit file type means a top-level
`GoogleService-Info.plist` ships as XML and `TopLevel.strings` as text,
where spike 2 saw both converted to binary plists before iOS read them. Does
iOS still read them?

**Setup.** A scratch script, not in the repo (`/tmp/kf-xmlplist-spike/spike.py`):
spike 2's app and includes unchanged, wired the way spike 4 found works.
Built for the simulator and launched on the iPhone Air simulator with
`simctl launch --console-pty`, in the mode that reports what `NSBundle`
finds. The plist is read the way Firebase reads it:
`pathForResource:@"GoogleService-Info" ofType:@"plist"`, then
`dictionaryWithContentsOfFile:`.

### Results

Every include in the `.app` was byte-identical to its input
(`GoogleService-Info.plist` and `Root.plist` still `XML 1.0 document text`).
The app reported:

```
KF-SPIKE GoogleService-Info found=yes BUNDLE_ID=org.kivyforge.spike2 API_KEY=AIzaSpikeKey
KF-SPIKE CFBundleDisplayName=SpikeEN
KF-SPIKE NSLocationWhenInUseUsageDescription=TRANSLATED reason from en.lproj
KF-SPIKE localizedInfoDictionary=CFBundleDisplayName,NSLocationWhenInUseUsageDescription
KF-SPIKE Localizable.greeting=hello from en.lproj
KF-SPIKE TopLevel.k=top-level strings file
KF-SPIKE Settings.bundle found=yes specifiers=2
KF-SPIKE chime.caf found=yes
```

(`BUNDLE_ID` is the value in spike 2's test file, not the app's identifier.)

### Result

**iOS reads every include unprocessed**, with the same values spike 2 saw:
the XML plist through Firebase's lookup, the top-level `.strings` as text, and
the `.lproj` and `Settings.bundle` content as before. The explicit file type
costs nothing at runtime. Not covered: the Firebase SDK itself, and a
launch on the phone.
