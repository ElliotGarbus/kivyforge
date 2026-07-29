# Android — Compatibility Matrix

> **Status: implemented (v1).** The single authoritative view of which
> **CPython × Kivy/SDL × pyjnius (`invoke0`) × ABI × minSdk** combinations the
> Android backend supports, and how well each is validated. This document is the
> **human-readable projection of machine-checked gates** — it adds no new
> enforcement of its own. The pins it describes are enforced by `kivyforge`:
>
> - the **pyjnius / bootstrap `invoke0` range** (hard `build` gate + `doctor` FAIL — see [bootstrap-android](05-bootstrap-android.md#the-nativeinvocationhandler-matched-pair)),
> - the **SDL ↔ Kivy rule** (`kivy_generation = 2` ⇔ Kivy `< 3.0`, `kivy_generation = 3` ⇔ Kivy `>= 3.0` — `doctor` WARN),
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

> **Honest-status note (updated 2026-07-24).** The
> [contract smoke test](06-cli-android.md#--smoke-the-contract-smoke-test)
> (`kivyforge run --smoke`) now runs **green under the first-party kivyforge
> stack** — a kivyforge-generated project, built and run by `kivyforge
> build`/`run`, not p4a — on an **x86_64 API-31 emulator**
> ([load-model findings, Phase 5](../../dev/android-loadmodel-findings.md)). That
> promoted the **CPython 3.14 / Kivy 2.3.1 / SDL2 / x86_64** cell to
> **Validated (emulator)**.
>
> **Both earlier caveats are now closed.** The Kivy 2.3.1 wheel is
> **first-party** (cibuildwheel, 16 KB-aligned, official SDL 2.32.10 grafted
> with sonames intact), and **arm64 is validated on a physical device** — the
> contract smoke test passes on a Pixel 8a (Android 16 / API 36) and the app
> renders there. Both locked ABIs now pass every leg of the gate
> (`EXT_OK`, `PROXY_OK`, `KIVY_CONTRACT_OK`).
>
> **Kivy 3.0 / SDL3 promoted (2026-07-27).** The same gate now runs green on
> the SDL3 stack via the [`hello-sdl3`](../../../../examples/mobile/hello-sdl3)
> example, on the emulator **and** on the Pixel 8a, with the app visually
> confirmed rendering on the Mali-G715. Two things bound the claim and are
> stated in the row: the Kivy wheel is a **`3.0.0.dev0` snapshot**, not GA, and
> upstream `kivy.mobile` still warns that Android support "is not yet
> implemented" — so the Activity half of the bootstrap contract is exercised
> and the platform-services half does not exist to exercise.

## Runtime × framework matrix

| CPython | Kivy | SDL | pyjnius (`invoke0` contract) | Bootstrap template | Status | Evidence | Revalidate on |
|---------|------|-----|------------------------------|--------------------|--------|----------|---------------|
| 3.14 | 2.3.1 (first-party wheel) | SDL2 (2.32.10, official) | `invoke0` contract **v1** | v1 | **Validated (x86_64 emulator + arm64 device)** | `kivyforge run --smoke` green on an x86_64 API-31 emulator **and** a Pixel 8a (Android 16 / API 36); app renders on-device; both wheels first-party cibuildwheel, 16 KB-aligned ([findings](../../dev/android-loadmodel-findings.md), [recipe](../../dev/android-wheel-build-recipe.md)) | new pyjnius release (esp. one moving the `invoke0` marker); new Kivy 2.x; CPython 3.14 point releases that change the ABI tag; new AGP/NDK major; **any SDL release change — the Java glue and `libSDL2.so` must move together** |
| 3.14 | 3.0.0.dev0 (first-party wheel) | SDL3 (3.4.12, official) | `invoke0` contract **v1** | v1 | **Validated (x86_64 emulator + arm64 device)** | `kivyforge run --smoke` green on an x86_64 API-31 emulator **and** a Pixel 8a (Android 16 / API 36) with the [`hello-sdl3`](../../../../examples/mobile/hello-sdl3) gate; app renders on-device (Mali-G715, `Window`/`GL`/`text`/`img` all `sdl3`) ([findings](../../dev/android-loadmodel-findings.md#kivy-30--sdl3-on-device-first-run)) | **Kivy 3.0 GA** (this is a `.dev0` snapshot); any change to the SDL3 Java glue or `libSDL3.so` — **they move together**; upstream `kivy.mobile` gaining a real Android implementation |
| 3.15 | 2.3.1 / 3.0 | per Kivy | `invoke0` contract **v1** (pending wheel) | v1 | **Pending** | CPython 3.15 is pre-release; `android_*` wheels for `cp315` not yet published | CPython 3.15 GA; availability of `cp315` Kivy/pyjnius wheels |

Notes:

- **pyjnius `invoke0` contract v1** is the version range carried by the current
  bootstrap template's compatibility marker. kivyforge **fails the build** (and
  `doctor` FAILs) for a locked pyjnius outside it; widening the range is a
  bootstrap-template change that adds a new contract version here.
- **The local Kivy 2.3.1 wheel** is kivyforge-built (no dependency on third-party
  channels), per [artifact-distribution-android](03-artifact-distribution-android.md).
- **Kivy 3.0 / SDL3** is first-class in the schema (`kivy_generation = 3`) and now exercised
  on-device against a `3.0.0.dev0` wheel. The row returns to **Pending** on
  Kivy 3.0 GA, since a snapshot is not the released artifact.
- **The SDL Java glue and the `libSDL*.so` are a matched pair** in both
  generations. `check_sdl_glue_contract()` fails the build on a mismatch,
  because `SDLActivity` aborts `onCreate` *silently* otherwise — no logcat, no
  traceback, a black screen ([findings](../../dev/android-loadmodel-findings.md#the-sdl-java-glue-and-libsdl2so-are-a-matched-pair-silent-failure)).

## ABI × minSdk

64-bit only — the python.org Android embeddable package ships no 32-bit runtime,
and kivyforge does not support `armeabi-v7a` / `x86`.

| ABI | Role | minSdk floor | Wheel-tag rule | Status |
|-----|------|--------------|----------------|--------|
| `arm64_v8a` | **shipping target** (physical devices) | 24 | `wheel_tag_api ≤ min_sdk` | **Validated** (Pixel 8a, Android 16 / API 36) |
| `x86_64` | emulator / CI | 24 | `wheel_tag_api ≤ min_sdk` | **Validated** (x86_64 emulator, API 31) |
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
| Row is **Validated** | `kivyforge run --smoke` green on a cited first-party emulator **and** device run — not hosted CI, which has no device ([cli-android](06-cli-android.md#what-kivyforges-own-ci-gates-and-what-it-doesnt)) |
| The generated project actually compiles | The hosted `android_gradle` job (AGP/AAPT/javac/NDK build of `hello-android` + the release policy path) on every push |

Because every row maps to a gate the tool already enforces, this matrix is a
*view*, not a second source of truth — updating a bootstrap template or a schema
rule is what moves the corresponding cell.
