# Roadmap

> **Status: re-planned 2026-09-12** after a break in development. The
> 2026-07-30 queue had six items; P0 (PyPI name) and P1 (safe-area examples)
> shipped, P2–P5 were never started, and four new items have been added.
> Active items are now numbered 1–8; each one that had an old label says so, so
> a commit message mentioning "P2" or "P3" still resolves.
>
> Standing decisions, unchanged: **aarch64 is cross-build capable** ·
> **docs are MkDocs Material → GitHub Pages** · **PyPI stays a solo-owner
> personal project until the GitHub repo moves to the Kivy org** ·
> **no emulation anywhere in the build path**.

## Where things stand

Phase B (byte-compile / `strip_source`) is implemented across Android, the
three desktop backends, and iOS, and is validated on a real Windows release
build **and on Android** (Pixel 8a, 2026-09-13 — see item 1). iOS is still
unvalidated, and needs a Mac.

- **Item 1 is done (2026-09-13).** CPython 3.14.7 (64-bit) is installed, Android
  `strip_source` has produced a real `.pyc`-only bundle that runs on a Pixel 8a,
  and the byte-compile doctor check ships on all five backends. It also exposed
  and fixed a live resolver bug; see the item.
- **Item 2 is done (2026-09-13).** [`test-matrix.md`](test-matrix.md) now answers
  "which host × target × tier has actually been exercised, and when", and the
  tier markers make it selectable. It found that **only Android has real
  toolchain coverage** — no CI job runs `kivyforge build` for any desktop target
  — and closed a second silent-skip hole of item 1's exact shape.
- **[`test-matrix.md`](test-matrix.md) was reviewed and corrected (2026-09-13).**
  Every claim in the review checked out against the code. The corrections that
  change *this* file are folded in below: the desktop lock blocker also blocks
  Windows, the markers do not describe what CI runs, and two new gaps came out of
  it — Android T3 has never run from a Windows host (item 1's own code path), and
  `kivyforge run` cannot produce a release build at all, so it can never exercise
  `strip_source`. The latter is a product hole, not a test gap.
- **Item 5's Android T3 slice is done (2026-09-13)**, pulled ahead of item 3
  because `android_gradle` was already building the stripped release APK that
  item 1's bug would have corrupted and never inspecting it. Item 1's failure mode
  is now a CI gate. **Item 3 is next**; item 5's remaining first move is a Linux
  build job, once the committed-lock blocker is cleared.
- **iOS is validated on the simulator and nowhere else** — corrected 2026-09-14,
  because both this file and the matrix had drifted into implying nothing iOS had
  ever run. `build`/`run -p ios --simulator` are green and all six iOS examples
  render, as first-party local runs in July. What is unproven is `strip_source`,
  any physical device, signing/provisioning, and any T3 on the built `.app` — and
  no amount of Windows-side work changes that: it needs the Mac.

## Execution order

| # | Item | Size | Gate |
|---|---|---|---|
| ~~1~~ | ~~Validate mobile `strip_source`, then the byte-compile doctor check~~ *(was P2)* | S | **done 2026-09-13** |
| ~~2~~ | ~~Test matrix + test plan~~ → [`test-matrix.md`](test-matrix.md) | S–M | **done 2026-09-13** |
| 3 | Output layer: `rich` rendering + `--json` | M | none |
| 4 | Linux aarch64 → Raspberry Pi target *(was P3)* | L | Linux host; Pi hardware to finish |
| 5 | E2E automation against the matrix — *Android T3 slice done 2026-09-13* | M–L | items 2, 3 |
| 6 | End-user docs *(was P4)* | M | items 3, 4 (settled surface) |
| 7 | Real 3.0.0 + Kivy transition *(was P5)* | M | GitHub repo transfer |
| 8 | `native_integration` support (Android + iOS) | XL | item 7; spec freeze |
| 9 | Byte-compile the embedded stdlib at build time (desktop) | S | none; wants a macOS host to confirm the signing side |

**Why this order.** Item 1 was first because it closes a *correctness* gap: a
feature that ships today could silently strip sources and produce a bundle a
device refuses to import. That instinct paid off — the work exposed a second,
live bug (two disagreeing interpreter resolvers, so iOS and cross-arch desktop
silently shipped source) that nothing else on this list would have surfaced.
Nothing should be built on top of an unvalidated packaging path.

Item 2 was second because it is cheap writing and it is what makes the rest of
this list decidable — before it, "is Android byte-compile proven?" was answered
by prose in this file and by hand-inspecting a staged bundle, which is exactly
how the item-1 gap survived from July to September. It earned its place twice
over: writing the coverage down turned up a second silent-skip hole (the macOS
Mach-O tests) and gave item 5 an ordered gap list instead of a blank page.

Items 3, 4 and 5 are ordered by *how much rework the other order costs*.
`rich` and `--json` are one item, not two, because both rewrite the same ~119
`click.echo` call sites — done separately, every output site is edited twice.
And that layer lands before aarch64 so the new Linux code is written against
the final console API, and before E2E automation because asserting on a JSON
envelope is far more durable than screen-scraping progress text.

Item 6 wants a settled CLI surface, which item 3 changes (it adds `--json`
everywhere) and item 4 changes (it adds an arch). Item 7 is event-driven
rather than order-driven — nothing in it should start before the repo actually
moves — but it wants docs to link to, so it sits after item 6.

Item 8 is last by its own stated condition — "after all platforms are working
and tested" — and because it is the largest thing on this list by a wide
margin. It has one cheap early move that is worth taking out of order; see the
item.

Item 9 is last by size rather than by dependency — it is small and blocks
nothing — but it is on the list at all because it is *measured*, not suspected:
170 ms of every desktop launch, established on 2026-09-15 and written down in
[`test-matrix.md`](test-matrix.md) §5.10 and §7.

`build-for` vs `build-on` architecture (previously tracked as its own deferred
item) is **not** listed separately: Linux aarch64 is precisely the case that
makes it live, so it is folded into item 4.

---

## Completed

Kept in full as the record of what was decided and why. Both shipped
2026-07-31. Where the text below defers something "to P5", read **item 7**.

### P0 — Reserve `kivyforge` on PyPI

**Why first.** Verified 2026-07-30: `pypi.org/pypi/kivyforge/json` returns
404, so the name is free — and squattable. There is no PyPI mechanism to
reserve a name other than uploading, so a real (pre-release) upload is the
action.

**Ownership model — and why it is not an org.** Verified: there is no PyPI
organization named `kivy` (`/org/kivy/` 404s), and Kivy itself does not use
one — `pypi.org/project/Kivy/` is owned by individual maintainer accounts
(`kivybot`, `matham`, `Mathieu.Virbel`, `misl6`, `tshirtman`), as is the rest
of the ecosystem (`buildozer`, `pyjnius`, `pyobjus`, `kivy-deps.*`). So
"transitioning to the Kivy domain" on PyPI means **adding Kivy maintainer
accounts as Owners**, not migrating into an org. Creating a PyPI org for Kivy
is a governance decision for Kivy leadership and is explicitly out of scope
here.

**Decision: publish personally, solo owner, until the GitHub repo transfers.**
Co-owners and Trusted Publishing are both deferred to P5 so all ownership
changes happen once, together.

**Trusted Publishing is deliberately NOT set up yet.** OIDC binds to
(repo owner, repo name, workflow file, environment). Configuring it now
against `ElliotGarbus/kivyforge` means configuring it twice — and leaving a
*stale* entry after the repo moves is a live security hole: GitHub allows the
vacated path to be re-created by anyone (repo-jacking), and a stale trusted
publisher would let whoever claims it publish to our project. Configure OIDC
exactly once, against the final `kivy/kivyforge` path, in P5. Until then the
existing API token is the correct tool.

**Work**

- Confirm `secrets.pypi_password` holds a `pypi-…` **API token** (the secret
  name predates the convention and reads like a password).
- Tidy `.github/workflows/pypi-release.yml`: it triggers `on: [push]`, so it
  builds a wheel on every push to every branch and only gates the *publish*
  step on a tag. Narrow the trigger to tags (+ `workflow_dispatch`).
- Sanity-check the long-description render — `twine check dist/*` is already
  in the workflow and covers this.
- Tag `v3.0.0.dev0` and let the workflow publish.

**Notes**

- **Pre-releases are not as invisible as they look.** pip excludes a
  pre-release only when a **stable release also exists**; when a pre-release
  is the *only* release on the index, `packaging`'s specifier filter falls
  back to it. So while `3.0.0.dev0` is the sole release, a plain
  `pip install kivyforge` installs it — `--pre` is not required. This
  corrects an earlier assumption recorded here; verified empirically against
  the live index in a clean venv. It resolves itself once a stable `3.0.0`
  ships. If the package must be non-installable in the meantime, **yank**
  `3.0.0.dev0` (PEP 592): a yanked release still holds the name, and stays
  installable when pinned exactly, but is skipped by ordinary resolution.
- `[project.urls]` still points at `ElliotGarbus/kivyforge`. That is accurate
  today; it is a P5 transition task, not a P0 blocker.
- The default branch is `modernization-rfc` (with a stale `master` present).
  Tags are branch-independent so this does not block the release, but the
  branch situation should be resolved before the real 3.0.0.

**Done when** `pip install --pre kivyforge` installs `3.0.0.dev0` from PyPI.
**— done 2026-07-31**, published from tag `v3.0.0.dev0` (commit `191b5829`);
wheel + sdist both live, verified by clean-venv install from the live index.

**Token scope — done 2026-07-31.** The first upload had to use an
**account-scoped** token, because project-scoped tokens can only be minted for
projects that already exist. Once `kivyforge` existed the GitHub secret was
replaced with a token scoped to `kivyforge` alone and the account-scoped one
deleted, so a leaked CI secret cannot reach anything else on the account. A
stopgap either way — P5 removes the token entirely in favour of OIDC.

The scoped token is untested until the next upload: PyPI has no
token-validation endpoint, and `workflow_dispatch` skips the publish step
(it is gated on `refs/tags/`). That is acceptable because an auth failure
consumes no version — the next tag is a safe test.

---

### P1 — Safe-area usage in the mobile examples

**Current state.** 2 of 11 mobile examples already use
`kivy.mobile.get_safe_area()`: `mobile-geometry` (308 lines — the dedicated
reference demo for the geometry API) and `svg-explorer` (192 lines, uses it
idiomatically for real layout).

**Scope: the five real-UI examples.**

| Example | Lines | Action |
|---|---|---|
| `pyobjus-ball` | 368 | add |
| `pyobjus-deviceinfo` | 217 | add |
| `keychain-spm` | 192 | add |
| `qr-maven` | 119 | add |
| `pyjnius-deviceinfo` | 86 | add |
| `hello-kivy` / `hello-sdl3` / `hello-android` / `hello-world` | 23 / 17 / 13 / 3 | **skip** |

The four `hello-*` examples exist to prove the toolchain boots at all;
safe-area handling would bury that signal in layout code. They stay minimal
on purpose.

**Implementation.** Follow `svg-explorer`'s `safe_area_insets()` helper: it
imports `kivy.mobile` defensively (degrades to zeros when absent, so the
example still runs on desktop), and converts UIKit points to Kivy pixels via
`get_scale()`. Duplicate that small helper per example rather than factoring
it into a shared module — examples must stay individually copy-pasteable, and
a shared import would make each one non-self-contained.

`mobile-geometry` stays the *reference* demo (it visualizes the insets with an
overlay); the five above should consume the API idiomatically for layout, not
re-demonstrate it.

**Done when** each of the five insets its content past the notch / Dynamic
Island / home indicator, and still runs unchanged on desktop.
**— done 2026-07-31.**

**Two things the work turned up, both since resolved.** The units differ per
platform: `get_safe_area()` returns UIKit **points** on iOS but **pixels** on
Android, and Kivy's own `kivy/mobile/__init__.py` documents "layout points"
for both with no caveat. Following that doc scaled Android by the display
density (2–3.5×); the helper now scales iOS only.

And Kivy 2.3.1 has no `kivy/mobile` module at all, so the three Android
examples on `kivy_generation = 2` can never report a safe area. Rather than
move them to generation 3 — which would collapse the gen-2/gen-3 coverage
split the compatibility matrix tracks — a purpose-built generation-3 example
was added: `examples/mobile/android-safe-area`. Validated on an API-36
emulator (x86_64) and a Pixel 8a (arm64_v8a).

---

## Active queue

### 1. Validate mobile `strip_source`, then add the byte-compile doctor check

*Was P2, and now explicitly two deliverables in this order: the validation is
the point, the check is what stops the gap recurring.*

> **Prerequisite: install a final CPython 3.14, 64-bit.**
>
> Re-verified 2026-09-12: the dev machine's only CPython 3.14 is still
> `3.14.0a7`, which the release-level guard correctly refuses. It is also a
> **32-bit** install (`Python314-32`) and still the `*` default for
> `py -3.14`, so it wins the launcher's lookup. The releaselevel is the
> blocker — a `.pyc`'s magic number is keyed to the minor version, not the
> word size, so 32-bitness would not by itself break byte-compiling — but
> install 64-bit anyway and remove the alpha. Every Android build here
> currently takes the degrade path and ships source.
>
> The consequence is easy to miss: **`strip_source` has
> never actually executed on Android or iOS.** Phase B shipped it for the
> mobile backends, the unit tests cover the mechanics, and the *desktop* path
> is verified against a real artifact (`dice-roller`'s Windows `dist/` contains
> `app/main.pyc` and no `.py`) — but no mobile build has produced a stripped
> payload even once.
>
> Verified 2026-07-31, and nothing has rebuilt it since: the staged Android
> bundle still contains `_python_bundle/app/main.py`.
>
> Installing the final 3.14 unblocks two things:
>
> - **Validating the feature.** Build `android-safe-area` with
>   `byte_compile = true`, confirm the bundle is `.pyc`-only, and confirm it
>   still boots on the Pixel. Sourceless imports (PEP 3147 legacy layout) are
>   exactly the kind of thing that works in a unit test and fails on a device.
> - **Testing this check properly.** With only an alpha present the doctor
>   check can only be seen degrading; a final 3.14 lets its PASS path be
>   exercised too, so the check is confirmed rather than merely run.
>
> **iOS stays unvalidated regardless** — it needs a macOS host, which no amount
> of Windows Python fixes.

**The gap.** A `byte_compile` setup that cannot find a matching CPython minor
only surfaces when `kivyforge package` actually runs — `kivyforge doctor` says
nothing. With the default `"release"` tri-state the build then degrades
quietly to shipping source, which is exactly the outcome someone who
configured stripping does not want to discover after the fact.

**Work.** Add a per-platform doctor check reusing the existing
`select_compiler()` from `kivyforge/bundle/pycompile.py`, so the check and the
build cannot disagree:

- `byte_compile = true` (explicit) + no matching interpreter → **ERROR**; the
  build will hard-fail.
- `byte_compile = "release"` (default) + no matching interpreter → **WARNING**;
  the build will silently ship source.
- Otherwise → pass.

Covers Windows, Linux, macOS, iOS (`[tool.kivy.ios.python.build_settings]`)
and Android. Note iOS/cross-arch cases never have a staged interpreter to fall
back on, so the check must pass `native=False` there exactly as the build does.

**A pre-release of the right minor is not enough — reuse
`select_compiler()`, do not reimplement the version test.** CPython bumps the
`.pyc` magic number through the alpha/beta cycle and only freezes it at the
first release candidate, so 3.14.0a7 (magic 3621) writes bytecode that shipped
3.14.6 (magic 3627) refuses to import, while still answering "3.14" to a
version check. `select_compiler()` and Android's `_reports_version()` now both
require `releaselevel == "final"`; a doctor check that only compared minors
would pass exactly where the build fails, which is worse than no check.

Found the hard way on 2026-07-31: an Android build picked up a 3.14.0a7 and
died on two 3.14 stdlib modules using t-string syntax the alpha cannot parse.
That was luck — without the SyntaxError it would have shipped a bundle whose
stdlib bytecode the device rejects, sources already stripped, with no clue as
to why. See the `TestPreReleaseInterpretersRejected` tests.

**A live test case is already on the dev machine.** Its only CPython 3.14 is
that 3.14.0a7, so any Android/iOS project pinning 3.14.x hits the degrade path
today — the check should fire there immediately, which makes it easy to
confirm the check works rather than merely runs.

**Message shape.** Follow the form the six backends now share: a short
headline, then the *why* (pre-releases do not count, and the reason), then an
explicit `Fix:` line naming both ways out. The degrade path is the one that
matters most — it is silent, and until 2026-07-31 it offered no remedy at all.

**Done when** an `android-safe-area` release build produces a `.pyc`-only
bundle that boots on the Pixel 8a, **and** `kivyforge doctor` reports the
misconfiguration on every platform that has the setting. iOS gets the same
treatment when a macOS host is available; it does not block this item.
**— done 2026-09-13.** Both deliverables landed; iOS is covered by the check but
its artifact remains unvalidated. That was attributed to needing a macOS host;
the host arrived 2026-09-14 and the real blocker turned out to be upstream — see
the note at the end of this item.

### What the work turned up — 2026-09-12/13

**CPython 3.14.7 (64-bit) installed, and `strip_source` has now actually run on
Android for the first time.** The build reported `byte-compiling the Python
payload with py -3.14 (.pyc only)`, and the staged bundle is what it should be:
**0 `.py`, 1036 `.pyc`, no `__pycache__`**, with `app/main.pyc` in the legacy
sourceless layout. Header magic is **3627** (a 3.14 final; the alpha's was 3621)
and flags `1` = hash-based/unchecked per PEP 552. **This overturns the
2026-07-31 finding** that the bundle still contained `_python_bundle/app/main.py`.

**It boots and runs on the Pixel 8a — validated 2026-09-13.** Kivy reports
`Installed at ".../site-packages/kivy/__init__.pyc"`, the GL stack comes up
(Mali-G715, OpenGL ES 3.2), and Kivy reaches `Start application main loop` and
renders. The *installed, unpacked* payload on the device is `.pyc`-only —
**0 `.py`, 1036 `.pyc`, 0 `__pycache__`**, `app/main.pyc` — so the check is
against what the device actually imports, not just the staged tree. No
`ImportError` or bad-magic anywhere: bytecode written by 3.14.7 loads under
3.14.6, confirming the magic-is-keyed-to-minor assumption on real hardware.
The app's own output cross-checks too: it reports a 121 px top inset, matching
the `displayCutoutSafeInsets=Rect(0, 121 - 0, 0)` the window manager reports.

**A trap for the next person doing device validation.** Two runs appeared to
hang after `[INFO] [Window] Provider: sdl3` with no error. That is not a
byte-compile failure and not an app bug — it is SDL waiting for a surface that
never arrives because the screen is locked or the notification shade has input
focus (`mCurrentFocus=NotificationShade` / `AlternateBouncerView` in
`dumpsys window`). `deviceLocked=0` from `dumpsys trust` is **not** sufficient;
check `mCurrentFocus` is the app's activity. `adb shell svc power stayon true`
avoids the doze/relock cycle mid-test. Worth encoding as a precondition in the
manual checklist item 2 produces, because the symptom looks exactly like a
sourceless-import failure.

**The premise of this item was wrong: there were two resolvers, and they
disagreed.** Android never used `select_compiler()` — it had its own
`_byte_compile_interpreter()` that *searches* (PEP 397 launcher, then
`python3.X`), while `select_compiler()` only ever considered the staged
interpreter or kivyforge's own process. Measured on this host, same target:

| | result |
|---|---|
| `select_compiler(native=False, "3.14.6")` | `None` — degrade, ship source |
| Android's search | `('py', '-3.14')` — byte-compile |

So a check built on `select_compiler()` as planned would have reported a
problem for Android where none existed. Worse, the disagreement was a **live
bug**: iOS and every cross-arch desktop build silently shipped source on this
machine despite a usable 3.14.7 being installed. What settled the design is
that all six backends *already* tell the user "install a final CPython — 
kivyforge finds it automatically", which was only true on Android.

**Fixed by unifying, not by special-casing the check.** The search moved into
`bundle/pycompile.py` as `find_interpreter()`; `select_compiler()` now falls
back to it, and Android calls it directly. `target_minor()` is shared too
(it was duplicated). Both resolvers now return `('py', '-3.14')` for the case
above, so the doctor check reuses the one function the build uses and cannot
drift from it. Interpreter-search tests moved to `tests/bundle/test_pycompile.py`
with the code, and `select_compiler()` — which had **no tests at all**, despite
five other test modules pointing at them — now has them.

**Check shape as built.** `check_byte_compile()` in `doctor/checks_common.py`,
wired into all five backends, reached through a new `Probe.byte_compile_interpreter()`
so it stays hermetic. Severity is as specified (`true` → FAIL, `"release"` →
WARN, `false` → SKIP), plus one case the plan did not anticipate: when the build
is **native** the staged runtime compiles its own payload and nothing on the
host matters, so that PASSes without probing. `builds_natively()` is deliberately
conservative — it requires *every* configured arch to match the host, because
claiming "native" on the strength of one matching arch would hide exactly the
cross-build case worth reporting. Verified live on Android: PASS naming
`py -3.14`, WARN and FAIL by pinning a 3.15 that does not exist, and FAIL exits
non-zero.

**Two things to carry forward.**

- **`kivyforge run` can never exercise this path.** `android_run()` hardcodes
  `debug=True`, so the `"release"` tri-state always resolves false in the dev
  loop; validating on-device required setting `byte_compile = true` explicitly.
  That is a structural reason the gap survived, and an argument for a
  `run --release` or an equivalent escape hatch. Not fixed here.
- **The convenient live degrade case is gone.** This file noted that the dev
  machine's alpha made the WARN path fire on any 3.14 project; installing 3.14.7
  removed that. The WARN/FAIL paths now need a deliberately unavailable version
  (3.15.0 was used), which is a better test anyway but no longer free.

**iOS `strip_source` remains unvalidated, and the blocker is not the one this
paragraph used to name.** It said "it needs a macOS host". A macOS host arrived
on 2026-09-14 and the attempt still could not run: `package -p ios` degraded to
shipping source with *"no final CPython 3.15 found (this project ships
3.15.0b4)"*, and **every iOS example in the repo pins `3.15.0b4`** — all seven
were checked. Byte-compilation needs a *final* interpreter, so iOS
`strip_source` is not merely unexercised but **currently unexercisable here**
until CPython 3.15 ships (~Oct 2026) or an example is deliberately pinned to an
already-final minor. See
[`macos-ios-validation-findings.md`](macos-ios-validation-findings.md) §4.

The one thing that mattered most in that attempt did pass: `<app>-ios/app` was
materialised as a **real directory copy, not a symlink**, and the working tree
was untouched — so the data-loss hazard
[`ios-source-stripping.md`](ios-source-stripping.md) was written to prevent does
not occur.

Note the remaining gap is narrower than "iOS is unvalidated". The simulator path
is proven, and as of 2026-09-14 so is the **device** path: `build`/`run -p ios
--device` and a signed `.ipa` export, on a physical iPhone, which found and
fixed a real bug no simulator run could reach (`--team-id` /
`KIVYFORGE_TEAM_ID` never reached the generated Xcode project, so it satisfied
the pre-flight check while having no effect on the build). What is still missing
for iOS is `strip_source` and any T3 on the built `.app`.

---

### 2. Test matrix + test plan

**Status: done 2026-09-13.** Delivered as
[`test-matrix.md`](test-matrix.md) — host × target capability, the six tiers,
per-cell coverage naming the CI job that produces it, the host-dependency list,
a prioritized gap list, the manual checklist, and a dated results log. The
tables that used to live here moved there rather than being copied, because two
copies drifting is the failure this item exists to prevent.

**Also landed:** the `integration`, `requires_toolchain`, and `requires_device`
markers, so selecting the hermetic suite is now `pytest -m "not integration"`
rather than a question about which job invokes which paths.

**Corrected 2026-09-13 after review:** an earlier version of this paragraph
claimed the markers answer "which tier does CI run", with an exact test count.
Both were wrong. No CI job filters on a marker — `unit_tests`, `windows_tests`,
and `macos_integration` all run unfiltered `pytest`, and T2/T3 are *jobs* that
build and then point pytest at the artifact path. The markers separate hermetic
from opt-in, nothing more. The counts are gone for good; see
[`test-matrix.md`](test-matrix.md) rule 3 on why a number in a document is the
same failure as an unlogged test. `requires_device` also marks no test yet.

**What the inventory found — four things that change later items:**

1. **Only Android has real toolchain coverage.** `android_gradle` drives AGP,
   the pinned NDK, CMake, and `javac` for real. Linux, macOS, and iOS have
   *none*: no CI job runs `kivyforge build` for any desktop target, and
   `appimagetool`, `codesign`, `lipo`, `hdiutil`, `xcodebuild`, and `simctl`
   have never executed outside a mock. `macos_integration` runs `pytest -q` and
   nothing more — its whole marginal value over `unit_tests` is two Mach-O
   launcher tests.
2. **A silent-skip hole of exactly item 1's shape, found and closed.** Those two
   macOS tests were gated by one `skipif` covering both "wrong host" and "no
   clang". On the macOS runner — the only place they can run — a missing clang
   would have skipped them and left the job green. Split into a platform gate
   (skip, correctly) and a toolchain gate that fails under
   `KIVYFORGE_REQUIRE_TOOLCHAIN`, now set on the three jobs that exist for their
   toolchain. Same reasoning as the existing `KIVYFORGE_REQUIRE_SYMLINKS`.
3. **T3 artifact assertions are the cheapest real win, and barely exist.** As
   found, `android_gradle`'s were three `unzip -l | grep` presence checks:
   nothing asserted `.pyc`-only under `strip_source`, nothing checked a `.pyc`
   magic number against the shipped runtime, nothing asserted ELF/Mach-O arch —
   even though `android/elf.py`, `linux/elftools.py`, and `macos/machotools.py`
   already parse all of it. **A T3 pass would have caught item 1 on day one**,
   which is the argument for item 5 leading with T3 rather than with a device.
   *Since closed for Android, later the same day; see item 5. Linux and macOS
   remain open, though only their pytest drivers are blocked — the check
   functions are not.*
4. **Item 5 has a lock question to settle first — but most of it is already
   settled elsewhere.** No `examples/desktop/*` project commits a lock: all four
   gitignore `pylock.*.toml`, and the only committed locks in the repo are
   `hello-android` and `hello-sdl3` (Android) plus `hello-kivy` (iOS).
   **Corrected 2026-09-13 after review:** this said the desktop examples commit
   `pylock.windows.toml`. They do not, which means a *Windows* build job is
   blocked on the same question — "Linux is the cheapest first target" was
   resting on a Windows lock that was never there.
   **Corrected again the same day:** it also framed this as an open choice
   between committed locks and lock-at-CI-time, when
   [`common/03-lockfile-concept.md`](../common/03-lockfile-concept.md)
   §"Example-repo lock policy" already decides it. Example locks are gitignored
   deliberately (whole-`pyproject.toml` hashing churns them; reference-only locks
   go stale silently), with one exemption for **on-device gate examples**, whose
   locks are evidence tied to a validated run. So the real options are a Linux
   *gate* example or lock-at-CI-time — not flipping the four demo apps, which
   would contravene stated policy. Lock-at-CI-time looks better for desktop,
   since PyPI wheels are immutable and a committed desktop lock therefore buys
   little evidence for the churn it costs; a committed Linux lock earns its place
   once item 4 supplies a real Pi gate. `ubuntu-latest` is still the cheapest CI
   job; a Windows build is the cheapest thing this dev box can prove without
   another OS.

**One correction to the plan this item started from:** the draft capability
table, written from memory rather than from the code, counted five platforms.
There are **seven target cells** — Android and iOS each carry two arches, and
they are genuinely different builds. It also implied win-arm64 was reachable:
the host gate is arch-agnostic by design, but `VALID_WINDOWS_ARCHS` is
`{amd64}`, so config rejects it today. Same for Linux `aarch64`, which is item 4.

---

### 3. Output layer: `rich` rendering and `--json`

**Status: the seam, `doctor`, `status` and `lock --json` landed 2026-09-14/15.**
`kivyforge/report/` now exists with the four pieces this item needs —
`console.py` (the `Report` seam and the stdout/stderr rule), `envelope.py` (the
versioned envelope), `diagnostics.py` (`Diagnostic` plus the code vocabulary),
and `exit_codes.py` (the reserved taxonomy). `rich` is a hard dependency. The
seam is the part that had to be built once; each remaining verb is now
independent work.

Against the agent-friendliness list below: **points 1, 2 and 5 (versioned
envelope, artifact paths, remediation as a field) are done**; **points 3 and 4**
(diagnostic IDs, exit-code taxonomy) have their mechanism and vocabulary built,
and `lock` is the first verb where the *narrowing* actually happened — see below;
**points 6–8** (`capabilities`, `--no-input`, `AGENTS.md`) are untouched. `build`
and `package` have not been converted.

**`lock` is where the taxonomy stopped being theoretical (2026-09-15).** Its
three `--check` failures now exit `LOCK_DRIFT` (`4`) rather than `1` and differ
only in code — `KF-LOCK-DRIFT`, `KF-LOCK-MISSING`, `KF-LOCK-UNREADABLE` — which
is the split the two audiences want: a CI job that only needs "re-lock and retry"
branches on the number, and anything that cares whether the lock is *corrupt*
rather than merely stale reads the code. `lock` on a host that cannot resolve
(iOS off macOS) exits `ENVIRONMENT_ERROR` with `KF-HOST-INCAPABLE`. Nothing
depended on the old `1`, because the existing tests asserted `!= 0` — which is
the argument for narrowing early, while that is still true.

Resolver warnings became diagnostics rather than stderr-only prose
(`KF-LOCK-WARNING`, always `WARNING`, run stays `ok`). The macOS and Linux
backends emit these for real judgement calls — accepting a vendored plain
`linux_*` wheel, say — and a machine previously could not see that had happened.

**`Report.record()` came out of this and is the generally useful piece.** A verb
that raises never reaches its own `emit`, so `reporting()`'s failure envelope had
nothing to put in `data` and emitted `"data": {}` — meaning the single run a CI
job most wants to read machine-side said *that* drift happened but not *what*
drifted, while the human on stderr got the diff. Fields recorded as they become
known now survive into the failure envelope, and `emit`'s own `data` merges over
them. `build` and `package` want this more than `lock` does: a build that fails
half way has usually still produced artifacts worth naming.

**The failure path is now covered too — `reporting()` in `cli/_output.py`.** A
verb that raised `ToolchainError` used to emit **no envelope at all**, so
`--json` gave empty stdout on exactly the run an agent most needs to read, and a
consumer could not tell that from a crash or from a verb that legitimately said
nothing. The failure is now reported in both registers rather than moved between
them: the envelope goes to stdout, and the exception is re-raised untouched so
click still prints `Error: ...` to stderr and still chooses the exit code.
`ToolchainError` grew `code`, `remediation` and a per-raise `exit_code`, all
optional, so an untriaged raise site keeps its old behaviour and is merely
*unspecific* rather than wrong. It also honours the `Fix:` line convention from
item 1, which gives every existing raise site a populated
`diagnostics[].remediation` without editing any of them — parsing prose once, at
the producer, is how a convention becomes a field instead of staying prose for
every consumer.

**Correction to the exit-code taxonomy, from measuring instead of assuming.**
The numbering drafted below gave `2` to "environment missing". But `2` is
`click.UsageError.exit_code` — the convention `argparse` follows too — so
`kivyforge doctor --bogus-flag` already exited `2` before any of this existed.
Keeping `2` would have made "you typed the command wrong" indistinguishable from
"this machine lacks a toolchain", which is the exact confusion the taxonomy
exists to remove. So `2` is ceded to click and never assigned by us, and the rest
shift up: **1** config/user, **2** usage (click's), **3** environment, **4** lock
drift, **5** build failure. `1` keeps its historical meaning, so the narrowing
stays additive. `tests/report/test_exit_codes.py` pins the literal integers,
which looks tautological and is the point — every other test refers to them by
name, so a renumber would otherwise pass the whole suite while breaking any
caller that had learned a number.

Four things worth knowing before the next verb goes through it:

- **Rich markup is off, and it had to be.** Rich's default `markup=True` parses
  `[PASS]` as a style tag and raises `MissingStyle`, because `PASS` is not a
  style — so simply routing doctor's existing lines through a Rich console
  crashes it. Styling is applied via explicit `style=` arguments instead. This
  also means content cannot influence rendering, which matters beyond doctor: a
  dependency named `foo[bar]` is ordinary PEP 508 and appears in resolver
  errors.
- **`--no-color` needs `force_terminal=False`, not just `no_color=True`.**
  Rich's `no_color` strips colour but keeps other SGR attributes, so a `bold
  red` style still emits `\x1b[1m` on a terminal. Since the reason to pass
  `--no-color` is normally a log file or CI transcript, where a stray bold code
  is as unwelcome as a colour, terminal detection is disabled too. Slightly
  broader than no-color.org's wording, and the broader reading is what callers
  want. Losing Rich's width detection costs nothing while `soft_wrap` is on.
- **The JSON path serialises with `ensure_ascii=True`.** That escapes every
  non-ASCII character, so machine output cannot raise `UnicodeEncodeError` on
  any stream encoding — including the redirected cp1252 stdout this item's
  third bullet below is about. `--json > out.json` therefore does not depend on
  the message-content guard holding forever, which is the right trade for the
  one output path that must never crash.
- **The stdout/stderr rule needed one refinement.** "Machine output to stdout,
  human to stderr" is right for *progress*, but doctor's report is the product,
  not progress, and `kivyforge doctor > report.txt` has always worked. So: the
  product goes to stdout (the envelope under `--json`, the report otherwise),
  progress and log lines go to stderr *always* including under `--json`, and the
  human report is suppressed under `--json` because the envelope supersedes it.

One behaviour change to note: **a doctor `FAIL` now exits `2`**
(`ENVIRONMENT_ERROR`) rather than `1`, since it means the machine or project is
not ready — a different reaction from "you passed a bad flag". Nothing in the
suite depended on the old value.

**New 2026-09-12. These are deliberately one item.** User output today is ~119
`click.echo` calls plus `CheckResult.render()`, with no central console —
counted across `platforms/*/cli.py` (Android 37, iOS 20, macOS 10, Linux 9,
Windows 7) and the shared verbs. Colour and JSON both need to intercept every
one of those sites. Introduce the seam once, then hang two renderers off it,
rather than editing 119 call sites twice.

**Shape.** A `kivyforge/report/` module: backends and verbs emit *events* and
structured results instead of formatted strings; a human renderer (`rich`) and
a JSON renderer consume them. `ToolchainError` grows structured fields.

**The stdout/stderr rule is the load-bearing decision.** Machine output goes to
**stdout**; human progress and log lines go to **stderr**. That makes
`kf build -p android --json > build.json` work while the user still watches
progress, and it means `--json` never has to suppress progress to stay
parseable. Everything else in this item is easier once that is fixed.

**`rich` has one real conflict to respect, and it is narrower than it looked.**
Commit 219a8148 pinned user-facing strings to a cp1252-safe set because a
redirected Windows stream falls back to the locale encoding and any character
outside it raises `UnicodeEncodeError` from inside the print. **Measured against
a real cp1252 stream, 2026-09-14** (rather than assumed), `rich` splits cleanly
into what it handles and what stays ours:

- **Its own boxes and rules are automatic — do *not* hardcode ASCII styles.**
  `Console.options.ascii_only` is derived from `file.encoding`, so a `Table`
  renders `+-----+` on a cp1252 stream and `┌─────┐` on a UTF-8 one, with
  `legacy_windows` and `safe_box` identical in both cases. Forcing ASCII box
  styles would only make UTF-8 terminals worse. An earlier version of this
  paragraph said to do exactly that.
- **Our message strings are still entirely our problem.** `rich` does not
  transliterate content: `→`, `├──`, `≥` and `✓` each raise from
  `console.print` exactly as from `click.echo`. Its only contribution is
  appending *"You may need to add PYTHONIOENCODING=utf-8 to your environment"*
  to the exception before re-raising, and a friendlier crash is still a crashed
  build. So the cp1252-safe set stays, and `tests/test_message_encoding.py`
  keeps its full value. House typography (`—`, `§`, `…`) encodes fine and stays
  allowed.
- **Spinners are the actual hazard, not emoji.** `Spinner("dots")` is braille
  (`\u280b`) and is *not* covered by the box substitution, so it raises. Any
  spinner needs an explicitly ASCII frame set or a gate on
  `console.options.ascii_only` — and a spinner is what someone will reach for on
  a long Gradle step, whereas nobody is about to type an emoji into a build
  message.

**The guard already survives this item — handled 2026-09-14 in c5efff82.** It
used to match `echo`/`secho` calls and Click help text by AST, which would have
kept passing while matching nothing the moment output moved to a renderer with
different call-site names. It now checks **every string literal** in `kivyforge/`
except docstrings (Click command and group docstrings still count, being
`--help` text). So item 3 can rename every print in the codebase without
quietly retiring the check, and there is nothing to remember to update.

Also honour `NO_COLOR` / `FORCE_COLOR`, drop colour when stdout is not a TTY,
and add `--no-color`. `rich` becomes a hard dependency — acceptable, it is pure
Python with no transitive weight.

**Order within the item.** `doctor` first: `CheckResult` is already a frozen
dataclass with `name`/`status`/`detail`/`hint`, so it is a near-free
`--json` and it is the single most useful one to an agent, which needs to know
whether a build is even possible before attempting it. `status` next, which
needs actual refactoring — `linux_status()` and its peers `click.echo` computed
strings like `"out of date (run `kivyforge lock -p linux`)"`, so the state has
to be returned rather than printed. Then `lock`, `build`, `package`.

**`lock` needed no refactoring, which is worth knowing before `build`.** Its
outcomes were already computed as data and only *described* by `click.echo`, so
the conversion was mechanical and the whole cost was deciding the payload
vocabulary (`action` ∈ wrote/unchanged/checked, `in_sync`, `packages`,
`lockfile`) and the codes. `build` and `package` were not this easy: their output
is genuinely progress — subprocess pass-through from Gradle, Xcode and
`appimagetool` — so the interesting question there is not how to render it but
which of it is *product* versus noise to forward to stderr unchanged. That is
worked out in
[`build-package-output-proposal.md`](build-package-output-proposal.md), scope
agreed 2026-09-16.

**The `build`/`package` payload ended up far smaller than it started, and that is
the reusable lesson.** It began at eleven fields, each justified by a sentence of
the form "CI wants X". Held to a stricter test — name the thing in a pipeline or
agent loop that reads this field and behaves differently — only
`artifacts[].path` and `artifacts[].kind` survived. Size and hash were cut once it
turned out the pipelines that look like they want a digest either take a path
instead, key off *inputs* rather than outputs, or compute the digest themselves.
`signing.tier` was cut for having a clear role and no consumer: nothing here
publishes built apps. The sharpest of the cuts generalises past this item —
**a field whose only plausible consumer is a check verifying the same build that
emitted it does not belong in the envelope**, because feeding a T3 assertion the
build's own claim about `strip_source` would weaken the assertion rather than
automate it. The working rule now: *the envelope states as data what kivyforge's
own human-mode lines already state as prose, and only where a consumer can act on
the difference.* The qualifier matters — the toolchain's own human-readable output
(Gradle, `xcodebuild`) is explicitly not a candidate pool for payload fields; it is
progress, forwarded verbatim and never parsed. Fields are additive later; one
emitted before anything reads it is a guess that has to be honoured forever.

**Third-party output changes only where `--json` forces it, and then by file
descriptor rather than pumped through us.**
The natural-looking design is a line pump, re-emitting each Gradle line through
`report.progress`. Measurement killed it: a child writing raw UTF-8 bytes, read
through a text-mode pump and re-written to a cp1252 console, arrives mangled,
and the build log is the entire artifact of a failure. Handing a tool our stderr
descriptor delivers its bytes as sent, cannot deadlock, and — once the payload
decision above established that no tool output becomes a field — there was never
a reason to read the lines at all.

**Two scoping rules shrank that from three toolchains to one.** *On success,
preserve existing platform behaviour unless stdout contamination has to be fixed
for `--json`; on failure, preserve all available diagnostic output.* Only Gradle
contaminates stdout — it inherits ours and would write thousands of lines into the
middle of the JSON document — so only Android's invocation changes. iOS stays
buffered even though a multi-minute `xcodebuild archive` prints nothing, because
nobody here has hit the no-output timeout that would make it a problem; that is the
same call the artifact hash got. Linux keeps discarding `appimagetool`'s output but
gains a fix under the second rule: it raises with `proc.stderr or proc.stdout`, so
whenever stderr has content the stdout half of the evidence is lost — the exact
trap `ios/xcode/runner.py` carries a comment about.

**Reading the code closely found the hole that mattered: artifacts had no way home
on the failure path.** `Report` lives in `cli/_output.py`, the work that produces
artifacts is three frames down in `platforms/*/cli.py`, and a verb that raises never
reaches its own `emit`. So a `BuildOutcome` returned only on success would leave an
Android package that failed *after* writing `app-release.apk` emitting `"data": {}` —
reintroducing, for the verbs that need it most, exactly the hole `Report.record()`
was added to close.

**Making artifacts an event closed that hole and three others.** Product lines are
interleaved with progress and their order carries meaning — iOS prints `Generated
<slug>-ios` minutes before `Exported <ipa>`, macOS prints `Built`, then two signing
lines, then `Packaged` — so rendering product only from a returned value would
reorder real build logs to tidy a seam. Reporting each artifact at the moment of
finalisation instead preserves ordering, enforces the finalised-and-verified rule by
construction, puts artifacts on `Report` before any later failure, and therefore
needs no new `data=` argument on `ToolchainError` at all. The lesson worth keeping:
**when a value has to be both ordered and durable, an event beats a return value,
and the return value becomes a summary rather than a channel.**

**Printing and recording then had to be split into two events, and the reason is
the most interesting finding of the review.** A single `on_product(artifact)` cannot
work, because three package flows call a build function that legitimately *prints*
in a situation where nothing should be *recorded*: `macos_package` calls
`macos_build`, whose `Built <app>` line fires while the bundle is still unsigned;
`ios_package` calls `prepare_build`, whose `Generated` line names an intermediate;
`android_package` calls `android_build` for the same reason. Splitting into
`on_line(message)` and `on_artifact(artifact)` also disposes of the nesting problem
without a flag — a caller passes `on_artifact` down only when the inner function's
products are the verb's products — so **the build-versus-package artifact asymmetry
becomes one argument at three call sites instead of a condition threaded through the
backends.** Generalises to: when two registers disagree about the same moment, the
disagreement belongs in the wiring, not in a conditional.

**There is a more dangerous version of the same question: an artifact path on a
failed run can name a file the run did not produce.** None of the three
packaging backends leave a clean slate on failure, and two do so *deliberately* —
Linux builds to a tempfile and swaps on success so a failure "leaves any previous
.AppImage intact", and Windows reserves the prior package and calls
`restore_previous` when signing fails, which is a rollback feature. Android simply
writes to fixed paths that nothing clears. So the obvious reading of "report what
you produced" would hand an agent a stale artifact indistinguishable from a fresh
one, and it would ship it. The rule that survives: **`artifacts` lists only products
this invocation finalised and verified**, which makes `[]` the correct answer for
most failures. `_require_artifact` was already doing this on the success path and is
the model to extend.

**The channel for progress and diagnostics is the `lock` pattern, not a new one.**
Withholding `Report` from the platforms while also requiring `[stage]` lines to
become `report.progress` and success-path INFO/WARNING diagnostics to reach the
envelope is a contradiction, and `lock` had already resolved it: it passes
`on_warning=lambda msg: _warn(report, msg)` and `_warn`, on the CLI side, does both
`report.progress` and `report.diagnose`. The backend calls a plain callable and
knows nothing about reports, codes or severities. Generalised, that is
`on_progress(message)` plus `on_note(code, message)` — and because a diagnostic
raised that way is accumulated on `Report` immediately, success-path warnings
survive into a failure envelope with no extra plumbing.

**Failure paths were quietly putting third-party output on stdout.** The tools we
capture embed their output in the exception message, backends wrap that with
`ToolchainError(str(exc))`, and `as_diagnostic()` copies the message into
`diagnostics[].message` — so a failing `xcodebuild` could put megabytes of build
transcript inside the JSON document, contradicting "all third-party output is
stderr" on the one path that matters most. The split: the diagnostic message is a
summary worth branching on, and the captured log goes to `report.progress` before
the raise.

Three narrower findings worth carrying because they outlive this item. **Android
prints absolute paths where the other four backends print relative ones**
(`android/cli.py:449,532` versus `{path.relative_to(project_root)}` everywhere
else), so "publish the paths" cannot mean "publish what we print" until that is
normalised. **`byte_compile` needs one code with two severities**, since `= true` is
an explicit demand that must keep failing while the default `= "release"` degrades
with a warning — the code carries the meaning, the severity carries the consequence.
And **"no gate checks it" is not the same as "we never learn it"** — a distinction
worth remembering, because getting it wrong nearly cost a usable exit code. No
up-front gate answers "is the toolchain installed": `check_host_capability` compares
`platform.system()` and nothing more on every backend, Android's is a deliberate
no-op, and `_require_macos_host` never checks that Xcode exists. But an absent tool
announces itself when we try to spawn it, and `macos/machotools.py` and
`macos/launcher.py` already catch `FileNotFoundError` and say "required macOS tool
not found" in prose. Those are toolchain-missing determinations needing only a code,
so `KF-TOOLCHAIN-MISSING` at exit `3` is reachable there. What stays out of reach is
the Gradle-mediated case: a missing JDK or NDK is discovered *by Gradle*, arrives as
a build failure, and no exit status can recover the distinction afterwards. Closing
that needs an Android preflight, which doctor already knows how to answer and which
would pay for itself by failing a bad runner in seconds instead of after a Gradle
download.

**Two gaps found by the review are worse than any misclassification: neither primary
build tool produces an envelope when it cannot be spawned.** `run_command`
(`ios/xcode/runner.py`) and `run_gradle` (`android/gradlew.py:30`) are the single
funnels for every Xcode and Gradle invocation and catch neither `FileNotFoundError`
nor `OSError`, while `reporting()` only catches `ToolchainError` — so the result is a
traceback on a stream a JSON consumer is not parsing. Not a wrong answer, an
unparseable one. Worth generalising into a rule for the `--json` work: **every
uncaught exception type is a hole in the envelope contract**, so the audit is of what
can escape a verb, not only of what each verb reports.

**The accumulator has to live in the backend, and the reason is a useful test for
where state belongs.** An earlier draft put it verb-side, which cannot work:
`Platform.build`/`package` *return* `BuildOutcome`, so a backend given only a
notify-callback would keep its own private list anyway — two collections updated by
hand at every product site. The no-op recorder used when a package flow calls a build
function is the proof, since the inner call must still return a populated outcome with
nobody listening. So a small `OutcomeBuilder(on_artifact)` with `add()` and
`finish(notes)` sits in the backend: `add()` stores *and* notifies, making it
impossible to update one and forget the other. **Whoever owns the return value owns
the accumulator.**

**`on_note` must never print, which turned a per-code rendering policy into no policy
at all.** Every success-path note already has human text, and two of the four are not
lines of their own: the signing warning is embedded in `Packaged … (onedir folder,
unsigned …)`, and the byte-compile degradation is already its own `[stage]` line. A
generic echoing adapter would therefore duplicate prose in one case and add lines in
another. Making the callback machine-only means the human text for a note stays
wherever the backend already puts it, and there is nothing per-code left to specify.
The review also found a fourth note we emit and drop entirely — iOS's `Warning:
entitlements not granted by the pinned provisioning profile` under `auto_signing`,
which succeeds and has no code — so `KF-ENTITLEMENTS-UNGRANTED` joins the set. And
`build`/`package` should reuse all three of `lock`'s lock codes rather than only
drift: the same missing or unparseable lockfile is branchable under `lock --check
--json` today and opaque under `build --json`, which is how consumers learn to stop
trusting codes.

**The stream migration is much wider than it first looked, and pretending otherwise
was the last real inconsistency in the spec.** "Progress goes to stderr" plus "only
Gradle and Android's brackets change streams" cannot both hold: counting the
`build`/`package` paths, roughly 25 lines are on stdout today that the rule moves —
macOS's `Developer ID signing with …` and `signed N Mach-O binaries`, iOS's
`Collecting artifacts` and three `xcodebuild …` lines, Linux's `Packaging … with
appimagetool`, the byte-compile note on all four desktop backends, and ~16 bracketed
Android lines. Narrowing the rule to Android was rejected: it would make the stream a
per-backend accident, and the entire value of the rule is that a consumer can rely on
stdout being product everywhere. The release note is therefore one sentence — **for
`build` and `package`, everything except the product lines moves to stderr** — and
"byte-identical human output" is redefined as *merged* text and order being unchanged,
since a per-stream baseline cannot survive a deliberate migration.

**One backend would have ended up with an empty stdout and a non-empty envelope.**
Plain `build -p android` announces its only product as `[generate]
dice-roller-android/ regenerated` — progress by the rule — so after the migration the
command would print nothing while the envelope claimed a `project` artifact. It gains
a `Generated <project>` line matching iOS's wording. A good reminder that a
stream-classification rule needs a pass over what is *left* on the other stream, not
only over what moves.

**Two decisions taken rather than offered.** Android's failure classification goes to
typed subclasses of `AndroidBuildError` (`GradleFailed`, `ArtifactMissing`,
`LockDrift`, `ToolchainMissing`, `ContractViolation`) rather than optional fields on
the base: the raise sites already group that way, the funnel becomes a dispatch table
instead of a convention, and a missed site degrades to today's behaviour instead of
raising on an unexpected keyword. And spawn failures split by errno — catch `OSError`
so the envelope always survives, but map only `FileNotFoundError` to
`KF-TOOLCHAIN-MISSING` and everything else to a new `KF-TOOLCHAIN-UNUSABLE` with
`errno` in context. `EACCES` on a wrapper means "fix the file mode", not "install the
tool", and one code cannot say both.

**Two scoping corrections worth carrying.** The stderr-only rule for tool output
applies to *bulk* producers, not to every subprocess: `(proc.stderr or proc.stdout)`
embedded in an error message is a house convention with sixteen sites — `signtool`,
`codesign`, `clang`, `rcedit`, `keytool`, `notarytool`, `adb`, the pip and Swift
resolvers — and for those the quoted line *is* the diagnosis. The rule is about
volume: a diagnostic message may quote a tool, it may not contain a build log.
Separately, `status --json` does **not** emit project-relative paths today, contrary
to what is easy to assume: every backend hands `BuildArtifact.probe()` an absolute
path and `as_dict()` only calls `as_posix()`, changing separators without
relativising. The relative-path rule is scoped to `build`/`package`; normalising
`status` is a small independent change.

**Validated on macOS and Linux (2026-09-16/17), one defect between them.** Recorded
in [`build-package-output-mac-findings.md`](build-package-output-mac-findings.md) and
[`build-package-output-linux-findings.md`](build-package-output-linux-findings.md).
The highest-risk change — pinning iOS DerivedData so the simulator `.app` has a
project-relative path — works, with `build`, `run` and `status` all agreeing on where
it lands. Linux found no defects against a real `appimagetool`, and confirmed two
things only a live tool can: `artifacts == []` on failure *while a previous AppImage
sat in `dist/linux`* (§4.1b in the wild rather than in theory), and both of the
tool's streams reaching stderr, which is exactly what the old `stderr or stdout`
idiom dropped.

The defect is a good example of how a rule spreads more slowly than it is written.
Missing `sips`/`iconutil` classified as `KF-ERROR`/exit `1` instead of
`KF-TOOLCHAIN-MISSING`/`3`, because `macos/icns.py` pre-checks `shutil.which` and
raises a bare `AppBundleError`, so it never reaches `spawn_failure()`. The audit that
produced the spawn-failure inventory looked at `subprocess` call sites; this one
guards its spawn with a `which` check instead, and so read as already handled. Fixed
by attempting the spawn and catching `OSError`, like `machotools`/`notarize`/
`launcher`. macOS is the only backend with the gap — Linux and Windows generate icons
with Pillow in-process, so they have no spawn site to misclassify.

**Linux also asked a fair question about `--json`: the distribution advice vanishes
rather than moving to stderr.** Answered in the proposal as intended behaviour, since
notes are product prose — they say what was produced and what to do with it, which is
the register the envelope replaces. Sending them to stderr would make `--json` change
where advice goes rather than whether it applies.

**Pyright is now a CI gate, at zero errors.** Adopted over `ty`, which is still
`0.0.x` and so a poor thing to gate on, and it paid for itself immediately: its first
run found that `spawn_failure()` returned `dict[str, object]`, which cannot be
`**`-unpacked into `ToolchainError`'s typed parameters — 30 of 64 errors from one
day-old helper. The cross-host lesson is worth keeping, and came from the Mac run:
pyright infers `pythonPlatform` from the *host* and narrows the stdlib stubs to
match, so the Windows-only registry probe in `doctor/probe.py` is clean on Windows
and three errors on macOS and Linux. `"pythonPlatform": "All"` makes the answer
host-independent, which a five-target build tool linting on ubuntu and authored on
Windows cannot do without.

**`status` turned out to pay a debt as well as add a feature.** The backends now
return a `StatusReport` (`kivyforge/status.py`) that `cli/status.py` renders.
That closed
[`abstraction-leak-retro.md`](../common/abstraction-leak-retro.md) §1.6a, where
`_humanize`, `_build_state` and `_lock_state` were duplicated once per desktop
backend — quadruplicated by then, since Windows landed after that retro and
copied all three. The duplication had survived four backends precisely because
the helpers returned *display strings*: each copy differed only in a platform
name embedded mid-sentence, and there was no shared type that could hold "which
state" apart from "how to say it". Deduplicating was blocked on wanting the state
as data, which is what `--json` forced. Android also stops being the odd one out
— it alone reported bare lock states with no relock hint, and used absolute
build timestamps where the other four used relative ages.

**Making kivyforge agent-friendly — beyond `--json`.** In rough value order:

1. **A stable envelope, versioned.** Every `--json` response carries
   `{"schema": 1, "kivyforge": "...", "command": ..., "platform": ...,
   "ok": bool, "data": {...}, "diagnostics": [...]}`. Agents branch on shape;
   an unversioned shape is a shape that breaks silently.
2. **Report artifact paths in `data`.** `{"artifacts": [{"path", "kind",
   "sha256"}]}`. Build layout is deterministic (`build/<platform>/…`,
   `dist/…`), but an agent currently has to know that from docs or guess. This
   is cheap and removes a whole class of flailing.
3. **Stable diagnostic IDs.** Failures are prose strings today, and an agent
   cannot branch on prose. Give each a code — `KF-LOCK-DRIFT`,
   `KF-BYTECOMPILE-NO-INTERP`, `KF-HOST-INCAPABLE`. Note
   `native_integration` already does exactly this (`ni.req.N`, `ni.decl.*`,
   `ni.adv.S*`), so adopting the discipline now also pre-pays item 8.
4. **An exit-code taxonomy.** `ToolchainError.exit_code` is `1` for
   everything, so an agent cannot tell "you configured this wrong" from
   "this toolchain is missing" from "the build failed" — and those want
   different reactions. Reserve: 1 config/user error, 2 environment/toolchain
   missing, 3 lock drift, 4 build failure.
5. **Promote the `Fix:` convention to a field.** The backends already share a
   message shape ending in an explicit `Fix:` line (established in item 1).
   Emit it as `diagnostics[].remediation` instead of burying it in prose.
6. **Capability introspection**, e.g. `kivyforge capabilities --json`:
   platforms, valid archs, package formats, and **which hosts can build which
   targets**. That last one is the matrix from item 2, and it is precisely the
   fact that stops an agent trying to build iOS on Windows.
7. **Non-interactive guarantees.** No verb should ever prompt; add `--no-input`
   so that is contractual rather than incidental, and keep progress rendering
   off when not a TTY.
8. **`AGENTS.md`** at the repo root for agents working *on* kivyforge (how to
   run the suite, the coverage gate, the ruff config, the cp1252 rule), plus a
   short "driving kivyforge from an agent" page in item 6's docs.

Optional, worth a look but not committed here: a `--dry-run` plan mode on
`build`/`package` so an agent can validate config without paying for a full
build.

**This item is also test infrastructure.** Item 5's assertions get to compare
JSON documents instead of grepping progress text, which is why item 3 comes
first.

**Done when** every verb accepts `--json`, output is on stdout with progress on
stderr, the envelope is schema-versioned, and a golden-file test pins the
envelope for each verb.

---

### 4. Linux aarch64 — Raspberry Pi as a *target*, not a host

**Groundwork that already exists** — this is more additive than it looks:

- `kivyforge/platforms/linux/elftools.py` already maps `aarch64 → (ELFCLASS64,
  EM_AARCH64)`; validation is pure ELF parsing and is arch-agnostic.
- `appimage.py`'s `_APPIMAGETOOL` / `_TYPE2_RUNTIME` are already per-arch dicts
  keyed by arch — aarch64 is a new entry, not a refactor.
- `manylinux_platform_tags(floor, arch)` in `linux/lock/profile.py` is already
  arch-parameterized.
- `linux-spec.md` already documents aarch64 as "purely additive later".

**Cross-build is nearly free, and the architecture already anticipates it.**
The entire payload is prebuilt artifacts — PBS runtime tarball, manylinux
wheels, a shell `AppRun`, host-side Pillow icon work — none of which require
executing an aarch64 binary. `appimagetool` runs on the *host* arch and takes
`--runtime-file` to embed the *target* runtime. And the byte-compile ladder
built in Phase B already handles a foreign target correctly: it cannot run the
staged aarch64 interpreter, so it falls back to the kivyforge-hosting
interpreter on a matching CPython minor — which is valid, because a `.pyc`'s
magic number is keyed to the minor version only, never to architecture. **No
emulation anywhere**, consistent with the principle established in Phase B.

**Work**

- Config: `VALID_LINUX_ARCHS = {"x86_64", "aarch64"}`, `DEFAULT_LINUX_ARCHS`
  unchanged; drop the "aarch64 is planned" loader hint.
- Lock: widen `VALID_WHEEL_ARCHS` in `linux/lock/profile.py`.
- Runtime: PBS `aarch64-unknown-linux-gnu` triple mapping.
- `appimage.py`: add aarch64 `appimagetool` + type2-runtime entries (URL +
  SHA-256 pins, same shape as the existing x86_64 ones), and pass
  `--runtime-file` so a host-arch appimagetool can emit a target-arch AppImage.
- **Formalize build-for vs build-on.** Introduce one explicit notion of "can
  this host execute a binary of target arch T" and route the existing implicit
  `native=` byte-compile argument through it, rather than leaving each backend
  to open-code `platform.machine().lower() == target_arch`. This is the deferred
  item; aarch64 is what makes it real.
- `doctor`: report whether the current build is native or cross, and warn where
  a cross-build genuinely loses something.
- Docs: rewrite the linux-spec Architectures section.

**Scope narrowed 2026-09-12: the Pi is a target, never a host.** The earlier
plan also required a natively-built AppImage on the Pi. Dropped. kivyforge
never has to run on the Pi, which removes the whole question of whether a Pi is
a viable dev machine (SD-card I/O, 4–8 GB RAM, a toolchain install nobody will
maintain) and leaves exactly one supported path: **cross-build on Linux x86_64,
run on the Pi.** Convenient, because it is also the path the architecture
already anticipates — the payload is prebuilt artifacts throughout, so nothing
needs to execute an aarch64 binary at build time.

Two consequences to write into `linux-spec.md`:

- `check_host_capability()` still requires a Linux host, so **the Windows dev
  box cannot build this target at all** — WSL2 or a Linux box is a hard
  prerequisite, not a convenience. This is the item's real gate.
- Native aarch64 *building* is not unsupported-forever, just untested and
  unclaimed. Say so, rather than implying it works.

**Pi specifics to settle while implementing**

- **Which Pi, which OS.** Baseline is 64-bit Raspberry Pi OS (Debian-based) on
  Pi 4 / Pi 5. Its glibc sets the real floor the manylinux ladder must clear —
  check it against `effective_glibc_floor()` rather than assuming the x86_64
  floor transfers.
- **32-bit ARM is out of scope.** `armv7l` / `armhf` means a third arch, a
  different PBS triple, and a manylinux tier with far worse wheel coverage.
  Not worth it while 64-bit Pi OS is the default image.
- **Wheel availability is the likely surprise**, not the build. Verify at lock
  time that the dependency closure actually has `manylinux_*_aarch64` wheels;
  a plain `linux_aarch64` wheel from `find_links` gets the same mandated
  warning x86_64 already gives.
- **GPU/display is a run-time question, not a packaging one**, but it is where
  a Pi run will actually fail first. Note the expectation (SDL under the KMS/DRM
  or X11/Wayland stack the Pi image ships) so a failure there is not
  misdiagnosed as a build bug.

**Validation.** The cross-build half validates immediately on a Linux x86_64
host with no Pi present, and it is all T3 work from item 2: build an aarch64
AppImage, assert every ELF is `ELFCLASS64` / `EM_AARCH64`, and assert no
host-arch binary leaked into the AppDir. Actually *running* it waits on
hardware.

**Deferred, unchanged:** win-arm64. Also deferred: aarch64 as a build host.

**Done when** an aarch64 AppImage cross-built on Linux x86_64 launches and runs
on a Raspberry Pi 4 or 5 under 64-bit Raspberry Pi OS.

---

### 5. E2E automation against the matrix

**New 2026-09-12.** Item 2 decides *what* to test; this item builds it. Split
out because the doc is a week and the harness is not, and because it depends on
item 3's JSON output to assert against.

**Work, in the order that buys the most per unit of effort**

- **T3 artifact assertions first**, as a reusable pytest helper library rather
  than per-platform copy-paste: payload is `.pyc`-only, ELF/Mach-O/PE arch
  matches the target, no host binary in a cross-build, manifest and
  `Info.plist` contain what config declared, signatures verify. These run
  wherever the artifact was produced and need no device.
- **Drive the CLI through `--json`** rather than parsing progress output. This
  is the difference between a suite that survives a wording change and one
  that does not.
- **Extend CI per matrix cell.** Add a Linux job that builds an aarch64
  AppImage (cross, T2+T3) once item 4 lands. Add an Android emulator job for
  T4 — CI deliberately skips the emulator today, and `run --smoke` already
  exists to be driven. Add an iOS simulator job on the macOS runner when the
  wheels it waits on are published.
- **A small fixture-app set** rather than testing against the full 11 examples:
  one minimal app per target plus one that exercises native binaries, wheels
  with extension modules, icons, and `strip_source`. Full-example builds stay
  a nightly, not a per-push cost.
- **The manual checklist becomes runnable**: a short script that prints the
  exact commands for a manual pass and records the results into the matrix
  doc's log, so a hardware session produces a dated artifact instead of a
  memory.

**Started early, 2026-09-13: the Android T3 slice is done.** Taken out of order,
ahead of item 3, because item 2's inventory showed `android_gradle` was *already*
building a stripped, byte-compiled release APK on every push — `byte_compile` and
`strip_source` both default to `"release"` — and discarding it after three
`unzip -l | grep` presence checks. Item 1's bug was live in a code path CI was
running the whole time and never looking at.

It jumped the queue on three grounds: artifact assertions read files rather than
CLI output, so unlike the rest of this item they carry no rework risk from item
3's `--json`; the build and the ELF helpers both already existed, so it was small;
and it makes item 3 safer to land, since a 119-call-site output refactor is a poor
time to have artifact correctness unverified. Details and the remaining T3 boxes
are in [`test-matrix.md`](test-matrix.md) §5.1.

**Sharpened by item 2's inventory (2026-09-13)** — two changes to the above:

- **A plain Linux `x86_64` build job comes before the aarch64 one, and does not
  wait on item 4.** Linux is the emptiest column in the matrix (unit tests only;
  `appimagetool` has never executed outside a mock) and the cheapest to fill:
  `ubuntu-latest`, no signing identity, no Mac.
- **Settle how the desktop job gets its lock first.** No `examples/desktop/*`
  project commits a lock — all four gitignore `pylock.*.toml` — so any desktop
  build job, **Windows included**, needs an answer. But
  [`common/03-lockfile-concept.md`](../common/03-lockfile-concept.md)
  §"Example-repo lock policy" already supplies most of it: example locks are
  gitignored on purpose, exempting only on-device gate examples whose locks are
  evidence. So the choice is a Linux gate example or lock-at-CI-time, and the
  latter looks right for desktop until item 4 gives Linux a Pi gate. This decides
  the shape of the "small fixture-app set" above, so settle it first.

- **`kivyforge run` needs a release path before anything can test one.**
  `android_run()` calls `android_build(..., debug=True)` unconditionally and then
  looks for the debug output, so no flag makes `run` produce a release build.
  Android applies `byte_compile`/`strip_source` in release only, so the command
  developers use most cannot reach the stripping path at all. Fix the command,
  then cover it — a test written against `run` today would exercise the branch
  that was already fine. Small, and it belongs to this item because it is the
  reason the gap persisted.
- **Android T3 has never run from a Windows host**, which is where item 1's bug
  actually lived: `android_gradle` runs on ubuntu, so `find_interpreter()`'s
  Windows behaviour (the `py` launcher, versioned executables, pre-release
  rejection) is covered by unit tests and by one hand-run on 2026-09-13, and by
  nothing that repeats. A `windows-latest` job building one ABI and running the
  existing assertions is wiring plus Gradle time.

See [`test-matrix.md`](test-matrix.md) §5 for the full gap list in priority
order; it is the work queue for this item.

**Deliberately not automated:** anything needing an Apple ID, a real signing
cert, a physical device, or store submission. Item 2's checklist owns those.

**Done when** T0–T4 run in CI for every cell the matrix marks automatable, and
a hardware pass has a documented, repeatable procedure.

---

### 6. End-user docs (MkDocs Material → GitHub Pages)

*Was P4.*

**Current state.** `docs/guides/` is an intentional placeholder whose README
says guides will be *derived* from `docs/design/` — design docs are the source
of truth for behavior; guides distill the day-to-day workflow.

**Layout decision to settle first.** MkDocs conventionally treats `docs/` as
its source root, but `docs/` here holds ~50 design documents that are *not*
end-user material. Options are `docs_dir: docs/guides`, or a top-level
`site/`, or restructuring. Resolve before writing content — it determines
every internal link.

**Content, derived from the design docs**

- Getting started (install, `init`, first build) — the one page most readers
  will ever open.
- Per-platform guides: iOS, Android, Windows, macOS, Linux.
- Configuration reference for `[tool.kivy]` and each `[tool.kivy.<platform>]`
  overlay — distilled from `01-pyproject-*.md`, which are currently written as
  specs rather than as reference.
- CLI reference: `init` / `lock` / `build` / `run` / `package` / `doctor` /
  `status` / `clean` / `upgrade`.
- Troubleshooting, including signing prerequisites per platform.
- **Which host can build which target** — the item-2 matrix restated for end
  users. Verified 2026-09-12 that nothing in the repo states this in one place,
  and it is the first thing a new user gets wrong.
- **Raspberry Pi** as a section under the Linux guide rather than a platform of
  its own: it is an aarch64 AppImage cross-built on x86_64 (item 4).
- **Driving kivyforge from an agent or from CI** — `--json`, the envelope, the
  exit-code taxonomy, diagnostic IDs (item 3).

**Transition-safety.** Pages will publish to `elliotgarbus.github.io/kivyforge`
and move to `kivy.github.io/kivyforge` after the repo transfer. Therefore: use
**relative links** throughout, never hardcode the site origin, and **do not**
configure a custom domain (`CNAME`) before the transfer — it would have to be
redone.

**Done when** the site builds in CI and publishes on merge to the default
branch.

---

### 7. Real 3.0.0 release + Kivy transition checklist

*Was P5. Event-driven: nothing here starts before the GitHub repo moves.*

Everything deferred from P0 lands here, together, once the GitHub repo is
under the Kivy org.

- [ ] Add Kivy maintainer accounts (and/or `kivybot`) as PyPI **Owners**.
- [ ] Configure Trusted Publishing (OIDC) bound to `kivy/kivyforge`; remove the
      API token secret afterwards.
- [ ] Update `[project.urls]` — Homepage, Source, Bug Reports — to the Kivy org.
- [ ] Update the GitHub Pages URL and any absolute doc links; consider a custom
      domain only now.
- [ ] Resolve the `modernization-rfc` / `master` default-branch situation.
- [ ] Re-check the SDL-glue sync workflow's cross-repo reference to
      `kivy-mobile-wheels` if that repo moves too.
- [ ] Bump `3.0.0.dev0` → `3.0.0`, tag, release.

**Ordering note.** Nothing here should start before the repo actually moves —
doing any of it early means doing it twice, and in the Trusted Publishing case
means leaving an exploitable stale entry behind (see P0).

---

### 8. `native_integration` support for Android and iOS

**New 2026-09-12.** Target: post-3.0.0. Gated by its author's own condition —
after all platforms are working and tested — which is items 1–5.

> **`SPEC.md` in the
> [native-integration](https://github.com/ElliotGarbus/native-integration) repo is
> the only normative source**, and this entry was drafted from it, which is the
> right basis. [Doc 09](../common/09-native-sidecar-contract.md) was an earlier
> in-repo adoption record that the spec then moved ahead of; it has been reduced
> to a pointer, so nothing here needs reconciling against it.

**What it is.** `native_integration`
(`C:\Users\ellio\PycharmProjects\native-integration`) is a draft-v1 convention
plus a reference reader: a Python package ships a `native.toml` sidecar,
discovered through the `native_integration.v1` entry point, declaring what it
**owns** (Java namespaces), **requires** from the app (SDK floors, manifest
values, manual actions), and **contributes** (Gradle coordinates, Maven repos,
permissions, components, R8 keeps, SwiftPM packages, `Info.plist` entries,
Swift/Java source). Contract version `1.0`; library at `0.1.0.dev0`. Android
and iOS only — desktop is the build host, not a profile.

**The split that makes this tractable.** The library is a *reader*, explicitly
not a build tool: it discovers, validates, resolves, and records. It never
writes Gradle or Xcode output. So kivyforge's work is two clearly separable
halves, and only the second is large.

- **Read half (small).** Depend on `native-integration`; build a `Closure` from
  the already-resolved **target-platform** dependency set (not the build host's
  — this is requirement 1 and easy to get wrong); map kivyforge config onto
  `Application`; call `discover()` then `read()`; fail the build on
  `not integration.ok` and render `integration.report()` through item 3's
  reporter.
- **Generate half (large).** Roughly 15 spec requirements the reader explicitly
  leaves to the consumer, and they land squarely in the two backends kivyforge
  already generates projects for: inject Gradle dependencies and scoped
  repositories, merge permissions/`meta-data`/components/`view_links` into the
  manifest, apply R8 keeps, stage contributed Java/Kotlin/Swift source, add
  SwiftPM packages to the generated Xcode project, write
  `PrivacyInfo.xcprivacy` and `Info.plist` entries, register Swift↔Python
  modules, link `-ObjC` when a sidecar asks for categories, exclude `_native/`
  from the device payload, lock and SHA-verify the resolved Maven and SwiftPM
  graphs, and persist the acceptance record with a gate on changes.

**Three things kivyforge already has that fit, and one that does not.**
`[tool.kivy.android]` Gradle deps, `[tool.kivy.ios.native.swift_packages]`, and
`[tool.kivy.*.native.binaries]` are the same *kind* of declaration, just
authored by the app instead of by a dependency — so the staging and locking
machinery mostly exists. What does not exist is anywhere for the app to
**answer** a dependency: no config surface for per-distribution values,
acknowledgements, permission suppressions, export approvals, or credentials.
That is a new `[tool.kivy.native.<distribution>]` overlay and it needs
designing before any code.

**One bootstrap obligation to check early, because it could be structural.**
The spec requires the Android bootstrap activity to be an
`androidx.activity.ComponentActivity` (or subclass), and requires iOS URL
callbacks from `application(_:open:options:)` to reach app code rather than
being swallowed. kivyforge's bootstrap is a vendored SDL activity. **Confirm
what it actually inherits from before committing to this item** — if it is not
already a `ComponentActivity` that is a bootstrap change, and bootstrap changes
are the riskiest edits in the Android backend.

**The one cheap early move, and why it is worth doing out of order.** The spec
names kivyforge as its intended first consumer and says the contract stays
unfrozen until a real consumer builds to a device — and no consumer exists, so
52 conformance cases and 18 example sidecars have never met a build tool. A
**read-half-only spike** (map `Application`, run `discover()` + `read()`,
report, generate nothing) is small, is throwaway, and is the only way to find
out whether the config surface above is designable before the contract freezes.
Doing it during item 5 or 6, decoupled from the generator, costs little and
could save a v2 of the contract. It should not be allowed to grow into the
generate half early.

**Work**

- Spike the read half; feed findings back into the spec before freeze.
- Design the `[tool.kivy.native.<distribution>]` answer surface.
- Verify the `ComponentActivity` obligation against the current bootstrap.
- Generate half, Android first (kivyforge's Gradle generation is the more
  mature of the two), then iOS.
- Persist `native-integration.record` and implement the acceptance gate,
  including first-build acceptance.
- Wire `native-integration conformance --profile android|ios -- kivyforge …`
  into CI as a matrix cell (item 5).

**Done when** an app depending on a sidecar-shipping package builds and runs on
a real Android device and a real iPhone with no hand-edited Gradle or Xcode
settings, and the conformance corpus passes for both profiles.

**Prerequisite that is not ours:** `native-integration` is not on PyPI. Either
it publishes, or kivyforge vendors the reader — decide before the release that
ships this, not after.

---

### 9. Byte-compile the embedded stdlib at build time

Desktop bundles ship the embedded stdlib as pure `.py`, so every launch parses
it from source. Measured on 2026-09-15 (`test-matrix.md` §7): `import kivy`
costs **0.21 s** that way against **0.04 s** with a compiled stdlib — ~5×, or
~170 ms on every single launch, attributed by `-X importtime` to parsing
`typing`, `inspect`, `enum`, `logging` and `shutil`.

This is on the list because it is measured. It was invisible until macOS and
Linux both fixed their launchers: a `.AppImage` could never cache the stdlib
(read-only squashfs) and had been paying full cost since the beginning, while
the folder form and the `.app` were quietly buying the fast number by writing
`__pycache__` back into themselves — which on macOS invalidated the bundle's own
code signature. Both launchers now set `PYTHONDONTWRITEBYTECODE`, which is the
right fix and makes the cost permanent and explicit. Shipping real bytecode is
what removes it.

**Work**

- Run `compileall` over the staged runtime's stdlib during staging, on every
  desktop target (Linux, macOS, Windows). Use the same interpreter selection
  `byte_compile` already resolves, so cross-arch builds stay correct.
- Pass `PYTHONDONTWRITEBYTECODE=1` to the `byte_compile` subprocess. Its own
  imports currently deposit an arbitrary 41 stdlib `.pyc` into the artifact,
  which makes that subtree non-reproducible. Safe: `compileall` writes through
  `py_compile` and ignores the variable (verified 2026-09-15).
- Order matters on macOS — this must happen before `codesign`, like the existing
  payload compile, or it invalidates the signature it just sealed.
- Revisit both launcher comments once it lands; the environment variable becomes
  belt-and-braces rather than the whole defence.
- Re-measure and record, so the §5.10 number is retired rather than left stale.

**Done when** a freshly built desktop artifact contains no `.py`-only stdlib,
launching it writes nothing, and the measured `import kivy` cost is at parity
with the warm number above on all three desktop targets.
