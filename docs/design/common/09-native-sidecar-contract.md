# 09 — The native-sidecar contract (proposal)

A convention letting a **Python package declare the native material it needs** —
Java/Kotlin source, Maven coordinates, permissions, SPM packages, Info.plist
keys — so an app build tool can discover and stage it, instead of every app
author transcribing it by hand from a README. The declaration is discovered
through a `native-integration.v1` entry point; v1 scopes it to Android and iOS.

> **Status: proposal. Nothing here is implemented.** This document records the
> design and the reasoning behind each decision so the shape can be reviewed
> before any code exists. It is deliberately written to be readable by
> maintainers of *other* toolchains (Briefcase, python-for-android, Chaquopy) —
> the convention is worthless if only kivyforge reads it.

## Why it exists

`pip install` carries a package's Python half and drops everything else. If
`libfoo` needs an AAR, a Maven coordinate, and a permission, the dependency
graph delivers none of them — the app author reads a README and hand-copies the
rest into their own `pyproject.toml`. Every app repeats the transcription, every
version bump risks silent drift, and when `libfoo` is a *transitive* dependency
the person on the hook may not know it is in the tree.

**The package knows what it needs; the app author is the one obliged to say it.**
That inversion is the whole problem.

Two concrete data points:

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

This is not Android-only. The same gap exists on iOS — a package needing an SPM
dependency and an `NSCameraUsageDescription` string — and it is **sharper**
there: a missing Android permission yields a catchable denial, while a missing
iOS usage-description string terminates the app.

The mechanism is not speculative — working implementations of the general idea
exist in the Kivy ecosystem, notably
[ksproject](https://github.com/kivy-school/ksproject). What this document adds is
the provenance and review discipline: per-package attribution, namespace
ownership, hashes in the lock, and normative obligations on the consumer.

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

## Why per-package, not a merged tree

The tempting implementation is to let every package write its native material
into one shared location under `site-packages` — a single `.java/` tree the
builder stages wholesale — and let the installer do the merging for free. It is
less code, and it is the wrong shape.

**A merged tree destroys provenance at install time.** Once the files are
overlaid, the builder cannot tell which distribution contributed which file, and
everything downstream becomes impossible: no collision detection, no per-package
hashing, no review gate, and no way to report *which* package added a permission.
Every obligation in this document depends on knowing who contributed what.

It also opens a code-substitution path. A shared source tree is last-writer-wins
by construction, so a package shipping `org/kivy/android/PythonActivity.java`
silently replaces the bootstrap's own Activity — unauthenticated, reachable by any
transitive dependency, with no signal at any stage. That is not a hypothetical
shape: `denver_sw351` already writes into `org/kivy/android/` today, because "put
my glue next to the bootstrap's glue" is the obvious instinct when the tree is
shared.

**So contributions stay inside the package and the builder walks
distributions.** Provenance comes free, and namespace enforcement, hashing,
gating, and reporting all become possible. The merge becomes explicit code the
consumer owns, rather than a side effect of unpacking order.

## Mechanism

### Discovery

An entry point marks participation and points at the sidecar. **One entry, one
file, covering every platform the package supports:**

```toml
[project.entry-points."native-integration.v1"]
native = "mypkg/_native/native.toml"
```

- Entry points are a [PEP 621](https://peps.python.org/pep-0621/) field, so
  **every build backend supports them** — setuptools, hatchling, flit, pdm,
  maturin. This is why the sidecar is static package data rather than something a
  custom PEP 517 backend generates: a backend-based design needs a wrapper per
  backend, forever, and locks out every backend nobody wrote one for.
- The value is a distribution-relative path resolved with
  `importlib.metadata.Distribution.locate_file()`. **The package is never
  imported.** This is a hard requirement, not an optimization.
- `.v1` in the group name is the version gate: a v2 consumer ignores v1 groups
  outright, which is cleaner than negotiating inside the file.

**The declaration is not in `pyproject.toml`.** It cannot be: `pyproject.toml` is
a build-time input, and arbitrary `[tool.*]` tables do not survive into the wheel
or into `site-packages` — only PEP 621 metadata a backend translates into
`.dist-info/` does. Consumers read *installed* distributions, so they never see
it. That is exactly why a design that authors the schema in `pyproject.toml`
needs a custom build backend to copy it into the wheel, and why this one uses
static package data instead.

**One file, not one per platform**, so the `contract` version is declared once
and validated in a single read before anything is trusted. Adding a platform
later is a new table, not a new entry point plus a new file.

Because the platform lives *inside* the file, the entry point's **name** carries
no meaning — nothing in the protocol reads it. Both sides are therefore pinned:

- A producer **MUST** use the literal name `native`.
- A consumer **MUST** iterate every entry in the group and ignore the name
  regardless.

Strict in what you emit, liberal in what you accept. Without the second rule a
consumer would inevitably look up `"native"` by name and *silently skip* any
package that labelled it differently — the package installs, the build succeeds,
and the permission simply never lands.

### Layout

Payload lives inside the package directory, shipped as ordinary package data:

```
mypkg/
  __init__.py
  _native/
    native.toml
    java/org/example/mypkg/Bridge.java
    swift/MyPkgShim.swift
```

Nothing lands at the site-packages root. The builder knows every sidecar path
from discovery, so excluding them from the Python asset bundle is exact.

### Schema

```toml
contract = "1"

[android]
java_namespace = "org.example.mypkg"

[android.requires]
compile_sdk = 34
min_sdk = 24

[android.src]
java = ["java"]              # relative to this file
kotlin = []

[android.gradle]
dependencies = ["com.google.firebase:firebase-messaging:23.4.0"]
repositories = []

[android.permissions]
uses = ["INTERNET", "POST_NOTIFICATIONS"]
features = [{ name = "android.hardware.bluetooth_le" }]   # `required` not settable

[[android.components]]
kind = "service"             # service | activity | receiver | provider
name = "org.example.mypkg.PushService"   # a class shipped in [android.src]
exported = false             # MUST be false; true is rejected

[android.proguard]
keep = ["-keep class org.example.mypkg.** { *; }"]

[ios]
swift_symbol_prefix = "MyPkg"

[ios.requires]
deployment_target = "15.0"

[ios.native.swift_packages]
Shim = { url = "https://github.com/example/shim", requirement = { from = "1.2.0" }, products = ["Shim"] }

[ios.src]
swift = ["swift"]            # small @objc shims only

[ios.info_plist]
NSBluetoothAlwaysUsageDescription = "Connects to your fitness tracker."

[[ios.entitlements_required]]
key = "aps-environment"
reason = "Push notification delivery"
```

### Relationship to the app's own schema

Much of this vocabulary already exists in `[tool.kivy.<platform>]`. That is
**deliberate, not redundant**: the two say the same kinds of things with a
different *speaker* and different *authority*. The precedent is `Requires-Dist`
in a wheel versus `dependencies` in the app's `pyproject.toml` — identical
syntax, two speakers, merged by the consumer, and nobody calls it duplication.
The speaker *is* the information: it determines provenance, review status, and
what the declaration is allowed to do.

Names match kivyforge's spelling wherever the semantics are identical, so nobody
carries a translation table. Where they diverge, the divergence is the point.

| Sidecar | App equivalent | Who may set what |
| --- | --- | --- |
| `[android].java_namespace` | — | package only; the app owns every namespace by default |
| `[android.requires].compile_sdk` / `min_sdk` | `[tool.kivy.android].min_sdk` | app **sets**; package declares a **floor** ([obligation 6](#consumer-obligations)) |
| `[android.src].java` / `kotlin` | `[tool.kivy.android.src]` | identical |
| `[android.gradle]` | `[tool.kivy.android.gradle]` | identical |
| `[android.permissions].uses` | `[tool.kivy.android.permissions].uses` | identical |
| `[android.permissions].features` | `[tool.kivy.android.permissions].features` | package may name a feature; **only the app** may set `required` |
| `[[android.components]]` | `[[tool.kivy.android.activities]]` | shapes differ — see below |
| `[android.proguard].keep` | *(none — gap in kivyforge)* | app has `build_settings.minify` with nowhere to declare keep rules |
| `[ios].swift_symbol_prefix` | — | package only |
| `[ios.requires].deployment_target` | `[tool.kivy.ios].deployment_target` | app **sets**; package declares a **floor** |
| `[ios.native.swift_packages]` | `[tool.kivy.ios.native.swift_packages]` | identical |
| `[ios.src].swift` | — | package only; an app puts Swift in its own Xcode target |
| `[ios.info_plist]` | `[tool.kivy.ios.info_plist]` | identical |
| `[[ios.entitlements_required]]` | `[tool.kivy.ios.entitlements]` | app **writes values**; package **requests a capability** it cannot grant |

**Why `components` rather than `services`.** kivyforge's
`[[tool.kivy.android.services]]` *generates* a `PythonService` subclass running a
Python `entry_point`. A package-declared component is the opposite: a Java class
the package already ships, registered in the manifest. That is kivyforge's
`activities` shape (declare a class provided via `src`), not its `services`
shape. Reusing the name `services` for different semantics would be a worse trap
than a different name, so the sidecar uses one `components` array with an
explicit `kind`.

## The three rules

### 1. Namespace ownership

A package declares `java_namespace` and may contribute Java/Kotlin only under it.
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
2. Discover by **iterating every entry** in the `native-integration.v1` group,
   ignoring the entry-point name — never by looking up the name `native`. A
   name-keyed lookup silently skips any package that labelled it differently, and
   silent skipping is the worst available failure mode here: the package
   installs, the build succeeds, and the declaration simply never lands.
3. Enforce namespace ownership, and **fail** on collision — never resolve by
   file or copy order.
4. Never grant a permission, promote a feature to required, or accept an exported
   component on a package's declaration alone.
5. Record each package's contribution with a content hash, and fail the build when
   the effective set drifts from what was recorded.
6. Fail when a package's `requires` (compile_sdk, min_sdk, deployment_target)
   exceeds the app's configured value, naming the package.
7. Exclude sidecar directories from the Python payload.
8. Read the sidecar **without importing** the package.
9. Name the contributing distribution in every diagnostic.
10. Treat `entitlements_required` as a prerequisite to **report**, never a value
    to write.
11. **Fail** when one distribution declares more than one entry in the group,
    naming it — rather than picking one or merging them silently.

Obligation 5 is the review gate. The lock diff *is* the review — one deliberate
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
`swift_symbol_prefix` is advisory — the consumer attributes a redeclaration error
to the contributing package rather than preventing it. Documented as weaker
rather than pretended equivalent.

**Version coupling needs almost no machinery.** Three things were conflated.
Build-toolchain constraints (`compile_sdk`, `deployment_target`) need schema
fields and obligation 6. Runtime library coupling ("I need pyjnius ≥ 1.6") is
already a normal Python dependency. Bootstrap coupling needs *nothing*, because
rule 1 forbids packages from writing into bootstrap namespaces — they can only
*call* bootstrap classes, which is a loose Python-level dependency that tracks the
Kivy API and is expressible as `kivy>=2.3,<3`. An `x-<consumer>` extension
namespace was considered and **rejected**: it hedged against a problem rule 1
removes, and unused extension points calcify.

**Naming: `native-integration`, and no `[tool.]` table at all.** Because the
sidecar is static data rather than backend-generated, the package's
`pyproject.toml` needs only the entry point — there is no `[tool.X]` namespace to
bikeshed. The group name avoids "kivy" and "kivyforge" deliberately: naming it
after one toolchain guarantees the others never adopt it, and they are the
constituency that makes this a convention instead of a feature.

The word choice does real work, because the sidecar spans three tiers — glue
source, dependency coordinates, and manifest declarations — and most candidates
covered only one of them. `*-source` and `*-code` name the glue and miss the
manifests; `*-requirements` names the declarations and misses that source
actually ships; bare `native-*` misses that permissions and Info.plist keys are
not native code; bare `platform-*` is too broad to mean anything.
**"Integration" is the one word true of all three tiers**, and it is already the
term platform SDK documentation uses for exactly this bundle — *to integrate this
SDK: add the dependency, add the permission, add the service class*.

`native-interface` was considered and rejected despite reading well: in this
domain "native interface" is JNI (pyjnius is literally *Python Java Native
Interface*), so it would misdirect the very maintainers the convention targets,
and "interface" names a code boundary — which a Maven coordinate and a usage
description string are not.

"Mobile" was deliberately left out of the key. This document scopes v1 to Android
and iOS, but macOS already has `entitlements` and Info.plist channels, so the iOS
half has a live desktop analog; baking "mobile" into a global registry key would
foreclose a platform kivyforge already supports.

## Out of v1

**Prebuilt `.aar`.** An AAR carries its own `AndroidManifest.xml`, which AGP
merges into the app's — a binary nobody reviews contributing permissions,
exported components, and providers whose `onCreate` runs before the app's own
code. That undoes rules 2 and 3 completely. The vendor-SDK case is real, but its
answer is "the vendor publishes a Maven coordinate," which nearly all of them do.
Apps that genuinely need a vendored AAR declare it themselves, explicitly, in
their own `pyproject.toml`.

**Prebuilt iOS binaries** — see the Swift decision above.

**Native `.so` sidecars.** A sidecar `.libs/<abi>/` channel is not merely
redundant with tagged wheels, it is incompatible: encoding the ABI as a
subdirectory only
makes sense inside a fat `py3-none-any` wheel, which contradicts PEP 738 tagging.
kivyforge takes the ABI from the wheel tag and rejects a nested `.libs/<abi>/` as
malformed. See [08 — native-binaries channel](08-native-binaries-channel.md) for
the app-level equivalent.

## Path forward

Deliberately sequenced so the specification *describes* something rather than
proposing it.

1. **Build the reference reader as a standalone library**, not inside
   `kivyforge/`. It discovers, parses, validates, and enforces — turning the
   consumer obligations from prose into code paths that a consumer gets by
   *using* the parser rather than by remembering. A parser living under
   `kivyforge/` reads as a KivyForge feature no matter what the README says.
2. **Then, if it spreads**, write it up as a PyPA interoperability specification.
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
