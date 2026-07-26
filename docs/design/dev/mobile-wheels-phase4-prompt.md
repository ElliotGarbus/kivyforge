# Agent prompt — Phase 4: iOS recipes into the wheels repo (macOS)

> **Run this on the Mac with Xcode.** cibuildwheel's iOS target is macOS-only,
> so this phase cannot run anywhere else.
>
> Copy the "Prompt" section to the agent, or point the agent at this file.

## Context

`ElliotGarbus/kivy-mobile-wheels` now exists (Phase 1 complete): a bridge repo
that builds Android + iOS wheels reproducibly, hosts them on GitHub Releases,
and serves them as a PEP 503 index so kivyforge projects resolve them via
`extra_index_urls` like any PyPI package. Full plan:
`.cursor/plans/mobile-wheels-repo.plan.md` in the kivyforge repo.

Phase 0 (already done, on this Mac) found something that reshapes this phase:
**the 6 existing iOS wheels in `examples/wheels/ios/` are usable as-is.** Their
sha256s were independently verified and match the committed example locks
exactly, and the exact upstream commits that built them were recovered from the
cached checkouts. Those commits are now pinned in the wheels repo's
`recipes/PINNED_REFS.toml`:

| | commit | date |
|---|---|---|
| `kivy/kivy` | `a933f859b4d0add7267798ffba5abb1a456da7f4` | 2026-06-22 |
| `kivy/pyobjus` | `0c229e75248c14652b6764db5730eeb30bab95ed` | 2025-12-29 |

These are **deliberately not master HEAD.** Rebuilding from newer commits would
produce wheels nobody has run and invalidate the hashes in
`examples/mobile/hello-kivy/pylock.ios.toml`, forcing a re-lock and fresh
device validation to get back to where we already are.

So this phase splits into two halves with very different risk:

- **Part A — seed the first Release from the existing wheels.** Fast, no
  building. Unblocks the index (Phase 5) and the iOS half of Phase 6
  immediately. Do this first.
- **Part B — port the build scripts into the repo and CI.** Slower, and the
  pyobjus path has never run in CI anywhere. Its first run *is* the validation.

---

## Prompt

You are executing Phase 4 of the kivy-mobile-wheels plan on macOS. Work in
order; Part A is independent of Part B and much higher value per minute, so
finish and push it before starting Part B. Record what you actually observe —
if something fails, capture the error and continue with independent steps
rather than stopping.

### Step 0 — clone and orient

```bash
cd ~/PycharmProjects   # or wherever kivyforge lives
git clone https://github.com/ElliotGarbus/kivy-mobile-wheels
cd kivy-mobile-wheels
cat recipes/PINNED_REFS.toml
cat recipes/ios/README.md
```

`recipes/ios/README.md` lists exactly what the port must change. Read it before
touching anything.

Confirm `gh auth status` works — you will create a Release.

---

## Part A — seed the first Release (do this first)

### A1 — re-verify the wheels

Phase 0 hashed these; confirm nothing drifted since:

```bash
cd <kivyforge repo>/examples/wheels/ios
shasum -a 256 *.whl
```

Expected (from `docs/design/dev/mobile-wheels-phase0-inventory.md`):

```
9bd343eb6493a010dbf5665bcbb8410f410f4739be2532366fab88e9ae9ae8a1  kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphoneos.whl
c5dd880917ca53d52bfb9867d22636d2aba5651e22e8c21ec7756ccdc308fe91  kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphonesimulator.whl
1fde7d1afa462efab3c598cd7fb31dcbdc27e65270348444a7bb07f01dd6f31d  kivy-3.0.0.dev0-cp315-cp315-ios_13_0_x86_64_iphonesimulator.whl
f8833074f6493cc9fa25259180ca8aa36c961b0901d5f0c58546612e5a208ac7  pyobjus-1.2.4-cp315-cp315-ios_13_0_arm64_iphoneos.whl
edbcb6866c2696eb01815789765dcb2fc56032de468e448ec936370f907e1405  pyobjus-1.2.4-cp315-cp315-ios_13_0_arm64_iphonesimulator.whl
ddc92fa36049d816aa13a5efef37927e2bedea459c692c628254bbe5e93633ef  pyobjus-1.2.4-cp315-cp315-ios_13_0_x86_64_iphonesimulator.whl
```

**Any mismatch: stop and report.** These hashes are pinned in committed lock
files; a difference means the working copy is not what was validated.

### A2 — create two Releases

One release per package, so either can be bumped without re-releasing the
other. Tag scheme: `<package>-ios-<version>`.

Each release needs a `SHA256SUMS` asset — the index generator reads it to
attach `#sha256=` fragments, and **skips any wheel it cannot hash**, so a
release without it produces an empty index.

```bash
cd <kivyforge repo>/examples/wheels/ios

# Kivy
shasum -a 256 kivy-*.whl > /tmp/SHA256SUMS-kivy
gh release create kivy-ios-3.0.0.dev0 \
  --repo ElliotGarbus/kivy-mobile-wheels \
  --title "Kivy 3.0.0.dev0 — iOS" \
  --notes "Built from kivy/kivy@a933f859b4d0add7267798ffba5abb1a456da7f4 (2026-06-22).

Slices: arm64_iphoneos, arm64_iphonesimulator, x86_64_iphonesimulator (cp315).
Validated on-device: renders on the iOS simulator via kivyforge (see
kivyforge docs/design/dev/ios-validation-findings.md).

Bundles SDL3, ANGLE and ThorVG xcframeworks inside the wheel." \
  kivy-*.whl /tmp/SHA256SUMS-kivy#SHA256SUMS

# pyobjus
shasum -a 256 pyobjus-*.whl > /tmp/SHA256SUMS-pyobjus
gh release create pyobjus-ios-1.2.4 \
  --repo ElliotGarbus/kivy-mobile-wheels \
  --title "pyobjus 1.2.4 — iOS" \
  --notes "Built from kivy/pyobjus@0c229e75248c14652b6764db5730eeb30bab95ed (2025-12-29).

Slices: arm64_iphoneos, arm64_iphonesimulator, x86_64_iphonesimulator (cp315).
Note: pyobjus has no iOS CI upstream; this build path is not upstream-validated." \
  pyobjus-*.whl /tmp/SHA256SUMS-pyobjus#SHA256SUMS
```

### A3 — confirm the index generator sees them

```bash
cd <kivy-mobile-wheels>
GH_TOKEN=$(gh auth token) python3 index-gen/generate_index.py --output /tmp/idx
find /tmp/idx -name index.html | sort
grep -o 'sha256=[0-9a-f]\{8\}' /tmp/idx/kivy/index.html | head
```

**Expected:** `kivy` and `pyobjus` directories, 3 anchors each, every href
carrying a `#sha256=` fragment. If any wheel is reported skipped for having no
sha256, the `SHA256SUMS` asset is wrong — fix and re-run.

Report the generated `kivy/index.html` verbatim; it is small and it is the
artifact Phase 5 deploys.

**Part A is done here.** Push nothing (releases are server-side) and report
before starting Part B — Phase 5 can begin on the Windows machine as soon as
this lands.

---

## Part B — port the build scripts

Source scripts: `scripts/build_ios_wheels.sh` and
`scripts/build_pyobjus_ios_wheels.sh` in the kivyforge repo. They work; this is
a port, not a rewrite. Target: `recipes/ios/kivy-3.0-sdl3.sh` and
`recipes/ios/pyobjus.sh` in the wheels repo.

### B1 — required changes

**Remove the branch-name defaults.** Both currently do
`KIVY_REF="${KIVY_REF:-master}"` / `PYOBJUS_REF="${PYOBJUS_REF:-master}"`.
Replace with the pinned commit, via the helper already in the repo:

```bash
source "$(dirname "$0")/../lib/pins.sh"
clone_pinned ios.kivy "$KIVY_SRC"        # or: pin_get ios.kivy commit
```

There must be **no fallback**. A missing pin has to fail the build — that is
the entire point of the manifest, and `pins.sh` already enforces it (it checks
errors explicitly rather than relying on `set -e`, which bash disables inside
functions called in `||` lists and command substitutions).

**Keep the native-dependency caching.** Kivy's
`tools/build_ios_dependencies.sh` (SDL3 + ANGLE + ThorVG) is slow; the existing
script skips it when the SDL3 marker exists. Preserve that.

**Deployment target must go through `CIBW_ENVIRONMENT_IOS`.** Exporting
`IPHONEOS_DEPLOYMENT_TARGET` in the shell is not enough — iOS builds run in an
isolated cross-venv and cibuildwheel silently tags wheels `ios_13_0_*` instead
of `ios_16_0_*`. The existing scripts already get this right; do not lose it in
the port.

Note the existing wheels are tagged `ios_13_0_*`, which is expected and fine —
the python.org cp315 binary targets 13.0 and a lower minimum is compatible with
a 16.0 project.

### B2 — CI workflow

Fill in `.github/workflows/build-ios.yml` (currently a skeleton that fails
loudly by design). It needs to install the CPython 3.15 macOS framework
non-interactively — the local scripts stop and ask the user to `sudo installer
-pkg` it, because cibuildwheel refuses to sudo-install outside CI. In CI, just
install it.

### B3 — validate the port

Run the workflow via `gh workflow run build-ios.yml -f target=pyobjus`.

**Do pyobjus first.** It is small (~300 KB vs ~24 MB), fast, and it is the path
that has never run in CI anywhere — `setup.py` gates the iOS branch on
`sys.platform == "ios"` and picks the libffi slice via
`platform.ios_ver().is_simulator` and `ARCH`. If it fails, those are the first
two things to check.

Then `-f target=kivy-3.0-sdl3`.

**Do not publish anything Part B builds yet.** Compare a CI-built wheel's
sha256 against the Part A release. They will almost certainly differ — wheel
builds are not bit-reproducible — which is expected and is exactly why the
README says consumers must re-lock rather than assume hashes carry over. Report
the comparison; do not replace the Part A assets with CI output in this phase.

---

## Report

Write findings to `docs/design/dev/mobile-wheels-phase4-findings.md` in the
**kivyforge** repo (not the wheels repo) and commit on `modernization-rfc`:

- Part A: hash re-verification result, the two release URLs, the generated
  index HTML.
- Part B: what changed in the port, whether each CI build succeeded, and for
  pyobjus specifically — its first CI run anywhere — what broke and how, if
  anything.
- Any place the existing scripts turned out to do something the recipe READMEs
  do not mention.

Be accurate about what you observed. If Part B could not complete, say so
plainly — Part A is independently valuable and does not depend on it.
