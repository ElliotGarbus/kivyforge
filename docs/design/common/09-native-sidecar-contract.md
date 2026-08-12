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

> **Status: proposal.** Nothing is implemented beyond the two bootstrap seams
> below. Synced against SPEC.md at 25 consumer requirements — the spec has been
> through two external reviews and ten worked integration cases since this
> document was first written, and several arguments here were superseded rather
> than merely extended.

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
| **Discovery** | A `native_integration.v1` entry point (underscore — PyPA group names forbid hyphens) whose value is an importable module reference, never loaded or imported, locating `native.toml`; candidates restricted to the app's dependency closure |
| **Declaration** | One `native.toml` per distribution, shipped as ordinary package data, covering every platform |
| **Categories** | A package's *native integration material* is **`owns`** (exclusive, collision-checked claims — Java namespaces), **`requires`** (conditions the app must satisfy — SDK floors, entitlements, purpose strings, config files, app extensions, URL schemes, repository credentials), or **`contributes`** (material staged on its behalf). `contract` and `platforms` sit outside the three. Unknown keys fail closed; the `contract` minor negotiates capabilities, and an *under-declared* contract is rejected too |
| **Authority** | Only the app may set a feature `required`; an exported component is a *request* the app approves (`exported_required` + reason, failing when withheld — never falling back to unexported). `view_links` generates the browser-return filter, `intent_filters` a single vendor action on a non-exported component. Contributed repositories are bounded to their declared groups/modules — *not* `exclusiveContent`, which is a stronger policy — and reported with distinct prominence |
| **The second boundary** | The rules above bind *sidecar-authored* effects. A resolved `.aar` carries its own manifest: those permissions, features and components are read and attributed to the artifact, and two rules cross the boundary so material cannot launder past them — a resolved artifact may not silently promote a feature to `required`, and its exported components are reported with contribution-level prominence. Otherwise: attribution and review, not restriction |
| **Data, not code** | A sidecar never carries scripts, hooks, or build arguments; a consumer never executes declared content |
| **Out of scope** | Prebuilt `.aar` or iOS binaries **embedded in the wheel**, and extension modules **carried as binaries** (PEP 738 / PEP 730 tagged wheels solve those) — but a *declared* Maven coordinate resolving to an `.aar`, and a Swift package implementing a Python module from source, are both in scope. Also out: Android `res/`, build plugins and run-script phases (which excludes symbol-upload SDKs like Crashlytics entirely), and **native runtime lifecycle composition**, deferred rather than refused |

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
| `[[android.requires.application_values]]` | `[tool.kivy.android.manifest]` | package **requests a value** it cannot supply; logical `id` is what the app answers under, optional `manifest_meta_data` is the key the SDK reads. Inline references must resolve to a declared `id` |
| `[android.contributes.src]` | `[tool.kivy.android.src]` | identical semantics |
| `[[android.contributes.components.intent_filters]]` | `[tool.kivy.android].intent_filters` | app may write arbitrary filters on its own activity; a package gets **one vendor action on a non-exported component** — the FCM shape |
| `[[android.contributes.gradle_dependencies]]` | `[tool.kivy.android.gradle].dependencies` | identical semantics; sidecar entries are objects with a `configuration` (v1: `implementation` only) |
| `[[android.contributes.gradle_repositories]]` | `[tool.kivy.android.gradle].repositories` | package must declare `groups`/`modules`; kivyforge emits Gradle **content filtering** — bounded participation, *not* `exclusiveContent`, which additionally makes those modules resolvable only from that repository and can change resolution — plus `credentials_required` handling, and gives repositories **distinct prominence** in lock/report |
| `[[android.contributes.permissions]]` | `[tool.kivy.android.permissions].uses` | identical semantics; canonical manifest names (`android.permission.*`), `reason` carried into the report |
| `[[android.contributes.features]]` | `[tool.kivy.android.permissions].features` | package may name a feature; **only the app** may set `required` |
| `[[android.contributes.components]]` | `[[tool.kivy.android.activities]]` | shapes differ — see below; provenance is producer source (owned namespace) or `from_dependency` (declared coordinate); `exported_required` + reason is a request the app approves via `allow_exported`; `view_links` generates the VIEW/DEFAULT/BROWSABLE filter |
| `[android.contributes.r8].keep_classes` / `[[…r8.keep]]` | `[tool.kivy.android.proguard].keep` | app writes raw directives; a package writes **class patterns only** — `keep_classes` bounded by its owned namespaces, and a `from_dependency` keep verified against the **resolved archive contents** rather than the Maven group |
| `[ios].swift_symbol_prefixes` | — | producer guidance, not ownership — `@objc` runtime names are global across modules, so exclusivity is unenforceable; it also does not reach file-scope declarations or extension members |
| `platforms` | — | package states where it **functions at all**, which is not the same as where it contributes; we fail the build rather than shipping an app that fails at `import` |
| `[ios.requires].deployment_target` | `[tool.kivy.ios].deployment_target` | app **sets**; package declares a **floor** |
| `[[ios.requires.entitlements]]` | `[tool.kivy.ios.entitlements]` | app **writes values**; package **requests a capability** it cannot grant. v1 verifies key presence, not value semantics |
| `[[ios.requires.usage_descriptions]]` | `[tool.kivy.ios.info_plist]` | app **writes the sentence** — it is App Store reviewed; a package may only state the need. `info_plist.values` rejects `*UsageDescription` keys outright |
| `[[ios.requires.app_extensions]]` / `application_files` / `url_schemes` | app's own project | package states the need; the app builds the target, ships the file, registers the scheme. `url_schemes` is satisfied by explicit **acknowledgement**, since forwarding cannot be verified |
| `[[ios.contributes.swift_packages]]` | `[tool.kivy.ios.native.swift_packages]` | identical semantics; requirement is one of `exact`/`from`/`revision`, `branch` forbidden; `from` resolutions are pinned in the lock |
| `[ios.contributes.src]` | — | package only, and for small shims only; anything larger belongs in a Swift package, whose own module gives it real symbol separation |
| `[[ios.contributes.python_modules]]` | — | package only; registers a Swift-implemented Python module into the interpreter before init. `name` is a single ASCII identifier, no dots |
| `[ios.contributes.info_plist]` | `[tool.kivy.ios.info_plist]` | split into `values` (scalars, fail on collision) and `append` (arrays, merged) |

**Why `components` rather than `services`.** kivyforge's
`[[tool.kivy.android.services]]` *generates* a `PythonService` subclass running a
Python `entry_point`. A package-declared component is the opposite: a Java class
the package already ships, registered in the manifest. That is kivyforge's
`activities` shape (declare a class provided via `src`), not its `services`
shape. Reusing the name `services` for different semantics would be a worse trap
than a different name, so the sidecar uses one `components` array with an
explicit `kind`.

## The application's side — the answer surface

§2.2 says every `requires` is answered by the **application, through the
consumer's own configuration**, and defines the capability rather than the
spelling. The spelling is therefore ours to design, and it is a real surface: at
26 consumer requirements there are nine distinct things an app may need to say
back.

**The join key is not ours to choose.** A consumer's config format is its own,
but the key an answer is filed under comes from the declaration, so the answer
can be matched to the requirement that asked for it:

| Producer declares | We must key the answer on | Proposed spelling |
| --- | --- | --- |
| `[[android.requires.application_values]]` | `id` | `[tool.kivy.android.application_values]` |
| contributed permission | permission `name` | `[tool.kivy.android.permissions].deny` |
| `exported_required` component | component `name` | `allow_exported` (exists) |
| repository `credentials_required` | repository `url` | `[tool.kivy.android.gradle.repository_credentials]` |
| `[[ios.requires.entitlements]]` | `key` | `[tool.kivy.ios.entitlements]` (exists) |
| `[[ios.requires.usage_descriptions]]` | `key` | `[tool.kivy.ios.info_plist]` |
| `[[ios.requires.application_files]]` | `name` | bundle-resource config |
| `[[ios.requires.app_extensions]]` | `kind` | extra-target config |
| `[[ios.requires.url_schemes]]` | **the distribution** | acknowledgement list |

Note the first row. Our mapping table above pairs `application_values` with
`[tool.kivy.android.manifest]`, which is the right *analogy* but the wrong
*key*: the app answers under the producer's logical `id`, and we translate to
the manifest key the sidecar names in `manifest_meta_data`. The answer surface is
new, not an existing table with extra entries.

The last row is the odd one, and deliberately: `url_schemes` names no key,
because the scheme is the app's to choose. It is joined by distribution, and the
spec forbids a sidecar declaring more than one — so our acknowledgement can be a
flat list of distribution names.

### Credentials must be answerable without committing them

This is the one place §2.2 constrains us rather than leaving it open. A
build-time credential **MUST** be supplyable by indirection — an environment
variable, a secret store, a file outside the project — and we **MUST NOT**
require it in a file we tell the app author to commit.

That rule lands squarely on us, because our natural answer surface is
`pyproject.toml`, which is committed by definition. Doc §9's prohibition on
recording a credential in the lock would be theatre if the same secret had to be
pasted into the file next to it. Mapbox already assumes the indirection —
`~/.gradle/gradle.properties`, outside the project.

```toml
# the app's pyproject.toml — the reference is committed, the value is not
[tool.kivy.android.gradle.repository_credentials."https://api.mapbox.com/downloads/v2/releases/maven"]
username = "mapbox"
password = { env = "MAPBOX_DOWNLOADS_TOKEN" }
```

A literal **MAY** be accepted so a developer experimenting is not blocked, but
must not be the only option. `doctor` is the natural place to warn when one is
in use.

**Ordinary application values are not secrets, and should not be treated as
such.** A Sentry DSN or an AdMob app ID is embedded in the shipped APK and
readable by anyone who unzips it; committing those is not a leak, and routing
them through the environment buys nothing but friction. Only the build-time
credential — which never reaches the device — must stay out of the repository.

## What kivyforge must implement

The spec's 25 consumer requirements, mapped onto machinery we have or need.
Grouped as §8 groups them; the numbers are the spec's own.

**Discovery and the sidecar** (1–4, 14)

| Requirement | Status in kivyforge |
| --- | --- |
| Iterate the group within the app's resolved closure, never importing | **new** — the closure is what `pylock.<platform>.toml` already resolves |
| Enforce the contract gate, both directions: reject a newer minor, *and* reject a sidecar that under-declares while using a later revision's keys | **new** |
| Fail closed on unknown keys in a platform table we build | **new** |
| Exclude sidecar directories from the Python payload | **new** — the stager already excludes non-payload trees |

**Claims and namespaces** (5, 17)

| Requirement | Status in kivyforge |
| --- | --- |
| Enforce `[owns]`, fail on collision | **new** — closest analog is the `.so` duplicate policy in [04](../platforms/android/04-gradle-project-generation.md) |
| Compute every namespace/prefix/group containment on **dot-separated segments**, never raw string prefixes | **new** — small, and the likeliest place two consumers diverge |
| Reserve our own bootstrap namespaces | **done** — `org.kivy.android`, `org.libsdl.app`, `org.jnius` are already on the spec's reserved list |

**Prerequisites — never satisfied by us** (6, 8, 21, 22, 23, 25, 26)

| Requirement | Status in kivyforge |
| --- | --- |
| Report all five §7.3 prerequisite kinds — entitlements, usage descriptions, app extensions, application files, URL schemes | **partially exists** — the entitlements pre-flight and doctor check generalize |
| Fail when an **unconditional** prerequisite is unsatisfied, judged by §7.3's per-primitive satisfaction table | **new** — note `url_schemes` is satisfied by explicit app *acknowledgement*, since forwarding cannot be verified |
| Record an unsatisfied **conditional** prerequisite without failing | **new** |
| Never write an entitlement or usage description on a *producer's* authority — while still materializing what the *application* supplied | **new**, and the distinction matters: we generate the app's project, so this is originate-versus-place, not a ban on writing |
| Fail when `exported_required` has no approval — never fall back to unexported | **exists** — `allow_exported` is the approval mechanism |
| Fail when an application value is unsupplied, or an inline reference names no declared `id` | **new** — §6.3 now separates logical `id` from `manifest_meta_data` |
| Application-side permission suppression, absent from the **effective merged** manifest | **new** — a `deny` list in `[tool.kivy.android.permissions]`; emitting `tools:node="remove"` when a resolved `.aar` also declares it is the part that makes it real |
| Offer a means to answer **every** `requires`, each filed under the key §2.2 names — not a key of our choosing | **new** — nine answer paths; see [the answer surface](#the-applications-side--the-answer-surface) |
| Accept a build-time credential **by indirection**, never only as a literal in a committed file | **new** — the rule exists because `pyproject.toml` is our natural answer surface and is committed by definition |
| Reject a sidecar declaring more than one `url_schemes` entry | **new** — it carries no identifier, so two would be indistinguishable to whoever answers them |

**Native dependency resolution** (10, 12, 16)

| Requirement | Status in kivyforge |
| --- | --- |
| Lock the **fully resolved graph including transitives**, Gradle and SwiftPM alike, and resolve from the record thereafter | **partially exists** — the lock already records the resolved Maven graph |
| Record a **checksum per resolved artifact** | **new** — now MUST, not SHOULD; this is what makes "resolves identically" a claim about bytes |
| Record the resolved **revision** for Swift packages, not only the version | **new** — extends the SPM lock handling |
| Never convert a declared Gradle version to `strictly`; show **requested-versus-resolved** where they differ | **new** — a declared version is a requirement, and conflict resolution may select higher |
| Reject a resolved Swift graph containing a branch or path dependency | **new** |
| Bound a contributed repository to its groups/modules, and reject a credential in URL user-info | **new** — content filtering, *not* `exclusiveContent`. The consumer obligation is deliberately narrow: no algorithm decides whether an arbitrary string is a secret, so we reject what is syntactically identifiable and warn on the rest |
| Fail when a repository declaring `credentials_required` has none configured, naming the distribution | **new** — rather than attempting resolution and surfacing a bare `401` |
| On resolution **failure**, report every coordinate and package with the distribution that declared it | **new** — the resolver names an artifact; only we can name the Python package behind it |

**Generated project material** (11, 13, 20, 24)

| Requirement | Status in kivyforge |
| --- | --- |
| Validate `keep_classes` against owned namespaces | **new** — generation lands via [`[tool.kivy.android.proguard]`](../platforms/android/01-pyproject-android.md#toolkivyandroidproguard--r8-keep-rules) |
| Verify every `from_dependency` keep against the **resolved archive contents** | **new** — Maven groups and Java packages are different namespaces (`com.squareup.okhttp3` ships `okhttp3.*`); we already open every `.aar` for requirement 19 |
| Generate `view_links` filters, and `intent_filters` only on non-exported components | **new** — app values via manifest placeholders, already supported |
| Register declared Python modules into the interpreter, reject dotted/non-identifier names, exclude `<name>.py` **and** `<name>.pyi` from the device payload | **seam done** — `kivyforge_register_native_modules()` runs before `Py_InitializeFromConfig`; the table it reads is still empty |

**Recording, disclosure, attribution** (7, 9, 15, 19, 25)

| Requirement | Status in kivyforge |
| --- | --- |
| Record and report the delta; fail on drift, **including the first build** | **new** — see below |
| Hash sidecar inputs **per file, for every producer** | **new** — supersedes our path/editable-only argument; see below |
| Record and report permissions, features and components from **each resolved `.aar`'s own manifest**, attributed to the artifact | **new** — now MUST, not SHOULD; `kivyforge package` already lints the merged manifest |
| Never let a resolved artifact silently promote a feature to `required`; report its exported components with contribution-level prominence | **new** |
| **Never write a supplied credential** into the generated project, the record, or a diagnostic | **new** — and the lock is committed, so this points straight at us |
| Name the contributing distribution in **every** diagnostic | **new**, but free once contributions stay per-package |

**Platform applicability** (18)

| Requirement | Status in kivyforge |
| --- | --- |
| Fail when building for a platform a sidecar's `platforms` key omits | **new** — cheap, and turns a runtime `ImportError` into a build-time diagnostic |

Note how much of the *authority* half already exists. `auto_features` and
`allow_exported` were built for app-declared inputs and generalize to
package-declared ones unchanged — which is a good sign the split was drawn in the
right place.

## Bootstrap seams

Two things in the generated bootstraps had to change **before** the reader
exists, because they are structural preconditions rather than features. Both are
inert today: nothing fills the iOS table, and nothing was previously setting the
Android attribute.

**iOS — an inittab hook (`§7.7`).** Some packages implement a Python extension
module in Swift; the Swift compiles into the app target against this app's own
interpreter, so there is no shared object and `dlopen` never runs. Such a module
is invisible to `import` until it is registered, and registration must happen
before `Py_InitializeFromConfig`. `kivyforge_bootstrap.m` had no such point.

It now calls `kivyforge_register_native_modules()` between `Py_PreInitialize` and
`Py_InitializeFromConfig`, iterating a table in a generated
`kivyforge_native_modules.h` — the same per-project-header pattern as
`main_config.h`, so `main.m` and the bootstrap stay stable. With no contributed
modules the table holds only its terminator and the loop does nothing.

This matters more than one package: PyCoreLocation, PyWebViews, PyPHPicker,
PyCamera, PyCoreBluetooth, PyCoreMidi, PyTextToSpeech and PySpeechRecognizer are
all built this way. Without the hook they compile, link, and fail at `import`.

The registration failing is fatal by design. Packages ship a same-named typing
stub for off-device editing, so a silently skipped registration would otherwise
surface as an app that imports successfully and returns `None` from every call.

**Android — the `<application android:name>` slot (`§6.1`).** `manifest.py` merged
`[tool.kivy.android.manifest.application]` verbatim, so an app author could set
`android:name` and replace the Application class. That is a singleton slot: only
one class occupies it, so ceding it leaves no way for two SDKs that both need
startup work to coexist, and it is the slot a sidecar must never be able to
claim. It is now reserved, with a `ManifestError` naming why. Every other
attribute still passes through.

Nothing here implies startup hooks are coming. Sentry demonstrates the opposite
— it reaches pre-application initialisation with a `ContentProvider` in its own
AAR plus manifest meta-data, no producer code at launch — which is part of why
that proposal stayed deferred. The slot is reserved so the question stays open,
not because it is settled.

## Recording and review — kivyforge's mechanism

The spec mandates the *property* (a change must not pass silently, and there must
be a durable record to diff against) but not the file format, since Briefcase and
python-for-android have no lockfile. Ours is the lock.

**The record holds the resolution, not the declaration.** This is the part that
grew most. An early draft of this section recorded what the sidecar *said* — its
coordinates, permissions and component names. §9 requires what the build
*resolved*, which is a much larger object:

```toml
[[packages]]
name = "kivy-firebase-push"
version = "1.1.0"

[packages.tool.kivyforge.native_integration]
java_namespaces = ["org.kivyschool.firebase"]
permissions = ["android.permission.INTERNET", "android.permission.POST_NOTIFICATIONS"]
components = ["org.kivyschool.firebase.PushService"]
# per-file, for every producer — not only path/editable installs
files = { "native.toml" = "sha256:…", "java/Push.java" = "sha256:…" }

  # the resolved graph, transitives included, one entry per artifact
  [[packages.tool.kivyforge.native_integration.resolved]]
  coordinate = "com.google.firebase:firebase-messaging:23.4.0"
  requested  = "23.4.0"          # shown only when resolution selected higher
  sha256     = "…"
  # what this artifact's own manifest brought, attributed to it and not to us
  manifest_permissions = ["com.google.android.c2dm.permission.RECEIVE"]
```

Canonical permission names, per §6.7 — not the `"INTERNET"` shorthand our own
schema uses.

**Per-file hashes are required for every producer**, which supersedes an argument
this document previously made. We reasoned that a wheel's SHA-256 in
`pylock.<platform>.toml` already pins the sidecar transitively, so only path and
editable installs need their own hash. That reasoning is correct about
*integrity* and beside the point: §9 wants per-file hashes so a diagnostic can
say `java/Push.java changed` rather than "the producer's hash changed." Cheap,
and the spec is normative.

**Disclosure is still the gap a hash cannot fill** — a version bump reads
identically whether it fixed a typo or began requesting a location permission —
which is why the resolved contribution is recorded in readable form beside the
wheel pin that already secures it.

**`kivyforge lock` reports the delta**, because whoever runs it is best placed to
act and should not wait for a code-review diff:

```
Native integrations resolved: 3 packages
  analytics-shim 2.1.0  (via some-ui-lib)
    + permission  android.permission.ACCESS_FINE_LOCATION
    + feature     android.hardware.location.gps  (required=false)
```

The `via` matters most: it is the transitive case, where the author has never
heard of the package. `kivyforge doctor` reports the current effective set as a
standing advisory, parallel to its implied-features check.

**`kivyforge build` fails on drift**, recomputing the effective set from installed
distributions and naming the package and delta — catching installs that bypassed
the lock and editables edited in place.

### Three consequences of the lock being the record

**The first build is not an exemption.** §9 requires the same explicit acceptance
when *no* record exists as when one changed: that is the build where an app
acquires all of its inherited native surface at once. `kivyforge lock` being an
explicit action maps onto this cleanly — but "no lock yet, so proceed" would not.

**The lock now has two staleness triggers.** A bounded range
(`at_least`/`below`) can resolve higher when upstream publishes, with the Python
closure completely unchanged. `lock` must re-resolve the native graph even when
nothing pip-visible moved, or ranges silently never advance and the lock quietly
stops meaning what it says.

**The lock is committed, and §9 forbids recording secrets.** With
`credentials_required = true` on a repository, the record carries the
*requirement* and never the value. The hazard is specific to us: §9's own
machinery — hash every input, keep the record durable and diffable — is exactly
what would launder a credential into version control. §2.2 closes the other half
of the same hole by requiring that the value be supplyable without ever entering
a committed file; keeping it out of the lock while requiring it in
`pyproject.toml` would achieve nothing.

**Provenance is worth storing even though §9 only requires reporting it.** The
`(via some-ui-lib)` path is a report obligation; the record is not required to
hold it, and a consumer can recompute it from the current closure each build. But
then the record cannot answer "did this package's path change" — only "did what it
contributes change." It is cheap to write and impossible to reconstruct later.

> Disclosure is not enforcement in one specific sense: the build *does* stop, and
> an unaccepted change fails. What no build tool can enforce is that anyone read
> what they accepted. A blocking prompt in a build loop earns click-through within
> a week; a recorded delta stays attributable before the fact in review and after
> the fact in history.

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
