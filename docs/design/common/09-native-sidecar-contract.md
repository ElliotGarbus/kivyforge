# 09 — The native-sidecar contract (proposal)

A convention letting a **Python package declare the native material it needs** —
Java/Kotlin source, Maven coordinates, permissions, SPM packages, Info.plist
keys — so a mobile build tool can discover and stage it, instead of every app
author transcribing it by hand from a README.

> **Status: proposal. Nothing here is implemented.** This document records the
> design and the reasoning behind each decision so the shape can be reviewed
> before any code exists. It is deliberately written to be readable by
> maintainers of *other* toolchains (Briefcase, ksproject, python-for-android,
> Chaquopy) — the convention is worthless if only kivyforge reads it.

## Why it exists

`pip install` carries a package's Python half and drops everything else. If
`libfoo` needs an AAR, a Maven coordinate, and a permission, the dependency
graph delivers none of them — the app author reads a README and hand-copies the
rest into their own `pyproject.toml`. Every app repeats the transcription, every
version bump risks silent drift, and when `libfoo` is a *transitive* dependency
the person on the hook may not know it is in the tree.

**The package knows what it needs; the app author is the one obliged to say it.**
That inversion is the whole problem.

Three concrete data points:

- **[KivMob](https://github.com/MichaelStott/KivMob)** (AdMob for Kivy, on PyPI)
  requires five separate hand-copied `buildozer.spec` settings — a Maven
  coordinate, a custom Maven repository, manifest `meta-data`, two permissions,
  and an AndroidX flag. Its author needed Java alongside their Python, had no way
  to ship it, and stood up an entire parallel Maven distribution channel
  (`org.kivmob:kivmob-android-bridge`) to work around the gap.
- **[denver_sw351](https://github.com/kuz3yr0n/denver_sw351)** ships
  `PyGattCallback.java` as `package-data`. The Java is genuinely unavoidable:
  `BluetoothGattCallback` is an abstract class, and pyjnius's `PythonJavaClass`
  goes through `java.lang.reflect.Proxy`, which can implement interfaces but
  cannot subclass. Nothing consumes the packaged copy — p4a's `add_src` takes a
  *repo-relative* path — so the app author still hunts it down in site-packages
  and hand-adds three Bluetooth permissions.
- **[ksproject](https://github.com/kivy-school/ksproject)** has a working
  end-to-end implementation of this idea (see [Prior art](#prior-art-ksproject)).
  The mechanism is proven; the guardrails are what is missing.

This is not Android-only. The same gap exists on iOS — a package needing an SPM
dependency and an `NSCameraUsageDescription` string — and it is **sharper**
there: a missing Android permission yields a catchable denial, while a missing
iOS usage-description string terminates the app.

## Scope

| Need | In scope? | Why |
| --- | --- | --- |
| Native `.so`, Python extension modules | **No** | Already solved by `android_<api>_<abi>`-tagged wheels ([PEP 738](https://peps.python.org/pep-0738/)) and the wheel-embedded `.libs/` scan |
| iOS native frameworks in wheels | **No** | Already solved by `ios_*`-tagged wheels and the `.frameworks/` scan |
| Java/Kotlin **source** | Yes | Tier 2 — unavoidable for JNI glue |
| Maven coordinates + repositories | Yes | Tier 1 — the recommended path |
| Android permissions, features, components, ProGuard rules | Yes | Manifest contributions |
| SPM packages, Swift `@objc` shims | Yes | iOS equivalents |
| Info.plist keys, entitlement prerequisites | Yes | iOS manifest equivalent |
| Prebuilt `.aar` | **No** — see [Out of v1](#out-of-v1) | Carries its own manifest; merges into the app's |
| Prebuilt iOS binaries (`.dylib`/`.xcframework`) from a sidecar | **No** — see [Out of v1](#out-of-v1) | Forces platform-tagged wheels; unauditable |

The perimeter is deliberate: **everything the Python packaging ecosystem already
handles stays there.** This contract covers only what wheels have no story for —
the Gradle/JVM and Xcode/SPM side. That keeps it small and makes it defensible
without asking wheels to do anything new about binaries.

## Prior art: ksproject

ksproject ships this today. Packages declare native material in their own
`pyproject.toml`; custom PEP 517 backends (`ksp-builder`, `pyjnius-builder`)
inject it into the wheel as dot-prefixed root directories; the build tool scans
installed site-packages and stages what it finds.

**Worth keeping:**

- Declarative config in the package's own `pyproject.toml`
- Separating native assets from the Python payload (their staging task excludes
  dot-dirs from the asset bundle)
- Merge-with-dedup for coordinates and permissions
- Import-free discovery — the build host is a desktop, and an Android-only
  package may not import there
- Following path/workspace dependencies, so monorepo development behaves like
  published wheels
- **No AAR channel.** Whether deliberate or not, this is the right call.

**The one architectural change:** ksproject merges **by filesystem overlay** —
every package writes into a shared `site_packages/<abi>/.java/` tree, so pip does
the merging for free. Elegant, and it **destroys provenance at install time**. By
the time the builder looks, it cannot tell which distribution contributed which
file. Every gap follows from that single choice: no collision detection, no
per-package hashing, no review gate, no way to report who added a permission.

Concretely, in ksproject today:

- `pip_install.py` copies local dot-dirs with
  `shutil.copytree(..., dirs_exist_ok=True)` — silent overwrite, and the project
  itself is copied *first*, so a local dependency overwrites the app's own Java.
- The generated Gradle `Copy` task stages `site_packages/<abi>/.java/` into
  `app/src/main/java/` **after** the bootstrap's own `PythonActivity.java`,
  `PythonService.java`, and `GenericBroadcastReceiver.java` are written there.
  A package shipping `.java/org/kivy/android/PythonActivity.java` silently
  replaces the bootstrap's Activity.

That last one is an unauthenticated code-substitution path into the app's entry
point, reachable by any transitive dependency. It is not hypothetical-shaped:
`denver_sw351` already writes into `org/kivy/android/` on the p4a side, because
"put my glue next to the bootstrap's glue" is the obvious instinct.

> Verified by reading the source, not by executing a collision. Reproduce before
> reporting.

**So: contributions stay inside the package, and the builder walks
distributions rather than a merged tree.** Provenance comes free, and namespace
enforcement, hashing, gating, and reporting all become possible.

## Mechanism

### Discovery

An entry point marks participation and points at the sidecar:

```toml
[project.entry-points."mobile-native.v1"]
android = "mypkg/_native/android.toml"
ios = "mypkg/_native/ios.toml"
```

- Entry points are a [PEP 621](https://peps.python.org/pep-0621/) field, so
  **every build backend supports them** — setuptools, hatchling, flit, pdm,
  maturin. This is the reason to prefer static data over ksproject's custom-backend
  approach, which needs a wrapper per backend forever.
- The value is a distribution-relative path resolved with
  `importlib.metadata.Distribution.locate_file()`. **The package is never
  imported.** This is a hard requirement, not an optimization.
- `.v1` in the group name is the version gate: a v2 consumer ignores v1 groups
  outright, which is cleaner than negotiating inside the file.

### Layout

Payload lives inside the package directory, shipped as ordinary package data:

```
mypkg/
  __init__.py
  _native/
    android.toml
    java/org/example/mypkg/Bridge.java
```

Nothing lands at the site-packages root. The builder knows every sidecar path
from discovery, so excluding them from the Python asset bundle is exact rather
than a dot-prefix heuristic.

### Schema

```toml
contract = "1"

[android]
java-namespace = "org.example.mypkg"

[android.requires]
compile-sdk = 34
min-sdk = 24

[android.source]
java = ["java"]              # relative to this file
kotlin = []

[android.gradle]
dependencies = ["com.google.firebase:firebase-messaging:23.4.0"]
repositories = []

[android.manifest]
permissions = ["INTERNET", "POST_NOTIFICATIONS"]
features = [{ name = "android.hardware.bluetooth_le" }]   # `required` not settable

[[android.manifest.services]]
name = "org.example.mypkg.PushService"
exported = false             # MUST be false; true is rejected

[android.proguard]
keep = ["-keep class org.example.mypkg.** { *; }"]

[ios]
swift-packages = [
  { url = "https://github.com/example/shim", requirement = { from = "1.2.0" }, products = ["Shim"] },
]
swift-symbol-prefix = "MyPkg"

[ios.requires]
deployment-target = "15.0"

[ios.source]
swift = ["swift"]            # small @objc shims only

[ios.info-plist]
NSBluetoothAlwaysUsageDescription = "Connects to your fitness tracker."

[[ios.entitlements-required]]
key = "aps-environment"
reason = "Push notification delivery"
```

## The three rules

### 1. Namespace ownership

A package declares `java-namespace` and may contribute Java/Kotlin only under it.
The consumer verifies both the file path and the source's `package` declaration.

- Reserved prefixes are rejected outright: `org.kivy.android`, `org.libsdl.app`,
  `org.jnius`, `org.renpy.android`, plus whatever the consumer's own bootstrap
  generates.
- Two distributions claiming overlapping prefixes is a hard error naming both.
- Collisions **fail**; they are never resolved by copy order.

This closes the substitution path described above, by construction rather than
by vigilance.

### 2. `required` is app-only

A package may declare the features its permissions imply, but never their
required-ness. Package-declared features arrive `required = false`; only the app
promotes them.

A BLE library cannot know whether *your* app requires Bluetooth or merely uses it
when present — that is a property of the app. This is
[`auto_features`](../platforms/android/01-pyproject-android.md) semantics with a
wider input, and it matters because merging permissions without emitting
non-required features silently shrinks the app's device reach on Google Play.

The same applies to iOS `UIRequiredDeviceCapabilities`.

### 3. `exported` is app-only

A package may register manifest components — an FCM service must be in the
manifest to work at all — but may never set `exported = true`. Exported
components are IPC entry points reachable by any other app on the device; opening
one is the app's decision, gated by the consumer's own review mechanism
(kivyforge's per-component `allow_exported`).

## Consumer obligations

This section is what makes the document a *contract* rather than a file format,
and it is precisely what [PEP 725](https://peps.python.org/pep-0725/) lacks: the
safety properties do not live in the declaration, they live in what the consumer
is required to do with it.

A conforming consumer **MUST**:

1. Reject a `contract` major version it does not understand, rather than ignoring
   unrecognized fields.
2. Enforce namespace ownership, and **fail** on collision — never resolve by
   file or copy order.
3. Never grant a permission, promote a feature to required, or accept an exported
   component on a package's declaration alone.
4. Record each package's contribution with a content hash, and fail the build when
   the effective set drifts from what was recorded.
5. Fail when a package's `requires` (compile-sdk, min-sdk, deployment-target)
   exceeds the app's configured value, naming the package.
6. Exclude sidecar directories from the Python payload.
7. Read the sidecar **without importing** the package.
8. Name the contributing distribution in every diagnostic.
9. Treat `entitlements-required` as a prerequisite to **report**, never a value to
   write.

Obligation 4 is the review gate. The lock diff *is* the review — one deliberate
look during code review, not an interactive prompt. It is also the obligation
that cannot be retrofitted: get it into v1 or it never arrives.

## Platform divergences

The spine is shared; three things genuinely differ.

**Manifest components are Android-only.** iOS App Extensions are separate Xcode
targets with their own bundle IDs, Info.plists, and entitlements — nothing a
Python package can contribute.

**Entitlements are iOS-only, and unique in kind.** They are bound to the App ID
and provisioning profile, so a package declaration is a *prerequisite for human
action*, not a value the builder can write. `codesign` requires the app's
entitlements to be a subset of the profile's; silently writing one produces a
signing failure much later with no trace back to the package that caused it. The
consumer must surface it as an actionable prerequisite. (The app-declared half of
this validation is implemented — see
[iOS CLI](../platforms/ios/04-cli-ios.md#kivyforge-build); provenance attaches at
the call site.)

**The trust axis inverts.** On Android an `.aar` merges its own
`AndroidManifest.xml` into the app's, so a binary can contribute permissions and
exported components. **iOS has no manifest merger** — a framework cannot inject
usage descriptions or entitlements into its host. (Privacy manifests are
aggregated, but that is disclosure, not capability.) This is why kivyforge
accepts `native.xcframeworks` as a first-class channel while this contract
excludes AARs: not an inconsistency, a response to a real platform difference.

## Resolved design decisions

**Swift: SPM recommended, source for small glue, no prebuilt binaries.**
SPM is the iOS analog of Maven — each package is its own module, so the symbol
collisions that plague Swift-compiled-into-the-app-target disappear, and Xcode
resolves and builds it. A few `@objc` shim files in the wheel remain available
because they version *atomically* with the Python half, which a separately
published SPM package does not (the KivMob failure). Prebuilt binaries are out on
the same grounds as AARs-in-wheels: they force an `ios_*` tag onto an otherwise
pure-Python package, so it can no longer be `pip install`ed on a desktop for
development. If they ever return they must be `.xcframework` (device plus both
simulator slices), never a bare `.dylib`.

Note the Swift namespace guarantee is **weaker** than the Java one: Swift source
compiled into the app target shares one module with no package namespace, so
`swift-symbol-prefix` is advisory — the consumer attributes a redeclaration error
to the contributing package rather than preventing it. Documented as weaker
rather than pretended equivalent.

**Version coupling needs almost no machinery.** Three things were conflated.
Build-toolchain constraints (`compile-sdk`, `deployment-target`) need schema
fields and obligation 5. Runtime library coupling ("I need pyjnius ≥ 1.6") is
already a normal Python dependency. Bootstrap coupling needs *nothing*, because
rule 1 forbids packages from writing into bootstrap namespaces — they can only
*call* bootstrap classes, which is a loose Python-level dependency that tracks the
Kivy API and is expressible as `kivy>=2.3,<3`. An `x-<consumer>` extension
namespace was considered and **rejected**: it hedged against a problem rule 1
removes, and unused extension points calcify.

**Naming: neutral, and no `[tool.]` table at all.** Because the sidecar is static
data rather than backend-generated, the package's `pyproject.toml` needs only the
entry point — there is no `[tool.X]` namespace to bikeshed. The group name avoids
"kivy" and "kivyforge" deliberately: naming it after one toolchain guarantees the
others never adopt it, and they are the constituency that makes this a convention
instead of a feature.

## Out of v1

**Prebuilt `.aar`.** An AAR carries its own `AndroidManifest.xml`, which AGP
merges into the app's — a binary nobody reviews contributing permissions,
exported components, and providers whose `onCreate` runs before the app's own
code. That undoes rules 2 and 3 completely. The vendor-SDK case is real, but its
answer is "the vendor publishes a Maven coordinate," which nearly all of them do.
Apps that genuinely need a vendored AAR declare it themselves, explicitly, in
their own `pyproject.toml`.

**Prebuilt iOS binaries** — see the Swift decision above.

**Native `.so` sidecars.** ksproject's `.libs/<abi>/` is not merely redundant
with tagged wheels, it is incompatible: encoding the ABI as a subdirectory only
makes sense inside a fat `py3-none-any` wheel, which contradicts PEP 738 tagging.
kivyforge takes the ABI from the wheel tag and rejects a nested `.libs/<abi>/` as
malformed. See [08 — native-binaries channel](08-native-binaries-channel.md) for
the app-level equivalent.

## Path forward

Deliberately sequenced so the specification *describes* something rather than
proposing it.

1. **Report the ksproject namespace issue** — independently and immediately. It
   is a live substitution path in a shipping tool, and arriving with a concrete
   bug and a concrete fix is a better opening than a spec proposal.
2. **Build the reference reader as a standalone library**, not inside
   `kivyforge/`. It discovers, parses, validates, and enforces — turning the
   consumer obligations from prose into code paths that a consumer gets by
   *using* the parser rather than by remembering. A parser living under
   `kivyforge/` reads as a KivyForge feature no matter what the README says.
3. **Read ksproject's existing layout too**, as a legacy shape mapping onto the
   same internal model, with a warning that it carries no provenance. They are
   the one shipping implementation; inventing a third convention makes three,
   whereas accepting theirs makes one convention with two readers immediately.
4. **Then, if it spreads**, write it up as a PyPA interoperability specification.
   The precedent is [PEP 561](https://peps.python.org/pep-0561/), not PEP 725: a
   marker file, a non-installer consumer (a type checker), and normative
   obligations on that consumer — standardized *after* the practice existed.
   Note that both the wheel format and entry points are living PyPA specs rather
   than frozen PEPs, so the bar is an interoperability spec, not a PEP.

## Related

- [04 — artifact distribution](04-artifact-distribution.md) — the consume-prebuilt principle this contract works within
- [08 — the native-binaries channel](08-native-binaries-channel.md) — the app-level analog for binaries no wheel delivers
- [android/01 — pyproject](../platforms/android/01-pyproject-android.md) — `native.aars`/`native.jars`, `gradle`, `permissions`, `src`
- [ios/01 — pyproject](../platforms/ios/01-pyproject-ios.md) — `native.xcframeworks`, `swift_packages`, `entitlements`, `info_plist`
- [ios/06 — Swift packages](../platforms/ios/06-swift-packages.md) — the SPM channel this contract routes iOS native code through
