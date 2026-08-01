# Roadmap — post-stripping work queue

> **Status: agreed 2026-07-30.** Six items, ordered. Phase B (byte-compile /
> `strip_source` across Android, the three desktop backends, and iOS) is done
> and validated on a real Windows release build; this is what follows it.
>
> Decisions already taken (see each item for the reasoning):
> **PyPI name reserved first** · **aarch64 is cross-build capable, validated
> natively on a Pi** · **docs are MkDocs Material → GitHub Pages** ·
> **PyPI stays a solo-owner personal project until the GitHub repo moves to
> the Kivy org.**

## Why this order

The name reservation is first because it is the only item that is *cheap and
time-sensitive at once* — `kivyforge` is unclaimed on PyPI today, the project
is publicly discussed, and a `.dev0` upload costs an afternoon. Everything
else can slip without anyone else being able to take it from us.

After that the order is: small independent wins (P1, P2) → the large feature
with a hardware lead time (P3) → docs, which want a settled feature surface
(P4) → the real release, which wants docs to link to (P5).

`build-for` vs `build-on` architecture (previously tracked as its own
deferred item) is **not** listed separately: Linux aarch64 is precisely the
case that makes it live, so it is folded into P3.

---

## P0 — Reserve `kivyforge` on PyPI

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

## P1 — Safe-area usage in the mobile examples

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

## P2 — `doctor` check for byte-compile misconfiguration

> **Prerequisite: install a final CPython 3.14 — and note the validation gap
> that its absence has been hiding.**
>
> The dev machine's only CPython 3.14 is a `3.14.0a7`, which the release-level
> guard correctly refuses. Every Android build here therefore takes the degrade
> path and ships source. The consequence is easy to miss: **`strip_source` has
> never actually executed on Android or iOS.** Phase B shipped it for the
> mobile backends, the unit tests cover the mechanics, and the *desktop* path
> is verified against a real artifact (`dice-roller`'s Windows `dist/` contains
> `app/main.pyc` and no `.py`) — but no mobile build has produced a stripped
> payload even once.
>
> Verified 2026-07-31: the staged Android bundle still contains
> `_python_bundle/app/main.py`.
>
> Install a **final** CPython 3.14.x (64-bit) and preferably remove the alpha,
> which is also the `*` default for `py -3.14` and so wins the launcher's
> lookup. That unblocks two things:
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

**Done when** `kivyforge doctor` reports the condition on every platform that
has the setting.

---

## P3 — Linux aarch64 (Raspberry Pi), cross-build capable

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

**Validation.** Cross-build from x86_64 can be validated immediately (build an
aarch64 AppImage, verify ELF classes and that no host binary leaked in).
Native build + actually *running* the AppImage waits on the Pi hardware.

**Deferred, unchanged:** win-arm64.

**Done when** an aarch64 AppImage built on x86_64 runs on a Raspberry Pi, and
a natively-built one does too.

---

## P4 — End-user docs (MkDocs Material → GitHub Pages)

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

**Transition-safety.** Pages will publish to `elliotgarbus.github.io/kivyforge`
and move to `kivy.github.io/kivyforge` after the repo transfer. Therefore: use
**relative links** throughout, never hardcode the site origin, and **do not**
configure a custom domain (`CNAME`) before the transfer — it would have to be
redone.

**Done when** the site builds in CI and publishes on merge to the default
branch.

---

## P5 — Real 3.0.0 release + Kivy transition checklist

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
