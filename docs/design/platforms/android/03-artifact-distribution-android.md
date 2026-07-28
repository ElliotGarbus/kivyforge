# Android — Artifact Distribution

> **Status: design.** Companion to [pyproject-android](01-pyproject-android.md) and [pylock-android-spec](02-pylock-android-spec.md).

This document defines, for the Android target, **where artifacts live**, **how
they're verified**, **how kivyforge consumes them**, and **how lockfile entries
map to project folders**. For the cross-platform concepts these Android specifics
instantiate, see [common artifact distribution](../../common/04-artifact-distribution.md).

## Four distribution channels, deliberately

For Android, kivyforge sources dependencies through four deliberate channels,
each matched to the shape the artifact naturally takes:

1. **Android wheels** — Python packages with C extensions (Kivy, pyjnius, pillow, numpy, …) and pure-Python packages, via pip-compatible indexes or vendored locally. The natural shape for things Python imports.
2. **The python.org Android runtime** — the prebuilt, relocatable CPython embeddable package, per ABI. The Android analog of the iOS `Python.xcframework`.
3. **`.aar` / `.jar` archives** — prebuilt Android/Java libraries that aren't bundled inside any Python wheel, hosted or vendored. The natural shape for things Gradle links.
4. **Gradle/Maven dependencies** — third-party libraries resolvable from a Maven repository by coordinate. The natural shape for the large Android/AndroidX/Google ecosystem, and (like iOS SPM) the one channel whose lifecycle a build tool — Gradle — already owns.

Channels 1–3 share one consumption model: **kivyforge downloads the artifact,
verifies its SHA-256, and stages it into the generated Gradle project.** Channel 4
differs in *who downloads* — **Gradle owns resolve/fetch/compile** — but not in
integrity: kivyforge still pins every resolved Maven artifact by SHA-256 and has
Gradle enforce it. It is reconciled with the "no from-source pipeline" principle
exactly as SPM is for iOS (see channel 4 below).

## The core invariant holds on Android

> **kivyforge runs no from-source build pipeline of its own.** It does not
> resurrect a python-for-android-style recipe system and it does not cross-compile
> Python C extensions.

The pyjnius Android-wheel spike
([findings](../../dev/pyjnius-android-wheel-spike-findings.md);
[pre-spike brief](../../dev/pyjnius-android-wheel-spike.md)) established that the
load-bearing unknown — pyjnius, the Java bridge — can be a clean prebuilt wheel
(Java-free, SDL-agnostic, `JNIEnv` resolved at runtime), proven on an x86_64
emulator and arm64 hardware; the first-party PyPI wheel, the SDL3-host run, and
first-party (kivyforge-stack) validation remain open (see the findings'
acceptance-criteria status). With CPython Android (Tier 3), a Kivy Android
wheel, and a pyjnius wheel all in hand, the Android backend is a **wheel-assembly
+ Gradle-drive** backend, not a from-source one — the same bet the desktop and iOS
backends make. Genuine from-source compilation of a Maven dependency is deferred
to **Gradle** (channel 4), exactly as iOS defers SPM source compilation to Xcode.
The only C kivyforge itself emits is the tiny native launcher (`libmain.so`),
compiled by the NDK during the Gradle build — the analog of Xcode compiling iOS's
`main.m`, not a bespoke cross-compile pipeline.

## App-specific native extensions (Cython / C)

Same rule as iOS: if the *app author* writes their own native code (a Cython
module, a C extension), it is **not** compiled by kivyforge. It must be **built
into an Android wheel out-of-band and then consumed like any other dependency**
(channel 1). Concretely, the author:

1. Packages it as a normal distribution.
2. Cross-builds Android wheels with **`cibuildwheel` (Android support, ≥ 3.1)** on a Linux/macOS host — the same tool and flow the Kivy and pyjnius wheels use. cibuildwheel drives the NDK via `sdkmanager`, defaults to `ANDROID_API_LEVEL=24`, and 16 KB-aligns the `.so`s (NDK r28+).
3. Consumes the wheel either **hosted** (publish to PyPI / a supplemental index, reference by name) or **vendored** (commit the built wheel, pin it by `path` — see [pylock-android-spec §"Locally built wheels"](02-pylock-android-spec.md#locally-built-wheels-path)).

**Corollary — `app_dir` is pure-Python only.** A `.so` compiled for the host will
not load on an Android device; native code belongs in an Android wheel, never
loose in `app_dir`. `kivyforge doctor` flags a non-Android `.so` under `app_dir`.

The common case — *using* `pyjnius`/`plyer` to reach Java/Android APIs — needs no
author-side compilation: the author writes pure Python, and pyjnius arrives as a
prebuilt Android wheel.

## Distribution channel 1: Android wheels

### Source registry: PyPI direct, plus configurable supplemental indexes, plus local

Android wheels follow [PEP 738](https://peps.python.org/pep-0738/) platform tags:
`android_<apilevel>_<abi>` (e.g. `android_24_arm64_v8a`, `android_24_x86_64`).
Pure-Python wheels use `py3-none-any`. PyPI accepts and serves `android_*` wheels;
pip ≥ 25.1 installs them (including cross-download).

`[project].dependencies` resolve against **PyPI first**. Three sourcing layers,
in the same "vendored/pinned, never resolve live at build time" discipline as
every other platform:

1. **Upstream-published Android wheels** (as the ecosystem publishes them) — consumed directly from PyPI under canonical names.
2. **Supplemental indexes** via `[tool.kivy.android].extra_index_urls` (passed to pip as `--extra-index-url`); each resolved wheel's URL is pinned in the lock regardless of index.
3. **Local/vendored wheels** via `[tool.kivy.android].find_links` — supported for a user's own locally cross-built wheels, but not what this project's examples use (see below).

> **No dependency on community wheel channels.** kivyforge deliberately does **not**
> resolve against the `kivyschool` Anaconda channel or any other community index by
> default. The Kivy 2.3.1 and pyjnius Android wheels are **built by the project**
> and published to
> [`kivy-mobile-wheels`](https://github.com/ElliotGarbus/kivy-mobile-wheels), a
> personally-owned bridge repo that builds them in CI and serves them over a PEP
> 503 index (layer 2 above, `extra_index_urls`) until first-party wheels exist on
> PyPI. This keeps provenance canonical and the supply chain auditable — the same
> reasoning behind the URL+SHA discipline everywhere else. (Earlier revisions of
> this project instead vendored these wheels locally via `find_links` + a `path`
> pin, layer 3; that mechanism remains supported for a user's own local builds,
> but the project's own examples no longer use it for Kivy/pyjnius.) When Kivy and
> pyjnius publish Android wheels to PyPI, the `extra_index_urls` entry simply goes
> quiet and the dependency resolves from PyPI with no config change beyond
> dropping it.

### The Kivy wheel carries its native `.so` payload (`.libs/`)

A Kivy Android app needs SDL and other native `.so`s (`libSDL2.so`, `SDL2_image`,
`SDL2_mixer`, `SDL2_ttf`, and Kivy's own compiled modules) present in the APK and
loaded before `import`. The **Kivy Android wheel bundles these under a top-level
`.libs/` directory** — the same idea as the `auditwheel`/`delvewheel`
`<pkg>.libs/` convention on desktop wheels (vendored shared libraries carried
inside the wheel), and the Android analog of how the iOS Kivy wheel bundles its
native xcframeworks under `.frameworks/`.

The directory is **flat** — the ABI is not repeated inside it. An Android wheel is
already single-ABI: its platform tag (`android_<api>_<abi>`) is the one source of
truth for which ABI its `.so`s target, so `.libs/` needs no `<abi>/` subdirectory.

After pip installs a wheel per ABI, `kivyforge build` walks every installed wheel
for a `.libs/` directory and copies each `.so` it finds into the Gradle project's
`app/src/main/jniLibs/<abi>/`, **keyed by the wheel's own platform tag** (not by
any path inside the wheel). For the canonical Kivy app this is where the SDL
family (SDL2 or SDL3 per `[tool.kivy.android].kivy_generation`) and Kivy's compiled extensions
arrive. The wheel author (you, when cross-building Kivy) controls this payload —
which is why building your own Kivy wheel, rather than trusting a community one,
matters.

> **Flat only.** `.libs/` must be **flat**: `kivyforge build` copies the `.so`s it
> finds directly under `.libs/` and treats **any subdirectory** (including an
> `.libs/<abi>/`) as a **malformed wheel** — a hard build failure with a clear
> message. This is not a compatibility loss: the flat layout *is* the established
> convention (`auditwheel`/`delvewheel` emit `<pkg>.libs/` with no ABI folder, and
> an Android wheel is single-ABI by tag), so no standard tool produces a nested
> layout. Rejecting it keeps the **wheel tag the one source of truth for the ABI**
> — an in-wheel `<abi>/` path would be a redundant second signal that could
> disagree with the tag.

> **`.so`, not `.java`.** The `.libs/` convention delivers **native
> libraries only**. Java glue is *not* shipped in wheels (the pyjnius spike
> dropped the `.java/` dot-directory): the one small Java class pyjnius needs is a
> kivyforge bootstrap template, and SDL's Java glue is part of the bootstrap. See
> [bootstrap-android](05-bootstrap-android.md).

### Wheel content rules

Android wheels in the Kivy ecosystem must:

- Contain `.so` extension modules at importable paths (so the runtime's import machinery + the `jniLibs` load path can resolve them; see [gradle-project-generation](04-gradle-project-generation.md)).
- Bundle any host-provided-but-app-packaged native libraries under a flat top-level `.libs/` (SDL family in the Kivy wheel); the wheel's platform tag identifies the ABI, so no `<abi>/` subdirectory is used.
- Be **16 KB page-aligned** (`.so` LOAD segments): Android 15/16 devices with 16 KB pages refuse to load 4 KB-aligned libraries. Build with NDK r28+ or `-Wl,-z,max-page-size=16384` (the pyjnius wheel already satisfies this; the bootstrap and runtime `.so`s must too — a toolchain task, see [gradle-project-generation §"16 KB alignment"](04-gradle-project-generation.md#16-kb-page-alignment)). Pass the flag **explicitly** even on a toolchain that already aligns: the spike found the pyjnius wheel's alignment under NDK r27 rode on CPython-Android's *implicit* `LDFLAGS`, so its build pins the flag in its cibuildwheel config as a drift guard ([findings, Step 7](../../dev/pyjnius-android-wheel-spike-findings.md)) — a locally cross-built Kivy wheel should do the same.
- Carry **no `DT_NEEDED` on `libSDL*.so`** for the pyjnius wheel (it resolves the getter at runtime) — verified at the ELF level by the [spike findings](../../dev/pyjnius-android-wheel-spike-findings.md).
- Not require Cython/compilers at consume time (Cython is a wheel-build-only tool).

### Verification

- PyPI wheels are subject to PyPI's integrity model (HTTPS + PEP 740 attestations as they stabilize).
- The lockfile pins each wheel's SHA-256; `kivyforge build` verifies before extraction. Vendored (`path`) wheels are hashed at lock time and verified identically.

## Distribution channel 2: the python.org Android runtime

python.org publishes an official, prebuilt, relocatable **Android embeddable
package** alongside normal CPython releases (see
<https://www.python.org/downloads/android/>), for **`aarch64` and `x86_64`**. This
is the Android analog of the iOS `Python.xcframework` and the desktop
`python-build-standalone`, and it is the reason Android needs no novel runtime
story: it reuses the iOS/python.org pattern.

- **Runtime provider.** The Android backend ships a `PythonOrgAndroidProvider` **modeled on the iOS `PythonOrgProvider`** (not the desktop PBS provider). It resolves a requested CPython version to the concrete per-ABI download URLs by reading the release's file list on python.org, pins each by URL + SHA-256 in `[[tool.kivyforge.python_android]]`, and reads the runtime's minimum-API floor from the artifact metadata. See [common runtime-provider pattern](../../common/07-runtime-provider-pattern.md).
- **64-bit only.** python.org ships no 32-bit Android runtime, which is the hard reason `[tool.kivy.android].abis` rejects `armeabi_v7a`/`x86` (see [pyproject-android §"ABIs"](01-pyproject-android.md#abis-abis)).
- **No PBS Android build exists** (python-build-standalone has no Android target), so there is nothing to wait on; python.org is the source.
- **Consumption.** `kivyforge build` downloads/caches each ABI's tarball, verifies its SHA-256, extracts it, and lays the runtime out following python.org's app-integration split, extended for multi-ABI: the pure-Python stdlib into the ABI-independent asset bundle; `libpython3.x.so` and the runtime's bundled external libraries (python.org's `lib*_python.so`, e.g. OpenSSL) into `jniLibs/<abi>/` under their soname; and the stdlib's `lib-dynload` extension modules flattened into `jniLibs/<abi>/` with a manifest entry. This is the Android analog of the iOS `install_python` step; the shared-library-vs-extension-module split and the manifest/finder are detailed in [gradle-project-generation §"Native libraries and the `.so` load model"](04-gradle-project-generation.md#native-libraries-and-the-so-load-model).

## Distribution channel 3: `.aar` / `.jar` archives

`[tool.kivy.android.native.aars]` / `[tool.kivy.android.native.jars]` entries in
`pyproject.toml` are resolved against:

1. **Upstream library publishers** that ship a downloadable `.aar`/`.jar`.
2. **Locally built / vendored archives** — an author who builds their own `.aar` commits it and points `source` at a repo-relative path.

The `source` is always **explicit** — a direct URL or a repo-relative path, no
indirection strings (mirroring the iOS xcframework rule). `kivyforge lock` reads
each artifact to pin its SHA-256 into `[[tool.kivyforge.android_libs]]`;
`kivyforge build` stages it into `<app>-android/app/libs/` and wires it into
`app/build.gradle`. AGP merges an `.aar`'s manifest, resources, and any bundled
`.so`s automatically.

## Distribution channel 4: Gradle/Maven dependencies

`[tool.kivy.android.gradle].dependencies` are Maven coordinates. Unlike channels
1–3, this channel is **not** an artifact kivyforge downloads, verifies, and
stages. `kivyforge lock` emits the coordinates into a scratch `build.gradle`, runs
Gradle's dependency locking **and hash verification** to resolve the full
transitive graph, and records every module + its per-artifact SHA-256 under
`[[tool.kivyforge.gradle.resolved]]` in the lock. From there **Gradle** resolves,
fetches, and (for source-only artifacts) compiles — kivyforge writes no build
logic, but it does pin the resolved bytes.

This is the direct analog of the iOS **Swift Package Manager** channel, and it
reconciles with the core invariant the same way: the invariant is *kivyforge runs
no from-source build pipeline of its own*, and Gradle — the platform's own
first-class dependency+build system — is categorically different from a bespoke
recipe system. Integrity is enforced by the `gradle.lockfile` +
`verification-metadata.xml` that `kivyforge build` materializes from
`[[tool.kivyforge.gradle.resolved]]` — a **mandatory** content-hash check whenever
Maven deps are declared, the analog of SPM's pinned revision + `.binaryTarget`
checksums. The generated Gradle files live only in the regenerated
`<app>-android/`; the committed lock is the single source of truth.

## Lockfile-entry to project-folder mapping

`kivyforge build` materializes `pylock.android.toml` into the generated
`<app>-android/` per these rules:

| Lockfile entry | Target | Why |
|----------------|--------|-----|
| `[[packages.wheels]]` `py3-none-any` | staged Python bundle (asset) | Pure-Python; unpacked once, shared across ABIs. |
| `[[packages.wheels]]` `android_<api>_<abi>` — pure-Python content | staged Python bundle (asset) | Site-packages Python code. |
| `[[packages.wheels]]` `android_<api>_<abi>` — `.so` extension modules | `app/src/main/jniLibs/<abi>/` (flattened + manifest entry) | Native libs must live where Android extracts + loads them; the bootstrap finder maps import name → flattened file. |
| Wheel-embedded `.libs/` (e.g. Kivy's SDL family) | `app/src/main/jniLibs/<abi>/` (ABI from the wheel tag) | Same. |
| `[[tool.kivyforge.python_android]]` (per ABI) | stdlib → staged bundle; runtime `.so`s → `jniLibs/<abi>/` | Follows the embeddable package's documented layout. |
| `[[tool.kivyforge.android_libs]]` (`.aar`/`.jar`) | `<app>-android/app/libs/` + `build.gradle` reference | Gradle links/merges. |
| `[tool.kivyforge.gradle]` coordinates | emitted into `app/build.gradle`; resolved via materialized `gradle.lockfile` + `verification-metadata.xml` | Gradle owns fetch/compile; bytes pinned by SHA-256. |

`kivyforge build` keeps native libs (`jniLibs/`) and pure-Python payload (the
asset bundle) disjoint: `.so` files are loadable only from the extracted native
library directory, while Python source is unpacked to app-private storage on
first launch by the bootstrap (see [gradle-project-generation](04-gradle-project-generation.md) and [bootstrap-android](05-bootstrap-android.md)).
