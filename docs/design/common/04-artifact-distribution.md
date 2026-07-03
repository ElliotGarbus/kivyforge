# 04 — Artifact Distribution

kivyforge is an **assembler of prebuilt artifacts**, not a from-source build system. This document defines the cross-platform rules for where artifacts come from, how they are verified, and the one invariant that shapes the whole architecture. Per-platform channel details live in each platform's doc (e.g. [iOS artifact distribution](../platforms/ios/artifact-distribution-ios.md)).

## The core invariant: no from-source build pipeline

> **kivyforge runs no from-source build pipeline of its own.** It does not resurrect a recipe system (building Python, OpenSSL, and dozens of libraries through a bespoke framework on the user's machine), and it does not cross-compile Python C extensions. Those are the genuinely painful, non-reproducible, toolchain-version-sensitive steps the architecture exists to eliminate.

What kivyforge *does* compile is the small platform bootstrap (e.g. iOS `main.m`) and whatever the **platform's own maintained toolchain** compiles as a first-class operation (Xcode linking/embedding frameworks; Xcode's Swift Package Manager compiling a source package; a platform linker producing a launcher). Deferring to the platform's vendor-supported mechanism is categorically different from a bespoke recipe system, and does not reopen that wound.

Consequences that hold on every platform:

- **Python dependencies arrive as wheels.** Platform-tagged binary wheels (PEP 730 iOS, PEP 738 Android, standard desktop tags) for compiled packages; `py3-none-any` for pure-Python. `toolchain lock` resolves and pins them; `toolchain build` installs the pins.
- **The Python runtime is prebuilt.** kivyforge downloads a prebuilt runtime for the target (e.g. python.org's `Python.xcframework` for iOS) rather than building Python.
- **App-authored native code must be pre-built into a wheel.** A user's own Cython/C extension is "an artifact that doesn't exist yet": the author cross-builds it into a platform wheel out-of-band (`cibuildwheel`, the python.org/Briefcase flow, etc.) and then consumes it like any other dependency — hosted on an index, or vendored and pinned by `path`. kivyforge never compiles it.

## Sourcing model

- **PyPI direct, with configurable supplemental indexes.** `[project].dependencies` resolve against PyPI first. For packages whose platform-tagged wheels aren't on PyPI yet, the platform overlay may declare supplemental `extra_index_urls`; each resolved wheel's URL is pinned in the lock regardless of which index supplied it. Whether any supplemental index is Kivy-operated or third-party is an organizational question outside this tool's scope.
- **Vendored artifacts by repo-relative `path`.** A wheel or native artifact built by the author can be committed to the repo and pinned by a repo-relative `path` (PEP 751 semantics: relative to the lockfile, POSIX separators, no absolute/escaping paths). This resolves identically on every clone and CI runner.
- **No new registry or package format.** kivyforge reuses PyPI for wheels and standard release hosting (e.g. GitHub Releases, python.org) for native artifacts; it stands up no bespoke format.

## Integrity and verification

- **Content-hash pinning.** Every artifact the lock references — wheel or native archive — carries a SHA-256 that `toolchain build` verifies before extraction. A mismatch aborts the build with the artifact name, URL, expected/actual hash, and a tamper hint.
- **Documented exception: platform-owned source channels.** Where a platform's own toolchain fetches and builds a source dependency (notably Xcode's SPM source packages), there is no stable *output* hash to pin. Those channels pin the **input** instead — the resolved Git revision (plus the platform's own checksum for binary targets) — a deliberate, scoped deviation documented with the channel (see [iOS Swift packages](../platforms/ios/swift-packages.md)). Wheels and directly-referenced native archives remain kivyforge-verified by SHA-256.

## Per-platform channels

Each platform instantiates these rules with its own native-dependency channels and staging layout:

- **iOS** — iOS wheels, `.xcframework` archives, and Swift Package Manager packages. See [iOS artifact distribution](../platforms/ios/artifact-distribution-ios.md).
- **macOS / Linux / Windows / Android** — documented as each platform lands.
