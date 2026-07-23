# Android — Compatibility Matrix

> **Status: design.** The single authoritative view of which
> **CPython × Kivy/SDL × pyjnius (`invoke0`) × ABI × minSdk** combinations the
> Android backend supports, and how well each is validated. This document is the
> **human-readable projection of machine-checked gates** — it adds no new
> enforcement of its own. The pins it describes are enforced by `kivyforge`:
>
> - the **pyjnius / bootstrap `invoke0` range** (hard `build` gate + `doctor` FAIL — see [bootstrap-android](05-bootstrap-android.md#the-nativeinvocationhandler-matched-pair)),
> - the **SDL ↔ Kivy rule** (`sdl = 2` ⇔ Kivy `< 3.0`, `sdl = 3` ⇔ Kivy `>= 3.0` — `doctor` WARN),
> - the **wheel-tag policy** (`wheel_tag_api ≤ min_sdk` — see [pyproject-android](01-pyproject-android.md)),
> - the **ABI set** (64-bit only; `arm64_v8a` + `x86_64`).
>
> When a gate's marker changes (e.g. a new bootstrap template widens the pyjnius
> range), the matching cell here changes with it — so the table cannot silently
> drift from what the tool enforces.

## How to read this

Compatibility knowledge goes stale as CPython, Kivy, pyjnius, AGP, and the NDK
move. Rather than stamping rows with calendar **expiry** dates (which become
maintenance noise), each row carries a **validation status** and one or more
**revalidation triggers** — the concrete events that demote a row back to
*Pending* until it is re-exercised. The **only** genuinely calendar-driven
constraint (Google Play's rising `target_sdk` requirement) is called out
separately at the end.

### Status legend

| Status | Meaning |
|--------|---------|
| **Validated** | Exercised on-device by a **first-party, cited** run (emulator **and** hardware) for this exact combination. |
| **Prototype** | Exercised only by the [pyjnius spike](../../dev/pyjnius-android-wheel-spike-findings.md)'s prototype (and/or community wheels) — indicative, **not** first-party validation. |
| **Pending** | Not yet exercised; expected to work by construction but unproven. |
| **By construction** | No separate run needed — the path is identical to a Validated/Prototype one except for a mechanically-substituted component (documented in the row). |

> **Honest-status note.** Per the
> [spike findings](../../dev/pyjnius-android-wheel-spike-findings.md), no
> combination is marked **Validated** yet: the spike's on-device runs used a p4a
> test harness (not the kivyforge stack), and the first-party PyPI pyjnius wheel
> and the SDL3-host run are still open. Rows reflect
> **Prototype / Pending** accordingly. The [contract smoke test](06-cli-android.md#--smoke-the-contract-smoke-test)
> (`kivyforge run --smoke`) is the mechanism that promotes a row to **Validated**
> once it runs green in first-party CI.

## Runtime × framework matrix

| CPython | Kivy | SDL | pyjnius (`invoke0` contract) | Bootstrap template | Status | Evidence | Revalidate on |
|---------|------|-----|------------------------------|--------------------|--------|----------|---------------|
| 3.14 | 2.3.1 (kivyforge-built local wheel) | SDL2 | `invoke0` contract **v1** | v1 | **Prototype** | [spike prototype](../../dev/pyjnius-android-wheel-spike-findings.md): x86_64 emulator + arm64 device (Pixel 8a); plus community `android_24` wheels | new pyjnius release (esp. one moving the `invoke0` marker); new Kivy 2.x; CPython 3.14 point releases that change the ABI tag; new AGP/NDK major |
| 3.14 | 3.0 | SDL3 | `invoke0` contract **v1** | v1 | **Pending** | tier-1 `SDL_GetAndroidJNIEnv` path is identical **by construction** to the SDL2 path, but not yet exercised | Kivy 3.0 GA; first SDL3 on-device run; any change to the SDL3 Java glue |
| 3.15 | 2.3.1 / 3.0 | per Kivy | `invoke0` contract **v1** (pending wheel) | v1 | **Pending** | CPython 3.15 is pre-release; `android_*` wheels for `cp315` not yet published | CPython 3.15 GA; availability of `cp315` Kivy/pyjnius wheels |

Notes:

- **pyjnius `invoke0` contract v1** is the version range carried by the current
  bootstrap template's compatibility marker. kivyforge **fails the build** (and
  `doctor` FAILs) for a locked pyjnius outside it; widening the range is a
  bootstrap-template change that adds a new contract version here.
- **The local Kivy 2.3.1 wheel** is kivyforge-built (no dependency on third-party
  channels), per [artifact-distribution-android](03-artifact-distribution-android.md).
- **Kivy 3.0 / SDL3** is first-class in the schema (`sdl = 3`) but its on-device
  path is unexercised until Kivy 3.0 ships the SDL3 host.

## ABI × minSdk

64-bit only — the python.org Android embeddable package ships no 32-bit runtime,
and kivyforge does not support `armeabi-v7a` / `x86`.

| ABI | Role | minSdk floor | Wheel-tag rule | Status |
|-----|------|--------------|----------------|--------|
| `arm64_v8a` | **shipping target** (physical devices) | 24 | `wheel_tag_api ≤ min_sdk` | **Prototype** (spike arm64 device) |
| `x86_64` | emulator / CI | 24 | `wheel_tag_api ≤ min_sdk` | **Prototype** (spike x86_64 emulator) |
| `armeabi-v7a`, `x86` (32-bit) | — | — | — | **Unsupported** (no 64-bit-only python.org runtime) |

- **minSdk floor is 24** — the first API level with RUNPATH (auditwheel's grafted-`.so` requirement), ~99% device coverage, and the floor the python.org runtime and the Android wheel-tag ecosystem target. Rejected below 24.
- A wheel's tag API level is a **floor**: it must be `≤ min_sdk`, and `kivyforge lock` accepts the highest-tag wheel whose API level is `≤ min_sdk` (never rejecting a compatible lower-tag wheel).

## Revalidation triggers (not calendar expiry)

A row drops to **Pending** (and the smoke gate must re-run to restore it) when any
of these occurs:

- **A new CPython minor** (e.g. 3.16) — new ABI tag, possibly a new embeddable-package layout.
- **A new Kivy release or an SDL-generation change** (2.x → 3.0, i.e. SDL2 → SDL3).
- **A new pyjnius release**, especially one that moves the `invoke0` compatibility marker (which also flips the hard build gate).
- **An AGP or NDK major bump** — affects the native-launcher compile, 16 KB alignment, and packaging.
- **A new Android platform requirement** that changes the load model (e.g. a future page-size or linker change beyond the 16 KB one already handled).

Each backend release should re-run `kivyforge run --smoke` across the supported
rows and update the **Status/Evidence** columns from the results.

## The one calendar constraint: Play `target_sdk` deadlines

Google Play enforces a **rising `target_sdk`** for new apps and updates on **fixed
annual deadlines** (typically ~one year after each Android release). This is the
only compatibility fact that genuinely expires on a date rather than on a
component change:

- Keep `[tool.kivy.android].target_sdk` at or above Play's current floor for new
  submissions; `compile_sdk` must be `≥ target_sdk`.
- kivyforge does **not** hardcode the deadline calendar (it would be a
  maintenance/drift liability, per the toolchain policy); consult
  [Google Play's target API level requirements](https://developer.android.com/google/play/requirements/target-sdk)
  before a submission window.

## Relationship to enforcement (no drift by design)

| Fact in this doc | Enforced by |
|------------------|-------------|
| pyjnius `invoke0` range | Hard `build` gate + `doctor` **FAIL** ([bootstrap](05-bootstrap-android.md#the-nativeinvocationhandler-matched-pair)) |
| SDL ↔ Kivy rule | `doctor` **WARN** ([cli-android](06-cli-android.md)) |
| `wheel_tag_api ≤ min_sdk` | `kivyforge lock` selection + `doctor` ABI coverage ([pyproject](01-pyproject-android.md)) |
| 64-bit-only ABI set | `[tool.kivy.android].abis` validation ([pyproject](01-pyproject-android.md)) |
| Row is **Validated** | `kivyforge run --smoke` green in first-party CI ([cli-android](06-cli-android.md#--smoke-the-contract-smoke-test)) |

Because every row maps to a gate the tool already enforces, this matrix is a
*view*, not a second source of truth — updating a bootstrap template or a schema
rule is what moves the corresponding cell.
