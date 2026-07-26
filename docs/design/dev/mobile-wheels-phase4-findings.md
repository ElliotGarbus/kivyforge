# Mobile wheels repo — Phase 4 findings (macOS)

Phase 4 of [`.cursor/plans/mobile-wheels-repo.plan.md`](../../../.cursor/plans/mobile-wheels-repo.plan.md),
executed per
[`mobile-wheels-phase4-prompt.md`](mobile-wheels-phase4-prompt.md), on the
Mac, 2026-07-26. Repo: `ElliotGarbus/kivy-mobile-wheels`.

## Part A — seed the first Release from the existing wheels

### A1 — hash re-verification

Re-hashed all 6 wheels in `examples/wheels/ios/`; all matched Phase 0 exactly,
no drift.

### A2 — releases created

- [`kivy-ios-3.0.0.dev0`](https://github.com/ElliotGarbus/kivy-mobile-wheels/releases/tag/kivy-ios-3.0.0.dev0)
  — 3 wheel slices + `SHA256SUMS`.
- [`pyobjus-ios-1.2.4`](https://github.com/ElliotGarbus/kivy-mobile-wheels/releases/tag/pyobjus-ios-1.2.4)
  — 3 wheel slices + `SHA256SUMS`.

**Bug found and fixed while executing, not in the prompt:** `gh release
create <file>#SHA256SUMS` sets a display **label**, it does not rename the
uploaded asset. The asset was actually created as `SHA256SUMS-kivy` /
`SHA256SUMS-pyobjus`, with `SHA256SUMS` only as the label. The index
generator matches the exact asset **name** (`a["name"] == "SHA256SUMS"`), so
both releases would have silently produced an index with zero `#sha256=`
fragments — every wheel skipped — without ever raising an error. Fixed by
deleting the mislabeled assets and re-uploading a file literally named
`SHA256SUMS`, confirmed via `gh api .../releases/tags/<tag> --jq
'.assets[] | {name, label}'` on both releases. Worth calling out in
`recipes/*/README.md` or the release-creation step of Phase 5/6's automation
so this isn't rediscovered.

### A3 — index generator confirmation

```
Generating index for ElliotGarbus/kivy-mobile-wheels -> /tmp/idx
  kivy: 3 file(s)
  pyobjus: 3 file(s)
```

Zero skips. Generated `kivy/index.html`:

```html
<!DOCTYPE html>
<html><body>
    <a href="https://github.com/ElliotGarbus/kivy-mobile-wheels/releases/download/kivy-ios-3.0.0.dev0/kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphoneos.whl#sha256=9bd343eb6493a010dbf5665bcbb8410f410f4739be2532366fab88e9ae9ae8a1">kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphoneos.whl</a><br/>
    <a href="https://github.com/ElliotGarbus/kivy-mobile-wheels/releases/download/kivy-ios-3.0.0.dev0/kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphonesimulator.whl#sha256=c5dd880917ca53d52bfb9867d22636d2aba5651e22e8c21ec7756ccdc308fe91">kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphonesimulator.whl</a><br/>
    <a href="https://github.com/ElliotGarbus/kivy-mobile-wheels/releases/download/kivy-ios-3.0.0.dev0/kivy-3.0.0.dev0-cp315-cp315-ios_13_0_x86_64_iphonesimulator.whl#sha256=1fde7d1afa462efab3c598cd7fb31dcbdc27e65270348444a7bb07f01dd6f31d">kivy-3.0.0.dev0-cp315-cp315-ios_13_0_x86_64_iphonesimulator.whl</a><br/>
</body></html>
```

`pyobjus/index.html` is structurally identical (3 anchors, `#sha256=` on
each, pointed at the `pyobjus-ios-1.2.4` release).

**Part A is fully done.** Phase 5 (index → Pages) can proceed against these
two releases now.

## Part B — port the build scripts into the repo and CI

### B1 — what changed in the port

Ported `scripts/build_ios_wheels.sh` → `recipes/ios/kivy-3.0-sdl3.sh` and
`scripts/build_pyobjus_ios_wheels.sh` → `recipes/ios/pyobjus.sh`, transcription
not rewrite, per the recipe README's own instructions:

- Removed `KIVY_REF="${KIVY_REF:-master}"` / `PYOBJUS_REF="${PYOBJUS_REF:-master}"`.
  Both scripts now `source recipes/lib/pins.sh` and call `clone_pinned
  ios.kivy "$KIVY_SRC"` / `clone_pinned ios.pyobjus "$PYOBJUS_SRC"` — no
  fallback, a missing pin fails the build (verified: `pins.sh` correctly
  resolved and checked out the exact pinned commits in CI, see B3).
- Preserved the native-dependency caching (`ios-kivy-dependencies/dist/...`
  marker for Kivy, `ios-deps-install/.../libffi.a` marker for pyobjus).
- Preserved `CIBW_ENVIRONMENT_IOS="IPHONEOS_DEPLOYMENT_TARGET=$IOS_DEPLOYMENT_TARGET"`
  in both — did not lose the cross-venv deployment-target injection.
- Output directory changed from `examples/wheels/ios` (kivyforge-relative) to
  `dist/ios` (wheels-repo-relative), matching this repo's own layout and
  `.gitignore` (`*.whl`, `.build/`).

### B2 — CI workflow

Filled in `.github/workflows/build-ios.yml`: `workflow_dispatch` with a
`target` choice input, installs the CPython 3.15 macOS framework
non-interactively (`curl` + `sudo installer -pkg ... -target /`, skipped if
already present), runs the selected recipe, hashes the output, uploads as a
workflow artifact. Does not publish to a Release — B3 explicitly compares
against Part A instead.

### B3 — CI validation

**Run 1 (pyobjus) — failed, environment gap, not a port bug:**
[`30225133643`](https://github.com/ElliotGarbus/kivy-mobile-wheels/actions/runs/30225133643)
failed in 22s at `pip install cibuildwheel` with `error:
externally-managed-environment` (PEP 668). The pinned checkout step
immediately before it worked correctly — `clone_pinned` cloned
`kivy/pyobjus` and checked out `0c229e75248c14652b6764db5730eeb30bab95ed`
exactly, confirming the pin-reading mechanism itself is sound.

**Root cause:** `macos-14`'s system `python3` is Homebrew-managed, so bare
`pip install` is blocked there — a gap between the runner and any local dev
Mac, where this generally isn't an issue. **Not mentioned in
`recipes/ios/README.md`'s "what the port must change" list** — worth adding.

**Fix:** added `actions/setup-python@v5` (Python 3.12, the *host* interpreter
driving cibuildwheel — unrelated to the cp315 iOS target being cross-built)
before the recipe step. Committed as `b0cec5d`.

**Run 2 (pyobjus) — succeeded.**
[`30225212642`](https://github.com/ElliotGarbus/kivy-mobile-wheels/actions/runs/30225212642),
1m38s. **This is pyobjus's first-ever CI run anywhere** (no upstream iOS CI
exists) — it passed on the first attempt after the environment fix, no
recipe-logic changes needed. `setup.py`'s `sys.platform == "ios"` gating and
`platform.ios_ver().is_simulator`/`ARCH` slice selection — flagged in the
README as the first things to check on failure — were never implicated.

**Run 3 (kivy-3.0-sdl3) — succeeded.**
[`30225296520`](https://github.com/ElliotGarbus/kivy-mobile-wheels/actions/runs/30225296520),
5m3s, including the full SDL3+ANGLE+ThorVG native-dependency build (no cache
hit — first run on a fresh runner).

**Hash comparison (both, as predicted by the prompt — wheel builds are not
bit-reproducible):**

| Wheel | Part A (local Mac, pinned commit) | Part B (CI, same pinned commit) |
|---|---|---|
| `pyobjus-...arm64_iphoneos.whl` | `f8833074...` | `32c2806a...` |
| `pyobjus-...arm64_iphonesimulator.whl` | `edbcb686...` | `46b03ac9...` |
| `pyobjus-...x86_64_iphonesimulator.whl` | `ddc92fa3...` | `4cf26516...` |
| `kivy-...arm64_iphoneos.whl` | `9bd343eb...` | `59cb6e7f...` |
| `kivy-...arm64_iphonesimulator.whl` | `c5dd8809...` | `57dd7c5b...` |
| `kivy-...x86_64_iphonesimulator.whl` | `1fde7d1a...` | `9ca50708...` |

All 6 differ, exactly as expected. **Per the prompt, CI output was not
published**, and the Part A release assets were not touched — this run is
validation only.

## Scripts vs README: anything undocumented found

The one gap: the PEP 668 externally-managed-environment failure on
`macos-14`'s system Python. Neither `recipes/ios/README.md` nor the original
kivyforge scripts' comments mention it, because it never surfaces on a normal
dev Mac (Homebrew Python there is typically not marked externally-managed the
same way, or a venv is already active). It is purely a GitHub-hosted-runner
trait. Recommend adding a line to `recipes/ios/README.md`'s "what the port
must change" section so a future Android-CI port (or any other recipe adding
a fresh `pip install` step) doesn't rediscover it.

## Status

Both parts complete. Wheels repo commits: `9847ba3` (pins), `8ff75d6` (port +
workflow), `b0cec5d` (CI fix), `7350cdd` (README note on the PEP 668 gap).
Releases live; CI validated for both recipes.

Phase 5 (index generator + Pages) landed concurrently on the Windows machine
while this phase was running here — `84538aa` "Deploy the PEP 503 index to
Pages" appeared on `origin/main` between this session's pushes, exactly as
the prompt anticipated ("Phase 5 can begin on the Windows machine as soon as
this lands"). The iOS half of Phase 6 (repoint examples at the index, re-lock,
re-validate on-device) remains.
