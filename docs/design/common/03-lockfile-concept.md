# 03 — Lockfile Concept

Every target platform produces a **reproducibility artifact**: a per-platform lockfile that pins the exact Python wheels, the exact runtime, and any exact native artifacts a build will use — by URL and SHA-256. `toolchain lock` generates it from `pyproject.toml`; `toolchain build` consumes it.

This document defines the cross-platform lockfile *pattern*. The concrete schema for each platform lives in its own doc (e.g. [iOS `pylock.ios.toml`](../platforms/ios/pylock-ios-spec.md)).

## Filename carries the platform

The lockfile is named `pylock.<platform>.toml`, sibling to `pyproject.toml`:

- `pylock.ios.toml`, `pylock.macos.toml`, `pylock.android.toml`, `pylock.windows.toml`, `pylock.linux.toml`.

This follows PEP 751, which reserves `pylock.toml` for a project's "default" lock and accepts `pylock.<name>.toml` for additional platform/variant locks. **The platform is identified entirely by the filename.** A single `pyproject.toml` with multiple `[tool.kivy.<platform>]` overlays therefore produces one committed lock per target, side by side.

## PEP 751 conformance + a single `[tool.kivyforge]` extension

Two parts coexist in every lock:

1. **Standard PEP 751 `[[packages]]`.** A valid PEP 751 lock that any PEP 751-aware consumer (pip, uv, pdm, …) can *read* without knowing anything about kivyforge. Each entry pins a package by name/version with per-wheel `url` (or repo-relative `path`) and `hashes`.
2. **A single `[tool.kivyforge]` extension table.** PEP 751 permits per-tool extension tables under `[tool.<name>]`. kivyforge stores everything PEP 751 doesn't model — the platform runtime, native artifacts, per-wheel source-index provenance, the source-`pyproject.toml` hash, schema versions — under **one brand-based table**, `[tool.kivyforge]`, in every lock regardless of platform.

kivyforge drives the install itself from the pinned per-wheel URLs and hashes rather than depending on a generic installer's lockfile reader. pip 26.1 added an experimental `-r pylock.toml` reader, but it is scoped to replicating a lock into the *host* environment: it performs no target-platform selection, and pip has explicitly declined to pick a `pylock.<platform>.toml` by filename (PEP 751's multi-platform story is in-file environment markers, not per-platform files). Neither fits kivyforge's model of cross-building for an explicit target from a per-platform lock, and the reader remains experimental (subject to change or removal). Everything kivyforge needs lives under `[tool.kivyforge]`, and kivyforge does not depend on any installer understanding that table.

### No platform discriminator field

`[tool.kivyforge]` contains **no platform discriminator**. The filename (`pylock.ios.toml` vs `pylock.macos.toml`) already identifies the platform, and the tool derives the platform from the resolved target — a redundant in-file field would only create an opportunity for the two to disagree. A light check that the expected platform sub-tables are present is acceptable for producing clear errors.

## What the extension table holds

The exact contents are platform-specific, but the pattern is consistent. `[tool.kivyforge]` typically holds:

- **Scalar provenance / integrity fields** — `schema_version` (of the extension table), `toolchain_version`, `generated_at`, and `pyproject_sha256` (the SHA-256 of the source `pyproject.toml`, used for **drift detection**: `toolchain build` recomputes it and refuses a lock that no longer matches, unless `--no-verify-lock`).
- **The platform runtime pin** — e.g. the iOS `[tool.kivyforge.python_xcframework]` (version + URL + SHA-256). Other platforms pin their own runtime equivalent.
- **Native artifact pins** — repeatable sub-arrays for platform-native dependencies (e.g. iOS `[[tool.kivyforge.xcframeworks]]`, `[[tool.kivyforge.swift_packages]]`).
- **Per-package tool metadata** — via PEP 751's per-package `[packages.tool.kivyforge]` (e.g. `direct_requirement`, `source_index`), invisible to other PEP 751 consumers.

## Independent version numbers

A lock carries several version numbers that evolve on different cadences:

| Version | Owner | Bump when |
|---------|-------|-----------|
| `lock-version` | PEP 751 (upstream Python packaging) | Upstream PEP revision. kivyforge refuses to read a major higher than it understands. |
| `[tool.kivyforge].schema_version` | kivyforge | Backward-incompatible change to anything under `[tool.kivyforge]`. Additive changes don't bump. |
| Overlay echo (e.g. `tool_kivy_ios_schema_version`) | kivyforge (echoed from pyproject) | Records the source `[tool.kivy.<platform>].schema_version` so the lock survives overlay schema bumps unambiguously. |

## Resolution + integrity, in brief

`toolchain lock` for a target:

1. Parses and validates `pyproject.toml` (`[project]`, `[tool.kivy]`, the target's overlay).
2. Pins the platform runtime.
3. Resolves `[project].dependencies` for the target's platform tags (host-independent), pinning every wheel by `url`/`path` + `hashes`. Compiled packages may pin multiple platform-tagged wheels; a package missing a required tag, or resolving to inconsistent versions across tags, is a **fail-fast** at lock time (see the iOS spec for the canonical treatment).
4. Pins any native artifacts declared in the overlay.
5. Writes `pylock.<platform>.toml` atomically, with deterministic ordering so diffs show only real changes.

Every artifact download is verified against its pinned SHA-256 before use; a mismatch aborts the build.

## Relationship to PEP 751

kivyforge's per-platform-file approach is **conformant with PEP 751**, and diverges only from its *preferred idiom* — a deliberate, documented trade-off:

- **The filename is spec-sanctioned.** PEP 751 requires a lock to be named `pylock.toml` or match `^pylock\.([^.]+)\.toml$` "if a name for the lock file is desired or if multiple lock files exist." `pylock.ios.toml` / `pylock.macos.toml` are exactly that. (The PEP's own worked example frames the `<name>` slot around use-cases/dependency-groups rather than platforms, so we use a generic extension point somewhat beyond its headline example — within the letter, if not the first illustration.)
- **Single-use locks are first-class.** PEP 751 supports both single-use and multi-use locks and states neither is better; each `pylock.<platform>.toml` is a conformant single-use lock any PEP 751-aware tool can read.
- **We opt out of the in-file marker idiom, because cross-compilation breaks it.** PEP 751's headline multi-platform mechanism is *one* file with per-package PEP 508 markers, where the installer selects the subset matching **the environment it is currently running in**. That assumes install-target == running interpreter. When kivyforge builds for iOS, the interpreter runs on **macOS**, and no standard marker expresses "resolve for iOS while running on a macOS host." Worse, iOS **device** and **simulator** are both `sys_platform == 'ios'` and differ only via `platform.ios_ver().is_simulator`, which is **not** a PEP 508 marker — so a single marker-file cannot even encode that split. Per-platform files sidestep all of this and map `--platform` → file deterministically.

The one concrete cost: generic installers won't platform-select our files by filename (pip explicitly declined this). That is acceptable because kivyforge owns wheel selection and install; each individual file stays a readable PEP 751 document regardless.

## Prior art: uv

[uv](https://docs.astral.sh/uv/) is the most developed take on this problem and reached the **opposite container choice**, which is instructive:

- **One universal `uv.lock`, not per-platform files.** uv's native lock captures "all possible Python markers (OS, architecture, Python version)" in a single file, using *fork-based* resolution (disjoint-marker entries + per-package wheel lists) to hold divergent graphs, tuned via `--fork-strategy`, `environments`, and `required-environments`.
- **A target-override flag makes cross-targets work.** The mechanism plain pip's `-r pylock.toml` reader lacks: `uv pip compile --python-platform <triple>` overrides the markers/tags instead of reading the host's. Accepted values include **native PEP 730/738 mobile tags** — `arm64-apple-ios`, `arm64-apple-ios-simulator`, `aarch64-linux-android`, `x86_64-linux-android` (with `IPHONEOS_DEPLOYMENT_TARGET` / `ANDROID_API_LEVEL`).
- **PEP 751 is uv's interchange, not its working format.** uv keeps `uv.lock` because "some of uv's functionality cannot be expressed in pylock.toml," but exports/consumes pylock (`uv export -o pylock.toml`, `uv pip compile -o pylock.toml`, `uv pip install -r pylock.toml`) — the same posture kivyforge takes with its PEP 751 core plus a native `[tool.kivyforge]` table.

Two takeaways. First, uv **validates the model**: its maintainers state iOS/Android installs are "almost always cross-platform installs, running on a macOS/Linux/Windows build system targeting an iOS/Android host," and that `--python-platform` selects wheels but does not build from source cross-platform — exactly kivyforge's binary-only, host-independent invariant. Second, both tools require an explicit target override; the only real difference is the container (uv's universal file vs. our per-platform files), and the device/simulator split — which even uv resolves as *separate* `--python-platform` invocations — is what tips kivyforge toward per-file. (This also makes uv a credible alternative resolver backend, since it natively knows the mobile tags and can emit `pylock.<platform>.toml`; see [resolver findings](../dev/resolver-findings.md).)

## Concrete schema

See the per-platform lockfile documents for the full field reference:

- [iOS — `pylock.ios.toml`](../platforms/ios/pylock-ios-spec.md)
