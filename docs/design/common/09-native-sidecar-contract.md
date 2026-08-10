# 09 — Native-integration (the sidecar contract)

How a **Python package declares the native material it needs** — Maven
coordinates, permissions, manifest components, SPM packages, Info.plist keys, and
any glue source — so kivyforge can stage it, instead of every app author
transcribing it by hand from a README.

> **The specification is not in this repository.** It lives at
> **[ElliotGarbus/native-integration](https://github.com/ElliotGarbus/native-integration)**
> (`SPEC.md`), deliberately outside kivyforge so other toolchains can adopt it —
> a convention only one tool reads is not worth defining.
>
> **That document is normative. This one is not.** This is kivyforge's adoption
> record: why we want it, how it maps onto our existing schema and machinery,
> what we must build, and which design decisions we contributed. When the two
> disagree, the spec wins and this file is stale.

> **Status: proposal, nothing implemented.**

## Why it exists

`pip install` carries a package's Python half and drops everything else. If
`libfoo` needs a Maven coordinate and a permission, the dependency graph delivers
neither — the app author reads a README and hand-copies the rest into their own
`pyproject.toml`. Every app repeats the transcription, every version bump risks
silent drift, and when `libfoo` is a *transitive* dependency the person on the
hook may not know it is in the tree.

**The package knows what it needs; the app author is the one obliged to say it.**

Two data points, both from this ecosystem:

- **[KivMob](https://github.com/MichaelStott/KivMob)** requires five hand-copied
  `buildozer.spec` settings. Its author needed Java alongside their Python, had no
  way to ship it, and stood up a parallel Maven distribution channel
  (`org.kivmob:kivmob-android-bridge`) to work around the gap.
- **[denver_sw351](https://github.com/kuz3yr0n/denver_sw351)** ships
  `PyGattCallback.java` as `package-data`. The Java is unavoidable —
  `BluetoothGattCallback` is abstract, and pyjnius's `PythonJavaClass` goes
  through `java.lang.reflect.Proxy`, which implements interfaces but cannot
  subclass. Nothing consumes the packaged copy, so the app author still hunts it
  down in site-packages and hand-adds three Bluetooth permissions.

The gap is sharper on iOS: a missing Android permission yields a catchable
denial, while a missing usage-description string terminates the app.

## What the spec defines

Enough shape to read the rest of this document; see `SPEC.md` for the normative
text.

| | |
| --- | --- |
| **Discovery** | A `native-integration.v1` entry point whose value is a **dotted resource anchor** (never loaded, never imported) locating `native.toml` |
| **Declaration** | One `native.toml` per distribution, shipped as ordinary package data, covering every platform |
| **Categories** | Everything a package declares is **`owns`** (exclusive, collision-checked claims — Java namespaces, Swift prefixes), **`requires`** (conditions the app must satisfy — SDK floors, entitlements, app-supplied values), or **`contributes`** (material staged on its behalf) |
| **Authority** | Only the app may set a feature `required`; an exported component or a contributed Maven repository is a *request* the app approves (`exported_required` + reason; repositories reported with distinct prominence) |
| **Data, not code** | A sidecar never carries scripts, hooks, or build arguments; a consumer never executes declared content |
| **Out of scope** | Prebuilt `.aar`, prebuilt iOS binaries, native `.so` (already solved by PEP 738 / PEP 730 tagged wheels) |

Two properties drive everything: contributions stay **per-distribution**, so
provenance survives and the merge is explicit code we own; and the **app keeps
authority**, so a package may request but never grant.

## Relationship to the app's own schema

Much of this vocabulary already exists in `[tool.kivy.<platform>]`. That is
**deliberate, not redundant**: the two say the same kinds of things with a
different *speaker* and different *authority*. The precedent is `Requires-Dist`
in a wheel versus `dependencies` in the app's `pyproject.toml` — identical
syntax, two speakers, merged by the consumer, and nobody calls it duplication.
The speaker *is* the information: it determines provenance, review status, and
what the declaration is allowed to do.

The sidecar's `owns`/`requires`/`contributes` structure supersedes exact
name-alignment with kivyforge's tables (an external-review restructure, adopted
because it makes the security model legible from the shape alone). This table is
therefore the translation table; semantics still line up even where spellings no
longer do.

| Sidecar | App equivalent | Who may set what |
| --- | --- | --- |
| `[android.owns].java_namespaces` | — | package only; the app owns every namespace by default |
| `[android.requires].compile_sdk` / `min_sdk` | `[tool.kivy.android].min_sdk` | app **sets**; package declares a **floor** |
| `[[android.requires.application_values]]` | `[tool.kivy.android.manifest]` | package **requests a value** it cannot supply (e.g. an API key's `meta-data`); app provides it |
| `[android.contributes.src]` | `[tool.kivy.android.src]` | identical semantics |
| `[[android.contributes.gradle_dependencies]]` | `[tool.kivy.android.gradle].dependencies` | identical semantics; sidecar entries are objects with a `configuration` (v1: `implementation` only) |
| `[[android.contributes.gradle_repositories]]` | `[tool.kivy.android.gradle].repositories` | package may contribute, but the lock/report gives repositories **distinct prominence** (supply-chain surface) |
| `[[android.contributes.permissions]]` | `[tool.kivy.android.permissions].uses` | identical semantics, plus a `reason` carried into the report |
| `[[android.contributes.features]]` | `[tool.kivy.android.permissions].features` | package may name a feature; **only the app** may set `required` |
| `[[android.contributes.components]]` | `[[tool.kivy.android.activities]]` | shapes differ — see below; `exported_required` + reason is a request the app approves via `allow_exported` |
| `[android.contributes.r8].keep_classes` | `[tool.kivy.android.proguard].keep` | app writes raw directives; a package writes **class patterns only**, bounded by its owned namespaces |
| `[ios.owns].swift_symbol_prefixes` | — | package only |
| `[ios.requires].deployment_target` | `[tool.kivy.ios].deployment_target` | app **sets**; package declares a **floor** |
| `[[ios.requires.entitlements]]` | `[tool.kivy.ios.entitlements]` | app **writes values**; package **requests a capability** it cannot grant |
| `[[ios.contributes.swift_packages]]` | `[tool.kivy.ios.native.swift_packages]` | identical semantics; requirement is one of `exact`/`from`/`revision`, `branch` forbidden; `from` resolutions are pinned in the lock |
| `[ios.contributes.src]` | — | package only; an app puts Swift in its own Xcode target |
| `[ios.contributes.info_plist]` | `[tool.kivy.ios.info_plist]` | split into `values` (scalars, fail on collision) and `append` (arrays, merged) |

**Why `components` rather than `services`.** kivyforge's
`[[tool.kivy.android.services]]` *generates* a `PythonService` subclass running a
Python `entry_point`. A package-declared component is the opposite: a Java class
the package already ships, registered in the manifest. That is kivyforge's
`activities` shape (declare a class provided via `src`), not its `services`
shape. Reusing the name `services` for different semantics would be a worse trap
than a different name, so the sidecar uses one `components` array with an
explicit `kind`.

## What kivyforge must implement

The spec's consumer requirements, mapped onto machinery we have or need.

| Requirement | Status in kivyforge |
| --- | --- |
| Discover by iterating the group, never importing | **new** |
| Reject unknown `contract` major | **new** |
| Enforce `[owns]` claims, fail on collision | **new** — closest existing analog is the `.so` duplicate policy in [04](../platforms/android/04-gradle-project-generation.md) |
| Never promote a feature to `required` | **exists** — `auto_features` semantics, wider input |
| Gate `exported_required` on app approval | **exists** — merged-manifest lint + per-component `allow_exported` is exactly the approval mechanism |
| Fail when `requires` exceeds app config | **new** — compare against `min_sdk` / `deployment_target` |
| Report contributed repositories with distinct prominence | **new** — a dedicated block in the lock report and a doctor advisory |
| Validate `keep_classes` patterns against owned namespaces | **new** — generation side lands via [`[tool.kivy.android.proguard]`](../platforms/android/01-pyproject-android.md#toolkivyandroidproguard--r8-keep-rules) |
| Pin `from`-ranged Swift package resolutions in the lock | **new** — extends the existing SPM lock handling |
| Record + report the delta; fail on drift | **new** — see below |
| Report `[[ios.requires.entitlements]]` as a prerequisite | **exists** — the entitlements pre-flight and doctor check |
| Report `[[android.requires.application_values]]` as a prerequisite | **new** |
| Exclude sidecar dirs from the Python payload | **new** — the stager already excludes non-payload trees |
| Name the contributing distribution in diagnostics | **new**, but free once contributions stay per-package |

Note how much of the *authority* half already exists. `auto_features` and
`allow_exported` were built for app-declared inputs and generalize to
package-declared ones unchanged — which is a good sign the split was drawn in the
right place.

## Recording and review — kivyforge's mechanism

The spec mandates the *property* (a change must not pass silently, and there must
be a durable record to diff against) but not the file format, since Briefcase and
python-for-android have no lockfile. Ours is the lock.

**Integrity is already solved.** A sidecar ships inside its wheel, and
`pylock.<platform>.toml` already pins that wheel by SHA-256, so the declaration is
transitively immutable. A separate hash would be redundant for anything installed
from a wheel.

**Disclosure is the gap**, and a hash cannot carry it — a version bump reads
identically whether it fixed a typo or began requesting a location permission. So
the resolved contribution is recorded in readable form, in the existing
per-package extension, beside the wheel pin that already secures it:

```toml
[[packages]]
name = "kivy-firebase-push"
version = "1.1.0"

[packages.tool.kivyforge.native_integration]
java_namespaces = ["org.kivyschool.firebase"]
gradle_dependencies = ["com.google.firebase:firebase-messaging:23.4.0"]
permissions = ["INTERNET", "POST_NOTIFICATIONS", "RECEIVE_BOOT_COMPLETED"]
components = ["org.kivyschool.firebase.PushService"]
java_sources = 2
```

**Path and editable installs need their own content hash**, since no wheel pins
them — following the `include_files` precedent, where re-locking is always the fix.

**`kivyforge lock` reports the delta**, because whoever runs it is best placed to
act and should not wait for a code-review diff:

```
Native integrations resolved: 3 packages
  analytics-shim 2.1.0  (via some-ui-lib)
    + permission  ACCESS_FINE_LOCATION
    + feature     android.hardware.location.gps  (required=false)
```

The `via` matters most: it is the transitive case, where the author has never
heard of the package. `kivyforge doctor` reports the current effective set as a
standing advisory, parallel to its implied-features check.

**`kivyforge build` fails on drift**, recomputing the effective set from installed
distributions and naming the package and delta — catching installs that bypassed
the lock and editables edited in place.

> Disclosure is not enforcement. If nobody reads the diff, it ships. A blocking
> prompt in a build loop earns click-through within a week; a recorded delta stays
> attributable before the fact in review and after the fact in history.

## Design decisions kivyforge contributed

Recorded here because the reasoning is ours even though the outcome is in the
spec.

**Swift: SPM recommended, source for small glue, no prebuilt binaries.** SPM is
the iOS analog of Maven — each package is its own module, so the symbol
collisions that plague Swift-compiled-into-the-app-target disappear. A few
`@objc` shim files remain available because they version *atomically* with the
Python half, which a separately published SPM package does not (the KivMob
failure). Prebuilt binaries are out on the same grounds as AARs-in-wheels: they
force an `ios_*` tag onto an otherwise pure-Python package, so it can no longer
be `pip install`ed on a desktop for development.

The Swift namespace guarantee is **weaker** than the Java one: Swift compiled
into the app target shares one module with no package namespace, so
`swift_symbol_prefixes` is advisory. Documented as weaker rather than pretended
equivalent.

**Version coupling needs almost no machinery.** Three things were conflated.
Build-toolchain constraints need schema fields and a floor check. Runtime library
coupling ("I need pyjnius ≥ 1.6") is already a normal Python dependency. Bootstrap
coupling needs *nothing*, because rule 1 forbids packages from writing into
bootstrap namespaces — they can only *call* bootstrap classes, a loose
Python-level dependency expressible as `kivy>=2.3,<3`. An `x-<consumer>` extension
namespace was considered and **rejected**: it hedged against a problem rule 1
removes, and unused extension points calcify.

**Naming: `native-integration`.** The sidecar spans three tiers — glue source,
dependency coordinates, and manifest declarations — and most candidates covered
only one. `*-source` and `*-code` name the glue and miss the manifests;
`*-requirements` names the declarations and misses that source actually ships;
bare `native-*` misses that permissions are not native code; bare `platform-*` is
too broad. **"Integration" is true of all three**, and is already the term
platform SDK documentation uses for this bundle. `native-interface` was rejected
despite reading well: in this domain "native interface" is JNI. "Mobile" was left
out of the key because macOS already has `entitlements` and Info.plist channels,
so the iOS half has a live desktop analog.

**Why not a `[tool.*]` table.** `pyproject.toml` is a build-time input; arbitrary
`[tool.*]` tables do not survive into the wheel or into site-packages, so
consumers reading installed distributions never see them. That is what forces
either a custom build backend or static package data — and a backend-based design
needs a wrapper per backend forever.

## Path forward

1. **Reference reader**, in the spec repo rather than under `kivyforge/` — it
   discovers, parses, validates, and enforces, turning the consumer requirements
   into code paths a tool gets by *using* it rather than by remembering. A parser
   under `kivyforge/` reads as a KivyForge feature no matter what the README says,
   and would quietly accrete kivyforge assumptions.
2. **Conformance test suite**, so a consumer can check itself rather than trust a
   document.
3. **kivyforge consumes the reader** — the table above is the implementation
   checklist.
4. **Then, if it spreads**, a PyPA interoperability specification. The precedent
   is [PEP 561](https://peps.python.org/pep-0561/), not PEP 725: a marker file, a
   consumer that is not an installer, and normative obligations on that consumer —
   standardized *after* the practice existed. Both the wheel format and entry
   points are living PyPA specs rather than frozen PEPs, so the bar is an
   interoperability spec, not a PEP.

## Related

- **[native-integration](https://github.com/ElliotGarbus/native-integration)** — the normative specification
- [04 — artifact distribution](04-artifact-distribution.md) — the consume-prebuilt principle this works within
- [08 — the native-binaries channel](08-native-binaries-channel.md) — the app-level analog for binaries no wheel delivers
- [android/01 — pyproject](../platforms/android/01-pyproject-android.md) — `gradle`, `permissions`, `src`, `proguard`
- [ios/01 — pyproject](../platforms/ios/01-pyproject-ios.md) — `swift_packages`, `entitlements`, `info_plist`
- [ios/06 — Swift packages](../platforms/ios/06-swift-packages.md) — the SPM channel this routes iOS native code through
