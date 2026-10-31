# macOS: Swift packages (`[tool.kivy.macos.native.swift_packages]`)

Status: **accepted**, 2026-10-31; the spike in
[macos-swift-packages-spike-findings.md](macos-swift-packages-spike-findings.md)
corrected §3.2 as noted there, and the design below is what shipped. Issue
[#201](https://github.com/ElliotGarbus/kivyforge/issues/201) asks for Swift
packages and `Info.plist` keys on macOS, as on iOS, citing Firebase. The
`Info.plist` half and its prerequisite, a launcher that keeps the `.app` as
the main bundle, shipped with this proposal (CHANGELOG, `[Unreleased]`). This
document covers the half that did not: building SwiftPM packages into a macOS
`.app` that has no Xcode project.

## 1. Why it is not the iOS channel with a different table name

On iOS, kivyforge writes package references into the generated `.xcodeproj`
and Xcode resolves, builds, links and embeds them into the app's own binary
([06-swift-packages.md](../platforms/ios/06-swift-packages.md)). The macOS
backend generates no Xcode project. Its main executable is a ~70-line C
launcher, and Python runs from `libpython` inside it. Swift code therefore has
to reach the process as a dynamic library that Python loads, then calls
through Rubicon-ObjC or pyobjus. That needs a build step kivyforge does not
have today.

## 2. Questions the Apple documentation and a spike settled

| Question | Answer | Source |
|---|---|---|
| What is the main bundle? | "The bundle directory that contains the current executable." | `Bundle.main`, Foundation docs |
| What did the `.app` see before #201? | `Contents/Resources/python/bin`, identifier `NULL`: the launcher `execv`ed `python3`. | Spike, 2026-10-31, `CFBundleGetMainBundle()` from inside `Dice Roller.app` |
| And after? | The `.app`; a custom `Info.plist` key reads back. | Same spike with a `dlopen(libpython)` + `Py_BytesMain` launcher; now `TestLauncherCompile::test_the_main_bundle_is_the_app` |
| Where does Firebase look for `GoogleService-Info.plist`? | `[NSBundle mainBundle]`, then the bundle holding its class; it also matches the bundle id. Before #201 it could not find a file `include_files` put in `Contents/Resources`. | `FirebaseCore/Sources/FIRBundleUtil.m` |
| Where do dynamic libraries go in a Mac app? | `Contents/Frameworks/` ("Framework, dynamic library"). Mach-O code anywhere outside a code location can fail notarization. | "Placing content in a bundle", Bundle Resources docs |
| Will the Hardened Runtime load our library? | Library validation admits Apple-signed code or the main executable's Team ID; kivyforge signs everything with one identity and already sets `disable-library-validation` by default. | Hardened Runtime + `com.apple.security.cs.disable-library-validation` docs; `signing.py` |
| Can `swift build` produce what we need? | **Not for packages with resources.** Its generated `Bundle.module` looks in `Bundle.main.bundleURL/<pkg>_<target>.bundle`, the top of the `.app`, then in the absolute build path, and `fatalError`s otherwise. The top of a `.app` is not a place codesign seals, so a shipped app crashes on first `Bundle.module` access. | `SwiftModuleBuildDescription.swift` (`generateResourceAccessor`), swift-package-manager `main` |
| Static or dynamic products? | A package should leave `type` unset so "the package's consumer" chooses. Most SDKs, Firebase included, do. | `Product.library(name:type:targets:)`, PackageDescription docs |

## 3. Proposed design

### 3.1 Config and lock

`[tool.kivy.macos.native.swift_packages]` with the iOS entry keys `url`,
`path`, `requirement` and `products`. It is a separate table, not a shared
one: a package's products differ per platform (a UIKit shim has no macOS
build), and every other per-target setting lives in its own overlay. `link`
and `embed` are Xcode target settings with no meaning here and are refused.
`lock` reuses `platforms/ios/lock/spm.py` unchanged and pins revisions in
`[[tool.kivyforge.swift_packages]]` in `pylock.macos.toml`. The SPM channel
pins inputs, not outputs, as on iOS (06-swift-packages.md, "Reproducibility").

### 3.2 Build: one aggregate framework, built by `xcodebuild`

`build` writes a throwaway root package under `build/macos/spm/`:

```swift
// swift-tools-version:5.9
let package = Package(
    name: "KivyforgePackages",
    platforms: [.macOS("<minimum_system_version>")],
    products: [.library(name: "KivyforgePackages", type: .dynamic,
                        targets: ["KivyforgePackages"])],
    dependencies: [/* one .package(url:, revision:) or .package(path:) per entry */],
    targets: [.target(
        name: "KivyforgePackages",
        dependencies: [/* .product(name:, package:) per declared product */],
        linkerSettings: [.unsafeFlags(["-Xlinker", "-ObjC"])])]
)
```

- **One dynamic image to load.** Every product whose manifest leaves `type`
  unset links statically into the root framework, so Python loads one thing
  and SwiftPM's automatic products are never duplicated across images. A
  product that declares `type: .dynamic` (the swift-bridge shim does) stays a
  framework of its own, which the root links by `@rpath`. The build copies
  every framework `xcodebuild` writes to `PackageFrameworks/`, and dyld loads
  the others when Python loads the root.
- **Run paths.** `xcodebuild` gives the frameworks only `/usr/lib/swift`, so
  kivyforge builds with `LD_RUNPATH_SEARCH_PATHS=@loader_path/../../..`: from
  `X.framework/Versions/A/` that is `Contents/Frameworks/`, whatever process
  loads it.
- **`-ObjC`.** Python reaches Swift through the Objective-C runtime by class
  name. Xcode links each package target as a prelinked object, so its classes
  stay without the flag (spike, step 2), but a package's static
  `binaryTarget` is an archive the linker would strip of unreferenced classes
  and categories. Firebase needs the flag on iOS (#197). `unsafeFlags` is
  allowed because this is the root package.
- **`xcodebuild`, not `swift build`**, because of the resource accessor in
  section 2. The Xcode accessor looks under the main bundle's `resourceURL`,
  then the `resourceURL` of the image holding the module's code, then the top
  of the main bundle. `xcodebuild` writes each `<pkg>_<target>.bundle` beside
  `PackageFrameworks/`, outside every framework.
- **Placement.** Frameworks go to `Contents/Frameworks/`. Resource bundles go
  to `Contents/Resources/`: the first place every accessor looks, for static
  and `.dynamic` products alike, and where Xcode puts them for an app. A
  framework's own `Resources/` works only for code linked into it. The
  existing inside-out deep sign covers both, unchanged (spike, step 4).
- Built with `ARCHS=<assembly arch>` and `CODE_SIGNING_ALLOWED=NO`; the deep
  sign signs the frameworks later, and resource-bundle targets never ask for a
  team.

### 3.3 Python side

The framework is not loaded automatically; Python loads it from the
documented place, as for native binaries:

```python
from pathlib import Path
import sys
from rubicon.objc.runtime import load_library

load_library(str(Path(sys.prefix).parents[1] / "Frameworks"
                 / "KivyforgePackages.framework" / "KivyforgePackages"))
```

The swift-bridge guide gains a macOS section.

### 3.4 Doctor

Reuse the iOS "Swift package toolchain" check, which skips when nothing is
declared, and add "`xcodebuild` can build for macOS".

## 4. Verification plan

1. Spike (section 3.2's open point): `examples/mobile/swift-bridge`'s local
   shim plus one remote package with resources, built as above; from Python,
   construct a shim class through Rubicon and read a `Bundle.module`
   resource. **Done 2026-10-31**:
   [macos-swift-packages-spike-findings.md](macos-swift-packages-spike-findings.md).
2. Firebase on macOS: `FirebaseCore` + `GoogleService-Info.plist` through
   `include_files` + `FirebaseApp.configure()` from Python, ad-hoc and
   Developer ID + notarized. A `hardware-checklist.toml` entry, since it needs
   a Firebase project: `macos-firebase-swift-package`, not yet run.
3. Hermetic tests for config, lock, `Package.swift` rendering and staging,
   with `xcodebuild` faked as `swift` is on iOS.

## 5. Not proposed

- Building per-product frameworks. That means N images to load in dependency
  order and `@rpath` links between them for the native-links check to judge,
  with no gain over one aggregate.
- Reading `[tool.kivy.ios.native.swift_packages]` on macOS (section 3.1).
