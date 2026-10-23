# Proposal — `include_files` beyond Android

> Status: **implemented 2026-10-23**. Section 8's on-Mac steps 1-5 passed the
> same day on Xcode 27 (simulator, an iPhone 18 Pro Max, and a notarized
> macOS package; test-matrix §7); step 6, Xcode 26, has not been run.
> Proposed 2026-10-22. Written for [#170](https://github.com/ElliotGarbus/kivyforge/issues/170).
> Code claims were read from the source at `87d1475d`.
> Spike results: [`include-files-spike-findings.md`](include-files-spike-findings.md)
> (spikes 1 to 8, all done 2026-10-22: incremental pruning, iOS file
> placement, macOS signing, forced Copy Bundle Resources wiring, iOS signing
> and installation on a phone, macOS notarization, iOS Release archive and
> IPA export, iOS reading unprocessed includes). Checked against Apple's
> developer documentation 2026-10-23: the macOS roots narrowed to
> `Resources` and `SharedSupport`, `AppClips/` and `Watch/` reserved,
> source formats that only work compiled refused, and quarantine dropped
> when staging on macOS. Revised after review 2026-10-23: plain `lock` must
> refresh include pins, a fix that lands on Android first
> ([#176](https://github.com/ElliotGarbus/kivyforge/issues/176)); lock inputs
> added plainly with a one-time re-lock; Android's overwrite code corrected;
> the built product verified before it is reported (`KF-ARTIFACT-CONTENT`).

## 1. Problem

Firebase's iOS setup asks for `GoogleService-Info.plist` "in the root of your
Xcode project, added to all targets". What that means is that the file must be
in the app target's Copy Bundle Resources phase, so it lands at the top of the
`.app`, where `FirebaseApp.configure()` looks for it. kivyforge has no way to
put it there:

- `app_dir` reaches `<app>.app/app/`, not the bundle root.
- `Resources/` in the generated `<app>-ios/` holds only what kivyforge
  generates (the asset catalog, the launch storyboard, the privacy manifest).
- Adding the file by hand in Xcode works for a while. The generator loads the
  existing `project.pbxproj` and only adds entries, so the reference should
  survive an incremental build. But `<app>-ios/` is designed to be
  gitignored and regenerable
  ([05 §Developer iteration workflow](../platforms/ios/05-xcode-project-generation.md#developer-iteration-workflow)),
  so a fresh clone, a CI run or a deleted folder loses it, with no error.

Android solved the same Firebase problem (`google-services.json` in `app/`)
with `[[tool.kivy.android.include_files]]`
([android/01 §include_files](../platforms/android/01-pyproject-android.md#toolkivyandroidinclude_files--copy-arbitrary-files-into-the-project)).
The question this proposal answers is whether that model should extend to the
other platforms, and how.

## 2. What `include_files` is for

`include_files` is not a way to ship app data. `app_dir` does that on every
platform, and an app reads its data relative to its own `__file__`. It puts a
file at a **native path outside the Python payload**, where the platform's
build system or OS expects to find it: the Gradle module root, an Android
`res/` folder, the top of an iOS bundle.

So the test for whether a platform needs it is not "does an app have extra
files" (they all do, and `app_dir` covers them) but "is there a native
location `app_dir` cannot reach that a library or the OS reads".

## 3. How other tools handle it

**PyInstaller.** `datas` (`--add-data SRC:DEST`) and `binaries` are its only
way to add files at all, since it collects Python by import analysis rather
than by copying a folder. So one mechanism covers both app data and native
paths. `DEST` is relative to the bundle's top-level directory, and the logical
layout is the same on every OS. On macOS, PyInstaller 6 relocates data into
`Contents/Resources` and code into `Contents/Frameworks`, cross-linked by
symlinks, because Apple's signing rules require that split
([`building/osx.py`](https://github.com/pyinstaller/pyinstaller/blob/243d0279/PyInstaller/building/osx.py)).
It also classifies every collected file as binary or data, because a file in
the wrong place breaks signing or notarization
([6.0 changelog](https://pyinstaller.org/en/v6.0.0/CHANGES.html)). There is
no first-class way to target other native paths.

**kivy-ios.** No declarative mechanism. `toolchain create` makes the Xcode
project once and it then belongs to the user, who drags files into it in
Xcode. `toolchain update` syncs only frameworks and libraries
([`toolchain.py` `update_pbxproj`](https://github.com/kivy/kivy-ios/blob/master/kivy_ios/toolchain.py)).
That works because a kivy-ios project is committed and hand-edited. A
kivyforge project is regenerated.

**Briefcase.** `sources` covers app data. Native paths need a custom
cookiecutter `template`. [beeware/briefcase#1875](https://github.com/beeware/briefcase/issues/1875)
asked for a way to add files to the generated project. Briefcase's lead
maintainer sketched a key mapping destination roots to source globs:

```toml
additional_files."app/src/main/res" = ["foobar/resources/**"]
```

and named the open question as "how you'd copy in a full directory tree". The
issue was closed in May 2026 with no linked PR, and the current
[configuration reference](https://briefcase.beeware.org/en/latest/reference/configuration/)
documents no such key.

**What kivyforge already has** is that sketch with the open question settled
(a directory source's contents land in `dest`, subfolders kept), plus:

- a SHA-256 pin per file in the lock, verified before staging, so an edited,
  added or deleted file fails the build instead of shipping silently;
- refusal of a copy that would overwrite a generated manifest or Gradle file;
- a record of what the last build copied, so a file taken out of `sources`
  is removed from the incremental project;
- a `doctor` check that reports drift before a build refuses it.

## 4. Decisions

### 4.1 Per-platform keys, shared implementation

Each platform gets its own `[[tool.kivy.<platform>.include_files]]`, with the
same table shape as Android. There is **no** `[tool.kivy].include_files`.

PyInstaller manages with one `datas` because its destination is the same
logical tree on every OS. kivyforge's equivalent of that tree is `app_dir`.
Native destinations differ by platform (a Gradle module root, an iOS bundle
root, a macOS `Contents/`), so a common key could not say where a file goes
without per-platform rules, which is a per-platform key with extra steps.

What *is* common moves into one shared module (section 5): source expansion,
the per-file pins, drift verification, staging, the removal record and the
`doctor` check. Each backend supplies three things:

1. what `dest` is relative to;
2. the paths kivyforge generates there, which an include may not replace;
3. how a staged file gets into the build (nothing on Android, where Gradle
   reads the tree; Copy Bundle Resources on iOS; nothing on macOS, where the
   bundle *is* the tree).

### 4.2 Scope: iOS now, then macOS; Linux and Windows on request

| Platform | `dest` relative to | Real uses | Decision |
|---|---|---|---|
| iOS | the `.app` root | `GoogleService-Info.plist`, `Settings.bundle`, `<lang>.lproj/InfoPlist.strings` (translated permission prompts), notification sounds | This change |
| macOS | `Contents/` | `<lang>.lproj/InfoPlist.strings`, document-type icons, Firebase's plist | Next, same shared module |
| Linux | AppDir root | AppStream metainfo in `usr/share/metainfo/`, MIME definitions in `usr/share/mime/packages/` | On request |
| Windows | bundle root | nothing concrete: `app\` covers data, `[tool.kivy.windows.native.binaries]` covers DLLs and helper executables | On request |

Linux is held back because its one strong case, AppStream metainfo, would be
better served by a dedicated key that `doctor` can validate with
`appstreamcli`, the way the `.desktop` entry is generated and checked rather
than copied. Windows is held back because nothing needs it. With the shared
module in place, adding either is a backend table and a loader call, so
waiting costs little.

### 4.3 Semantics shared by every platform

These are Android's rules today, unchanged:

- `dest` is a non-empty relative path that stays inside its root; `sources`
  is a non-empty list of project-relative paths that exist and do not escape
  the project.
- A file source lands in `dest` under its own name. A directory source's
  *contents* land in `dest`, subfolders kept.
- `kivyforge lock` records one pin per staged file, keyed by
  `(dest, source)`. `build` verifies every pin before staging: an edited
  file, a file with no pin and a pin with no file each fail with
  `KF-LOCK-DRIFT` (exit 4) and point at `kivyforge lock -p <platform>`.
  `--no-verify-lock` skips this along with every other lock check.
- No globs. A directory source plus per-file pins already gives "everything
  under this folder", and the lock lists exactly what ships.

Because pins are keyed by `(dest, source)`, they also catch changes to the
table itself: a new source has no pin, a removed one leaves a pin with no
file, and a changed `dest` does both.

**One rule changes, on Android too: plain `lock` must refresh the pins.**
Today it cannot. `lock` without `--update` returns "already in sync" when
`is_in_sync()` holds, and `is_in_sync()` compares only the config projection,
which records an include's `dest` and `sources` *paths*, not their contents.
So after editing a pinned file, or adding one to a directory source, `build`
says "Re-run `kivyforge lock -p android`", and that command changes nothing.
Only `--update` gets out, and it re-resolves every package to newest
([#176](https://github.com/ElliotGarbus/kivyforge/issues/176), reproduced
hermetically). The fix:

- a lock is in sync only if the config hash matches **and** the include
  pins, recomputed from disk, equal the lock's. Hashing local files needs no
  network;
- when only the pins differ, `lock` rewrites them and leaves resolution
  alone: no pip run, and none of the runtime, Gradle, xcframework or Swift
  package lookups that a re-resolve repeats;
- the drift messages and the `doctor` hint keep pointing at plain `lock`,
  which then does what they say.

This lands on Android first, as a fix with its own `CHANGELOG.md` entry,
before the refactor in section 5, so the shared module inherits it rather
than introducing it.

### 4.4 iOS

**`dest` is relative to the `.app` root.** `dest = "."` puts a file at the
top of the bundle; `dest = "Settings.bundle"` puts a directory's contents in
`<app>.app/Settings.bundle/`.

On Android, `dest` is relative to the generated Gradle project because Gradle
reads files from many places in it (`app/`, `app/src/main/res/`, `assets/`).
In an Xcode project a file does nothing unless a build phase references it,
so a project-relative `dest` would need a second setting to say which phase.
What the user actually knows is where the file has to end up in the app, and
that is what Firebase's, Apple's and every library's instructions describe.

**Staging and wiring.** `build` stages the includes into
`<app>-ios/Include/`, mirroring the bundle layout, then makes each *top-level*
entry of `Include/` a member of Copy Bundle Resources:

- a top-level file becomes a file reference, which Xcode copies to the bundle
  root;
- a top-level directory becomes a folder reference (the kind `app/` already
  uses), which Xcode copies as that directory, contents verbatim.

**Every top-level file goes in Copy Bundle Resources, whatever its
extension.** `pbxproj`'s `add_file` picks the build phase from the
extension: `.py`, `.c`, `.m`, `.swift` and ten more go to Sources, `.h` to
Headers, `.a` and `.dylib` to Frameworks, and an extension it does not know
(`.caf`, the usual notification-sound format) raises `ValueError`. Spike 2
added a top-level `helper.py`: it went to Sources, Xcode warned "no rule to
process file", and the build succeeded **without it in the `.app`**. So the
generator adds each top-level file with `create_build_files=False` and
`ignore_unknown_type=True`, then adds the build file to the Resources phase
itself. A top-level directory is unaffected: it is a `folder` reference,
which always goes to Resources.

**And every top-level file reference has an explicit type.** In the
Resources phase Xcode still chooses an action by extension, ignoring
`lastKnownFileType`: spike 4 saw `.swift`, `.c` and `.m` dropped with only a
warning. With `explicitFileType = file` on the reference, which overrides
the extension, every non-code file tried was copied byte for byte: `.py`,
`.h`, `.swift`, `.c`, `.m`, `.caf`, `.png`, `.storyboard`, `.plist` and
`.strings` among them.

Only top-level entries need references, because a folder reference carries
everything under it. References for entries that no longer exist are
removed. A group reference is not used: Xcode flattens a group's files into
the bundle root, which would lose `dest`.

Files are copied, not symlinked as `app/` is. An include changes only through
a re-lock, so the edit-then-Cmd-R loop that justifies the `app/` symlink does
not apply, and a copy is what the pins verified.

`<app>-ios/` is incremental, so the removal record from Android carries over:
`build` deletes what the previous build staged before it stages again. The
built product needs no pruning: on Xcode 27, an incremental build deletes the
output of a reference that left the project, and re-copies a folder reference
whenever anything under it changes, deletions included (spike 1).

**Reserved names.** An include may not replace anything the generated build
puts in the bundle. Every collision is refused, including ones Android would
allow as an override (section 7, question 2). The list comes from the
generator's own outputs rather than a hand-kept copy, so it cannot go stale.
Today that is at least: `Info.plist`, `PkgInfo` (written with `Info.plist`,
found by spike 2), `PrivacyInfo.xcprivacy` (which has its
own key), `Assets.car`, the icon PNGs `actool` writes beside it
(`AppIcon60x60@2x.png`, `AppIcon76x76@2x~ipad.png`, seen in a built
`hello-kivy.app`; the generator owns the asset catalog, so it can list them),
`LaunchScreen.storyboardc`, the executable,
`Frameworks/`, `PlugIns/`, `AppClips/`, `Watch/`, `python/`, `app/`,
`pip-deps/`, `_CodeSignature/` and `embedded.mobileprovision`. Xcode would
refuse most of these anyway with "Multiple commands produce", but that error
does not mention `include_files`. Spike 2 saw exactly that for a top-level
`Info.plist` and a top-level `PkgInfo` (exit 65).

`PlugIns/`, `AppClips/` and `Watch/` are reserved though no build writes them
today, because Apple's
[Placing content in a bundle](https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle)
names them as the iOS locations for app extensions and plug-ins, App Clips,
and a watchOS app. Spike 5 found that a data file in `PlugIns/` signs and
installs, so the reason is Apple's layout and App Store review, not the
toolchain.

**No code-bundle names.** A top-level `dest` ending in `.framework`,
`.xcframework`, `.appex` or `.app` is refused. Spike 5 copied a data-only
`X.framework/` folder as a resource and Xcode compiled a stub dylib into it
("Injecting stub binary into codeless framework"), so the bundle would hold
code the user never supplied. `.bundle` is allowed, since `Settings.bundle`
is the use it exists for. Apple's placement guide agrees: a codeless bundle
embedded outside a code location is signed as a resource, which is what a
`Settings.bundle` is.

**No native code.** An include that is a Mach-O file or a static archive, or
a directory that contains one, is refused, with a message pointing at
`[tool.kivy.ios.native.xcframeworks]`. Apple's placement guide puts
frameworks in `Frameworks/` and says iOS does not support standalone dynamic
libraries outside a framework, and `install_python` only wraps `.so` files
under `app/` and `pip-deps/`. Scripts are not code in this sense: Apple
treats Python and shell scripts as resources, so a `.py` include is fine. On iOS the refusal is also forced by the toolchain:
spike 5 found Xcode's resource copy strips an unsigned Mach-O
(`-strip-unsigned-binaries`), leaves it unsigned, and seals it as data, so it
could neither match its pin nor run; spike 4 saw a `.a` stripped the same way.
This is the iOS form of PyInstaller's binary/data classification. Detection
is by magic: Mach-O, which the macOS backend already does in
`machotools.py`, and `!<arch>` for archives.

**Nothing is processed.** Copy Bundle Resources treats some file types
specially by default: it compiles `.storyboard` and `.xib`, and converts
`.strings` and `.plist` to binary plists (spikes 1 and 2 saw the conversion).
The explicit type turns that off for top-level files, and a file inside a
folder reference was never processed (apart from binaries being stripped,
which the native-code refusal keeps out). So every include arrives byte for byte
and `build` can check the bundle's copy against the pinned SHA-256. An
include is the user's file as pinned, never something Xcode derived from it.

**No source formats that only work compiled.** A file or directory named
`*.xcstrings`, `*.storyboard`, `*.xib` or `*.xcassets`, at any depth, is
refused.
Xcode compiles each of these when it builds (a String Catalog into `.strings`
and `.stringsdict`, a storyboard into `.storyboardc`, an asset catalog into
`Assets.car`), so copied verbatim they would ship and do nothing, with no
error. String Catalogs matter most: they are Apple's current localisation
format, and an `InfoPlist.xcstrings` is what a user following
[Apple's localisation docs](https://developer.apple.com/documentation/xcode/localizing-and-varying-text-with-a-string-catalog)
would try first. The message names the compiled form to include instead
(`<lang>.lproj/InfoPlist.strings`). Not spiked: that an `.xcstrings` copied
raw is ignored at runtime follows from spike 4's verbatim copy and from
`NSBundle` reading compiled tables, but no run checked it.

Spike 2 checked the uses on an iOS 27.0 simulator, with the default
processing still on. A top-level `.strings` converted to binary still
resolves; spike 4 then showed the explicit type keeps it as text, which
`en.lproj` files in a folder reference showed iOS reads. `GoogleService-Info.plist` is
found by `pathForResource:ofType:`, the call Firebase makes, with its values.
A text `en.lproj/InfoPlist.strings` in a folder reference overrode
`CFBundleDisplayName` and `NSLocationWhenInUseUsageDescription`, and the
system location prompt showed both translated strings. `Settings.bundle`'s
`Root.plist` parsed in the app; the Settings app's pane for it was not seen.
Spike 8 repeated the read with the explicit type, so with the plist as XML
and the top-level `.strings` as text: same values.

One difference from Apple's own build remains unchecked. Apple's
[Settings bundle guide](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/UserDefaults/Preferences/Preferences.html)
says Xcode converts XML property lists to binary "to save space", so an
Xcode-built `Settings.bundle` ships a binary `Root.plist`, and this design
ships it as XML. The app reads the XML (spike 8), and nothing in the guide
says the Settings app needs binary, but nobody has seen the Settings app's
pane for it. Section 8 step 1 is therefore a gate, not a nicety.

Spike 7 took the same includes through a Release `archive` and
`-exportArchive` with kivyforge's own commands, for all three export
methods. Every include was byte for byte in each IPA, and the export added
or removed nothing.

### 4.5 macOS

**`dest` is relative to `Contents/`.** The bundle is assembled fresh in a
temporary `.app` and swapped in on success (`macos/bundle.py`), so macOS needs
no removal record and no build-phase wiring: staging is a copy into the
assembly tree before signing.

The copy drops `com.apple.quarantine`. A `GoogleService-Info.plist`
downloaded through a browser carries it, and Python's `shutil.copy2` and
`copyfile` both keep it on macOS (checked 2026-10-23); Xcode's resource copy
drops it, so iOS needs nothing. Apple has refused macOS uploads to App Store
Connect with that attribute on any file since 2025-02-18
([upcoming requirements](https://developer.apple.com/news/upcoming-requirements/)).
kivyforge has no Mac App Store path today, so this costs one call now rather
than a confusing rejection later.

**Allowed roots.** Apple documents what may live where in a bundle, and
`codesign` enforces it. So `dest` must start with `Resources` or
`SharedSupport`, which covers every use in section 4.2:

- Apple's
  [placement guide](https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle)
  lists `Contents/Resources/` as the macOS location for resources, which it
  defines as "everything that's not code";
- the
  [Bundle Programming Guide](https://developer.apple.com/library/archive/documentation/CoreFoundation/Conceptual/CFBundles/BundleTypes/BundleTypes.html)
  documents `SharedSupport` for "additional non-critical resources", such as
  document templates, clip art and tutorials.

`Library` is not allowed. Apple names `Contents/Library/`
only as the parent of code locations (`Automator/`, `QuickLook/`,
`LaunchServices/`, `LoginItems/`, `Spotlight/`, `SystemExtensions/`), and
[TN2206](https://developer.apple.com/library/archive/technotes/tn2206/_index.html)
says those places "are expected to contain only code" and that data files
there "will be rejected". A data file directly in `Library/` signs (spike 3),
but Apple documents no data use for it, and allowing the root would have
allowed `dest = "Library/LoginItems"`.

Spike 3 signed a bundle with one data
file in each candidate place, with kivyforge's own ad-hoc and Developer ID
signing. In `Resources/` (including an `.lproj` and a directory with dots in
its name), `SharedSupport/` and `Library/`, the bundle signed and passed
`codesign --verify --deep --strict`, also after a `zip`/`unzip` round trip,
which drops extended attributes. Dots in a directory name matter only in a
code location, where Apple's guide says the signing machinery takes such a
directory for a bundle. A data file at the top of `Contents/`, in
`MacOS/`, `Frameworks/` or `PlugIns/`, or beside `Contents/`, made
**signing** fail. The error names the main executable, not the include:

```
Spike3.app/Contents/MacOS/Spike3: code object is not signed at all
In subcomponent: Spike3.app/Contents/MacOS/data.json
```

So the check runs before signing, and its message names the include.

Spike 6 then notarized one bundle with an include in each place spike 3
passed, through kivyforge's `sign_bundle_developer_id()` and `notarize_and_staple()`:
`Accepted`, no issues in the notary log, stapled, and accepted by `spctl` as
Notarized Developer ID.

**Source formats** are refused as on iOS (section 4.4), for a stronger
reason: the macOS bundler runs no Xcode at all, so nothing would ever compile
an `.xcstrings`, `.storyboard`, `.xib` or `.xcassets`.

**Reserved names.** As on iOS, from the bundler's own outputs:
`Resources/app/`, `Resources/lib/`, `Resources/python/`, `Resources/bin/`
and `Resources/<exe>.icns`, plus `Info.plist`, `MacOS/` and
`_CodeSignature/`, which sit outside the allowed roots anyway.

**No native code.** A Mach-O include or a static archive is refused with a
message pointing at `[tool.kivy.macos.native.binaries]`. Both allowed roots
are data locations, and Apple's rule is that code does not go in them.
TN2206: code put anywhere but a code location is "sealed as data (resource)
files", sealed twice, and "Always put code and data into their proper
places. This applies to all signed code and is enforced by the code signing
machinery regardless of how the code is distributed." The placement guide
adds that misplaced code "might work during day-to-day development, but might
cause problems during notarization".

The toolchain does not enforce this today. In spike 3, a Mach-O executable at
`Resources/helper` signed and verified with both identities, and spike 6's
notarization accepted it, listing it as code in the ticket. So the refusal
follows Apple's documented rule rather than a failure anyone has seen. iOS
differs (section 4.4): there the toolchain strips a Mach-O include and leaves
it unsigned.

Placing code properly (`Contents/Frameworks/`, `Contents/Helpers/`,
`Contents/PlugIns/`, `Contents/Library/LoginItems/`, each with its own
signing order and entitlements) is a separate piece of work. It overlaps
with [#174](https://github.com/ElliotGarbus/kivyforge/issues/174): the
`native.binaries` channel this message points at stages into
`Contents/Resources/bin/`, which breaks the same rule. The pointer stays
right either way, since it names the configuration key, not the location.

### 4.6 The lock

**Pins.** iOS and macOS locks gain the same array Android writes:

```toml
[[tool.kivyforge.include_files]]
source = "config/GoogleService-Info.plist"
dest = "."
sha256 = "..."
```

macOS writes it through the shared wheel-and-runtime lock engine that Linux
and Windows also use, so those platforms can read it later without a format
change. Adding an optional array is backward-compatible for readers.

**Lock inputs.** The builder reads `include_files`, so
`tests/lock/test_lock_inputs.py` requires it in `LOCK_INPUTS["ios"]` and
`LOCK_INPUTS["macos"]`, as it is for Android. The paths are added plainly.
That changes `lock_inputs_sha256` for every existing iOS and macOS lock
([lock-inputs-proposal §2.1](lock-inputs-proposal.md#21-hash-the-lock-inputs-not-the-file)),
including projects that never use the feature, so each reads as stale once.

The migration follows
[lock-inputs-proposal §2.3](lock-inputs-proposal.md#23-migration-none-in-code):
no migration code, and a `CHANGELOG.md` note to run `kivyforge lock` once per
platform, which keeps the versions already pinned. A projection that omitted
a path while it was empty would avoid the one re-lock, but it would be a
special case carried forever in every hash, for a handful of beta locks.

The tracked locks are re-locked in the same change. The iOS gate lock,
`examples/mobile/hello-kivy/pylock.ios.toml`, needs Xcode to re-lock; as in
§2.3, its changed line can be written from `lock_inputs_sha256()`, checked
with `is_in_sync()`, and confirmed with `lock --check -p ios` on a Mac.

### 4.7 Failure codes

| Failure | Code | Exit |
|---|---|---|
| An include would replace a generated or reserved path, or (iOS) has a code-bundle name | new `KF-INCLUDE-RESERVED` | 1 |
| An include is or contains native code, a Mach-O or a static archive (iOS, macOS) | new `KF-INCLUDE-NATIVE-CODE` | 1 |
| An include is or contains a source format that only works compiled (`.xcstrings`, `.storyboard`, `.xib`, `.xcassets`; iOS, macOS) | new `KF-INCLUDE-SOURCE-FORMAT` | 1 |
| A file differs from, lacks or outlives its pin | existing `KF-LOCK-DRIFT` | 4 |
| `dest` or `sources` is malformed or escapes its root, or (macOS) `dest` is outside `Resources`/`SharedSupport` | existing config error | 1 |
| The built `.app` or IPA lacks an include, or holds a copy that does not match its pin (iOS, macOS; section 4.8) | new `KF-ARTIFACT-CONTENT` | 5 |

`context` names the `path` (in bundle terms) and the `source`; for
`KF-ARTIFACT-CONTENT` it also names the `artifact` and the expected and
actual SHA-256 (`null` when the file is missing).

Android's overwrite refusal raises the base `AndroidBuildError`, so today it
reports `KF-ERROR`, exit 1. The refactor gives it `KF-INCLUDE-RESERVED`,
still exit 1. An unclassified failure gaining a specific code is a
refinement, not a broken contract (`KF-ERROR` is "unspecific, never wrong"),
but agents can see it, so it gets a `CHANGELOG.md` line.

`KF-ANDROID-INCLUDE-OVERRIDE` stays Android-only, since only Android allows
an override.

### 4.8 Verifying the built product

On iOS and macOS, `build` and `package` check every include in the final
product against its pin **before reporting that product as an artifact**. A
missing file or a copy whose SHA-256 differs fails the run with
`KF-ARTIFACT-CONTENT`, exit 5, and the product is not listed in `artifacts`.
This is the existing rule that `artifacts` names only what this run
finalised and verified
([build-package-output-proposal §4.1b](build-package-output-proposal.md#41b-artifacts-on-a-failed-run-only-what-this-invocation-finalised)),
extended to the files the user asked for.

The check is possible because nothing is processed (section 4.4): each
include should arrive byte for byte, so the comparison is a hash, not a
format-aware diff. It is also the safety net for what the spikes could not
cover. They ran on Xcode 27 only; if another Xcode converts, strips or drops a
file, the build fails naming it instead of shipping it.

Where it runs:

- **iOS `build`**: on the `.app` after `xcodebuild build`, simulator and
  device.
- **iOS `package`**: on the archive's `.app`, and on the IPA after
  `-exportArchive`, by hashing the members of `Payload/<app>.app/` in the zip,
  with no extraction.
- **macOS**: on the assembled bundle after signing and **before**
  notarization is submitted, so a bad bundle is not sent to Apple; and on the
  final `.app` before it is reported.

Exit 5 is right because kivyforge staged correctly and a tool produced the
wrong product, which is what `KF-ARTIFACT-MISSING` already means for the
product as a whole. It is a separate code because an agent reading
`KF-ARTIFACT-MISSING` looks for a missing `.app`, while this one names a file
inside a product that exists.

Not Android: an include there is consumed by Gradle (`google-services.json`)
or compiled into `resources.arsc`, so nothing in the APK or AAB maps byte for
byte to a pin.

## 5. The shared module

A new `kivyforge/artifacts/include_files.py`, next to `native_stage_util.py`,
which set the precedent for staging code shared across backends. It holds:

- **expansion**: entries to `(source file, path under the root, pinned
  source)` triples. Android expands sources three times today, in
  `lock/builder.py`, `cli.py` and `doctor.py`, and the copies have to agree.
- **pinning**: `hash_include_files()`, from `android/lock/builder.py`.
- **verification and staging**: from `android/cli.py`'s
  `_copy_include_files` and `_remove_previous_includes`, taking the reserved
  set and an override callback from the backend.
- **the `doctor` check**: from `android/doctor.py`'s `_check_include_files`.
- **freshness**: `pins_current(lock, config, project_root)`, which `lock`
  calls alongside `is_in_sync()` and uses to take the pins-only refresh path
  (section 4.3).
- **product verification**: the hash check of section 4.8, over a directory
  tree (`.app`) or a zip member prefix (IPA), returning each missing or
  mismatched path for the backend to raise as `KF-ARTIFACT-CONTENT`.

Moving to shared places:

- `AndroidIncludeFile` becomes `IncludeFile` in `config/model.py`, and the
  loader's parser takes the platform and its root's name for messages.
- `LockedIncludeFile` and its reader and writer helpers move to the shared
  lock model.

Staying in the Android backend: the generated-file set, the override
diagnostic, and `_check_required_values` (the `strings.xml`/`styles.xml`
check), which are about Android resources, not about copying.

Order of work:

1. The Android freshness fix (section 4.3,
   [#176](https://github.com/ElliotGarbus/kivyforge/issues/176)), on its own,
   with tests that fail on today's code.
2. The Android move into the shared module: a refactor with no behaviour
   change apart from the overwrite refusal's code (section 4.7), with the
   existing Android tests passing untouched.
3. iOS, then macOS.

## 6. Rejected alternatives

- **One `[tool.kivy].include_files` for every platform.** See section 4.1:
  destinations are native, so the key would need per-platform rules anyway.
- **iOS `dest` relative to `<app>-ios/`, like Android.** See section 4.4.
- **A Firebase-specific key** (`google_services = "..."` per platform). It
  solves one library. `Settings.bundle`, `.lproj` folders and sounds would
  each need their own key.
- **Telling users to add the file in Xcode.** Lost when `<app>-ios/` is
  regenerated (section 1).
- **A user-supplied Xcode project template**, as Briefcase does. Hands the
  user the whole project to maintain, which is what kivyforge's generator
  exists to avoid.
- **Globs in `sources`.** See section 4.3.
- **All five platforms now, for a uniform key.** Linux and Windows have no
  concrete use (section 4.2), and an unused key is still documented,
  validated, locked and tested.

## 7. Questions for review

1. **Lock inputs. Decided:** add the paths plainly and re-lock every iOS and
   macOS lock once, following lock-inputs-proposal §2.3 (section 4.6).
2. **Overrides on iOS and macOS.** This proposal refuses every collision.
   Android allows replacing a generated resource, because replacing
   `styles.xml` or the launcher icon is a normal Android customisation. The
   generated Apple files all have their own keys (`privacy_manifest`,
   `icons`, `splash`, `info_plist`), so refusing seems right, but it could be
   relaxed later without breaking anyone. Apple's docs support refusing:
   they fix the location of `Info.plist`, the privacy manifest and the
   provisioning profile, and neither generator writes any `.lproj` content,
   so the main localisation use never collides.
3. **Android's overwrite failure code. Decided:** it is `KF-ERROR`, exit 1,
   today, and becomes `KF-INCLUDE-RESERVED`, still exit 1, with a
   `CHANGELOG.md` line (section 4.7).
4. **macOS allowed roots. Answered by Apple's docs:** `Resources` and
   `SharedSupport`, not `Library` (section 4.5). Apple's table also confirms
   `embedded.provisionprofile` at `Contents/` is a signing file, so it
   belongs with signing configuration, not here.

## 8. Verification

**Hermetic** (pytest, no toolchain):

- the shared module: expansion, pins, each drift case, the removal record,
  reserved paths, Mach-O and archive refusal, source-format refusal at any
  depth (`InfoPlist.xcstrings`, `Base.lproj/Main.storyboard`,
  `Media.xcassets/`);
- freshness, on Android first: after an edited file, a file added to a
  directory source, and a deleted file, plain `lock` writes the new pins
  without re-resolving (the resolver fakes record no call), and `build` then
  passes; an untouched project still reports `unchanged`;
- the Android suite unchanged after the refactor, except the overwrite
  refusal's code;
- product verification: a staged `.app` tree and an IPA-shaped zip with each
  include intact, one missing and one altered, giving `KF-ARTIFACT-CONTENT`
  (exit 5) naming the path and both hashes, and no artifact reported;
- iOS: the loader, the lock round trip, the lock-inputs hash now including
  `include_files`, and the generator: a top-level file is a file reference with
  `explicitFileType = file` in Copy Bundle Resources whatever its extension
  (`.py`, `.swift`, `.c`, `.caf`, `.plist` included), a top-level directory is
  a folder reference, a removed include loses its reference, a top-level
  `X.framework`/`X.appex` is refused, and `AppClips/` and `Watch/` are
  reserved;
- macOS: staging into the assembly tree with `com.apple.quarantine`
  dropped, and the allowed-roots check (`Resources` and `SharedSupport`
  accepted; `Library`, `Library/LoginItems`, `MacOS` and the `Contents/` top
  refused).

**On a Mac** (logged in [test-matrix §7](test-matrix.md#7-results-log)):

1. iOS simulator: build an app with `GoogleService-Info.plist` at `dest = "."`
   and a `Settings.bundle` directory. The build's own product check
   (section 4.8) passes; listing the `.app` confirms it independently, and
   the app reads the plist. Then edit the plist, run plain
   `kivyforge lock -p ios` and build again: the new pin is written and the
   build passes (section 4.3). Spikes 2, 4 and 8
   did this in scratch projects; this repeats it through `kivyforge build`. Also open Settings, then Apps, then the app, and see
   the `Settings.bundle` pane, which spike 2 could not reach without taps.
2. The same with an `en.lproj/InfoPlist.strings` that sets
   `NSCameraUsageDescription`, checking the translated prompt appears. Spike
   2 saw the equivalent for the location prompt.
3. Remove an include, re-lock and rebuild **without** a clean build, and check
   the file is gone from the built `.app`. Spike 1 showed Xcode 27 does this
   itself in a scratch project; this repeats it through `kivyforge build`.
4. A device build: `codesign --verify --deep --strict` on the `.app` passes
   and `kivyforge run -p ios --device` installs it. Spike 5 did both on an iPhone 18
   Pro Max for nine placements in scratch projects; this repeats it through
   kivyforge. Then `kivyforge package -p ios`, whose product check covers
   the IPA (section 4.8); spike 7 found the includes byte for byte there
   with kivyforge's commands on a scratch project.
5. macOS: an include under `Resources/`; `codesign --verify --deep --strict`
   passes on the signed `.app`, the product check runs before the notary
   submission, and notarization accepts it. Spikes 3 and 6
   did this in a scratch bundle; this repeats it through
   `kivyforge package -p macos` with Developer ID and a notary profile
   ([hardware checklist](hardware-checklist.toml)).
6. Steps 1, 3 and 4 on **Xcode 26**. Every spike ran on Xcode 27. Apple has
   required Xcode 26 or later for App Store uploads since 2026-04-28
   ([upcoming requirements](https://developer.apple.com/news/upcoming-requirements/)),
   so 26 is the oldest Xcode a shipped app can come from. The behaviours to
   confirm there are the stale-file pruning (spike 1) and `explicitFileType`
   overriding the extension (spike 4); the product check (section 4.8)
   fails the build if the second does not hold. kivyforge's documented minimum
   (Xcode 15) is a separate, wider question.

A real Firebase initialisation is not part of the gate: it needs the Firebase
SDK through Swift packages and a Firebase project, and proves Firebase works,
not that the file was placed.

## 9. Docs and changelog

- `ios/01-pyproject-ios.md` and `macos-spec.md`: the new key.
- `ios/05-xcode-project-generation.md`: `Include/` in the project layout, the
  generated file inventory and the Copy Bundle Resources phase.
- User guides: an "Add files to the app bundle" section in the iOS and macOS
  configure guides, with Firebase as the worked example, and the reference
  pages for both overlays.
- `docs/design/dev/lock-inputs-proposal.md` §2.1 already describes the
  section 4.3 fix as pending; when it lands, reword "Today that means" to the
  past tense, and add `include_files` to that section's iOS and macOS rows.
- `report/diagnostics.py`: the four new codes (`KF-INCLUDE-RESERVED`,
  `KF-INCLUDE-NATIVE-CODE`, `KF-INCLUDE-SOURCE-FORMAT`,
  `KF-ARTIFACT-CONTENT`), which `capabilities --json` then publishes.
- `CHANGELOG.md` under `[Unreleased]`:
  - **Fixed** (Android, first change): plain `kivyforge lock` now accepts an
    edited or added include file without `--update`.
  - **Changed** (Android): the include overwrite refusal reports
    `KF-INCLUDE-RESERVED` instead of `KF-ERROR`; the exit status is still 1.
  - **Added**: the iOS and macOS keys, and the product check.
  - **Migration**: every iOS and macOS lock reads as stale once; run
    `kivyforge lock -p ios` and `-p macos`, which keeps the pinned versions.
