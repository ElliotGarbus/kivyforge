# Findings — Swift packages on macOS: the `xcodebuild` aggregate spike

Run 2026-10-31 on the Mac, as step 1 of
[macos-swift-packages-proposal.md](macos-swift-packages-proposal.md) §4, for
issue [#201](https://github.com/ElliotGarbus/kivyforge/issues/201). It settles
the proposal's open point (where `xcodebuild` puts resource bundles, and
whether `Bundle.module` finds them in a signed `.app`) and checks the rest of
§3.2 against a real build.

**Headline: the design works, with three corrections.** A package that declares
its product `type: .dynamic` (the swift-bridge shim does) stays its own
framework, so the build produces *several* frameworks, not one. `xcodebuild`
gives them no run path that reaches `Contents/Frameworks`, so kivyforge has to
set one. And the resource bundles are best staged in `Contents/Resources/`,
not inside the aggregate framework, because that is the only place every
package's `Bundle.module` looks.

## Environment

| | |
|---|---|
| macOS | 26.6.2 (build 25G83), arm64 |
| Xcode | 27.0 (build 27A266a), Swift 6.4 |
| kivyforge | 3.0.0.dev1, at commit `10ff37ec` (the main-bundle launcher) |
| Packages | `examples/mobile/swift-bridge/swift-shims` (local, `type: .dynamic`, no macOS platform declared); `ResProbe`, a scratch local package with one `.process` resource and an `@objc` class that reads it through `Bundle.module`; `google/promises` 2.4.0 at `5d1d0d8` (remote; two targets, each with a `PrivacyInfo.xcprivacy` resource) |
| App | a scratch kivyforge project, CPython 3.13.14, `rubicon-objc` 0.5.7, whose `main.py` loads the framework, calls into each package and writes what it saw to a JSON file |
| Signing | kivyforge's own `sign_bundle_adhoc` and `sign_bundle_developer_id` (`Developer ID Application: … (R5PKSQLUZY)`), unchanged |

Nothing in the repository was edited for the spike.

## Step 1 — the aggregate package

The root `Package.swift`, as §3.2 proposes:

```swift
let package = Package(
    name: "KivyforgePackages",
    platforms: [.macOS("11.0")],
    products: [.library(name: "KivyforgePackages", type: .dynamic, targets: ["KivyforgePackages"])],
    dependencies: [
        .package(path: "<repo>/examples/mobile/swift-bridge/swift-shims"),
        .package(path: "<scratch>/resprobe"),
        .package(url: "https://github.com/google/promises", revision: "5d1d0d8836996aead64c0d76e2aaaa6c18a7d58c"),
    ],
    targets: [.target(
        name: "KivyforgePackages",
        dependencies: [
            .product(name: "SwiftBridge", package: "swift-shims"),
            .product(name: "ResProbe", package: "resprobe"),
            .product(name: "Promises", package: "promises"),
        ],
        linkerSettings: [.unsafeFlags(["-Xlinker", "-ObjC"])])]
)
```

The `package:` argument is the package's *identity*: the last component of its
URL or path, without `.git`. It is not the name the manifest declares
(`SwiftBridge`) and not the key in `pyproject.toml`.

Built with:

```
xcodebuild -scheme KivyforgePackages -destination generic/platform=macOS \
  -derivedDataPath <dd> -configuration Release \
  ARCHS=arm64 ONLY_ACTIVE_ARCH=NO CODE_SIGNING_ALLOWED=NO \
  LD_RUNPATH_SEARCH_PATHS=@loader_path/../../.. build
** BUILD SUCCEEDED **
```

`xcodebuild` run from a directory holding only a `Package.swift` treats it as
a workspace; `-list` shows the scheme named after the dynamic product. A
rebuild with everything cached took 7 s.

## Step 2 — what lands where

`<dd>/Build/Products/Release/`:

```
PackageFrameworks/KivyforgePackages.framework
PackageFrameworks/SwiftBridge.framework
Promises_FBLPromises.bundle
Promises_Promises.bundle
ResProbe_ResProbe.bundle
KivyforgePackages.framework.dSYM  SwiftBridge.framework.dSYM
*.o  *.swiftmodule
```

1. **Frameworks** are in `PackageFrameworks/`, one per *dynamic* product:
   the root and every product whose manifest says `type: .dynamic`. The shim
   does, so it is linked as `@rpath/SwiftBridge.framework/Versions/A/SwiftBridge`
   instead of statically. Products with no `type` (Promises, ResProbe) link
   into the root. The proposal's "one dynamic image" holds only when no
   package forces `.dynamic`; the build must copy every framework in
   `PackageFrameworks/`.
2. **Resource bundles** are flat in `Products/Release/`, named
   `<package>_<target>.bundle`, *outside* every framework. A remote package's
   bundles land the same way as a local one's.
3. **Run paths.** Without the `LD_RUNPATH_SEARCH_PATHS` setting the root's only
   `LC_RPATH` is `/usr/lib/swift`, so `@rpath/SwiftBridge.framework/...` would
   not resolve from `Contents/Frameworks`. With the setting, both frameworks
   carry `@loader_path/../../..`, which from `X.framework/Versions/A/` is
   `Contents/Frameworks/`. That is the framework's own run path, so it works
   whatever process loads it.
4. **`ARCHS=arm64`** gives thin binaries (`lipo -archs`: `arm64`). Without it,
   `generic/platform=macOS` in Release builds `x86_64 arm64`.
5. **`CODE_SIGNING_ALLOWED=NO`** builds unsigned; kivyforge's deep sign signs
   them later. It also keeps `xcodebuild` from asking for a team for
   resource-bundle targets, the error Firebase hit on iOS
   ([ios-firebase-spm-signing-findings.md](ios-firebase-spm-signing-findings.md)).
6. **`-ObjC` was not needed here.** Xcode links each package target into the
   root as a prelinked `.o` (`Promises.o: Mach-O 64-bit object arm64`), not a
   static archive, so a rebuild without the flag still exported
   `FBLPromise` and `RPProbe`. It stays: a package's `binaryTarget` *is* a
   static archive (Firebase's `GoogleAppMeasurement` is), and there the
   linker drops Objective-C classes and categories nothing references.

## Step 3 — the generated resource accessor

`Intermediates.noindex/ResProbe.build/Release/ResProbe-t.build/DerivedSources/resource_bundle_accessor.swift`
looks for `ResProbe_ResProbe.bundle` in, in order:

1. `Bundle.main.resourceURL`: the `.app`'s `Contents/Resources/`, now that the
   launcher keeps the `.app` as the main bundle;
2. `Bundle(for: BundleFinder.self).resourceURL`: the `Resources/` of the image
   the module's code is in, the root framework for a static product, or the
   package's own framework for a `.dynamic` one;
3. `Bundle.main.bundleURL`: the top of the `.app`, which codesign does not seal.

The absolute build-directory fallback `swift build` generates is not there.
Section 2 of the proposal was right to choose `xcodebuild`.

## Step 4 — staged into a signed `.app`, called from Python

The scratch app was built with `kivyforge build -p macos`, then the frameworks
were copied into `Contents/Frameworks/` (symlinks kept) and the bundles into
one of two places, and the whole `.app` re-signed with kivyforge's signer:

| Bundles staged in | Sign | `codesign --verify --deep --strict` | Result |
|---|---|---|---|
| `KivyforgePackages.framework/Versions/A/Resources/` | ad-hoc | valid, satisfies its DR | all calls work |
| `Contents/Resources/` | ad-hoc | valid, satisfies its DR | all calls work |
| `Contents/Resources/` | Developer ID, Hardened Runtime, timestamp | valid | all calls work |

What the app's Python saw (the `Contents/Resources/` run):

```
"main_bundle": ".../Swift Spike-resources-adhoc.app",
"notebook_title": "spike",                      # ObjCClass("SBNotebook").alloc().initWithTitle("spike")
"greeting": "hello from Bundle.module",          # RPProbe.greeting(), read through Bundle.module
"module_bundle": ".../Swift Spike-resources-adhoc.app/Contents/Resources/ResProbe_ResProbe.bundle",
"fbl": true                                      # ObjCClass("FBLPromise"), from the remote package
```

The Python side was the proposal's §3.3 snippet unchanged:
`load_library(str(Path(sys.prefix).parents[1] / "Frameworks" / "KivyforgePackages.framework" / "KivyforgePackages"))`.
Loading the root pulled in `SwiftBridge.framework` through the run path, and
`SBNotebook`, which lives in that second framework, resolved by name.

kivyforge's existing signer handled the frameworks with no change: signing the
framework's binary path signs the framework as a bundle (`codesign -dv`:
`Format=bundle with Mach-O thin (arm64)`, `Sealed Resources … files=7` with the
bundles inside it), and the Developer ID run gave both frameworks
`flags=0x10000(runtime)` and a timestamp.

Not done here: notarization. There is no keychain profile on this machine
under a name the spike could find, and Firebase on macOS (proposal §4 step 2)
is the run that has to notarize anyway.

## What changes in the design

1. **Copy every framework in `PackageFrameworks/`**, not one. Python still
   loads only `KivyforgePackages`; dyld loads the rest.
2. **Build with `LD_RUNPATH_SEARCH_PATHS=@loader_path/../../..`**, so each
   framework finds the others in `Contents/Frameworks/` by itself. The
   launcher's run paths stay as they are.
3. **Stage resource bundles in `Contents/Resources/`.** It is the first place
   every accessor looks, for static and `.dynamic` products alike; the
   framework's `Resources/` works only for code linked into that framework.
   It is also where Xcode puts them for an app target.
4. Build with `ARCHS=<the assembly arch>` and `CODE_SIGNING_ALLOWED=NO`.
5. `-ObjC` stays, for static `binaryTarget`s.
