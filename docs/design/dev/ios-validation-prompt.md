# Agent prompt — validate the iOS marker fix on macOS

> **Run this on a Mac with Xcode installed**, from the repo root of the
> `modernization-rfc` branch. Everything below was written on a Windows host,
> where the iOS verbs cannot run; that is exactly what needs confirming.
>
> Copy the whole "Prompt" section to the agent, or point the agent at this file.

## Background (what changed and why it needs a Mac)

Two changes landed for iOS:

1. **The iOS workflow is now macOS-only, and enforced.**
   `IosPlatform.check_host_capability()` always described this rule, but
   nothing called it — an off-macOS invocation failed later with whatever
   error xcodebuild or SPM raised first. It is now called by `ios_build`,
   `ios_run`, `ios_package`, `ios_open`, **and `lock -p ios`**. Gating `lock`
   is a deliberate departure from every other backend, whose locks are
   host-portable: resolving declared Swift packages shells out to
   `swift package resolve`, which needs the Xcode toolchain.

2. **Marker evaluation now targets iOS instead of the macOS host.**
   pip's `--platform` selects acceptable wheel *tags*; it does not change how
   environment markers are evaluated. pip evaluates every
   `; sys_platform == "darwin"`-style marker against the interpreter running
   pip. Since iOS is always cross-resolved from macOS, that answered every
   marker as **macOS**: a dependency gated `sys_platform == "darwin"` was
   wrongly pulled into an iOS lock, and one gated `sys_platform == "ios"` was
   wrongly **dropped — silently**, yielding an app missing a dependency at
   runtime with no error at lock time.

   The fix (`kivyforge/lock/_pip_shim.py`) replaces
   `packaging.markers.default_environment` — the single function every
   `Marker.evaluate()` consults — with the target environment from
   `kivyforge/platforms/ios/lock/markers.py`, then runs pip unchanged. pip
   still performs the entire resolution. The same mechanism is already proven
   on Android, where the equivalent bug was loud (a Windows host produced
   "no matching distribution" for `kivy-deps.angle`) and the fix is verified:
   Windows and Linux now produce byte-identical Android locks.

**The gap this prompt closes:** the iOS half has unit tests but has never been
run against a real pip resolve, because `lock -p ios` now (correctly) refuses
on Windows. The single most important question is whether the
`default_environment` patch actually takes effect with the pip installed on
your Mac — it is a documented dependency on a pip internal, and it is designed
to **fail loudly** rather than silently fall back to host markers.

---

## Prompt

You are validating a change to kivyforge's iOS dependency resolver on macOS.
Work through the steps in order. Record the actual output of each check —
do not summarise a step as passing without the evidence in front of you. If a
step fails, capture the full error and continue with the remaining independent
steps rather than stopping.

### Step 0 — environment

```bash
cd <repo root>
git checkout modernization-rfc && git pull
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/kivyforge --version
.venv/bin/python -m pip --version
xcodebuild -version
swift --version
```

Record the **pip version** — it matters for Step 2. kivyforge requires
pip >= 24.3 for iOS resolution (>= 25.1 for Android).

### Step 1 — test suite and lint on macOS

```bash
.venv/bin/python -m pytest tests/ -q -o addopts=""
.venv/bin/python -m ruff check kivyforge/ tests/
```

**Expected:** all pass. The Windows run was 1790 passed / 8 skipped; macOS
should show *fewer* skips, since several skips are Windows symlink-privilege
guards. Report the exact counts and any test that fails only on macOS.

Note `tests/conftest.py` has an autouse fixture that no-ops the iOS host gate
so the suite runs anywhere; `tests/platforms/test_host_gating.py` calls the
real helpers. Both should pass on Darwin.

### Step 2 — prove the marker retargeting actually takes effect

**This is the decisive check.** pip's own installation report records the
environment it resolved against, so the shim's effect is directly observable.
Run the shim by hand and inspect the report:

```bash
KIVYFORGE_TARGET_MARKER_ENV='{"implementation_name":"cpython","implementation_version":"3.15.0","os_name":"posix","platform_machine":"arm64","platform_python_implementation":"CPython","platform_release":"","platform_system":"iOS","platform_version":"","python_full_version":"3.15.0","python_version":"3.15","sys_platform":"ios"}' \
.venv/bin/python kivyforge/lock/_pip_shim.py install \
  --dry-run --ignore-installed --only-binary=:all: \
  --python-version 3.15 --implementation cp \
  --platform ios_13_0_arm64_iphoneos --abi cp315 \
  --target /tmp/kf-probe-target --report /tmp/kf-probe.json \
  requests
```

Then:

```bash
.venv/bin/python -c "
import json; r = json.load(open('/tmp/kf-probe.json'))
env = r['environment']
print('sys_platform    =', env['sys_platform'])
print('platform_system =', env['platform_system'])
print('platform_machine=', env['platform_machine'])
assert env['sys_platform'] == 'ios', 'SHIM DID NOT TAKE EFFECT'
assert env['platform_system'] == 'iOS', 'SHIM DID NOT TAKE EFFECT'
print('OK: pip resolved against the iOS environment, not the macOS host')
"
```

**Pass:** `sys_platform = ios`. **Fail:** `darwin` means the patch did not
apply — report it immediately with the pip version; the shim's assumptions
about `pip._vendor.packaging.markers` no longer hold.

Also confirm the shim's guardrail works — it must refuse rather than quietly
use host markers:

```bash
env -u KIVYFORGE_TARGET_MARKER_ENV .venv/bin/python kivyforge/lock/_pip_shim.py install --dry-run requests; echo "exit=$?"
```

**Expected:** non-zero exit and a message about refusing to resolve with the
host's marker environment.

### Step 3 — the host gate permits iOS on macOS

The gate must *allow* everything here. Any "requires macOS with Xcode" error
on a Mac is a bug in the gate.

```bash
cd examples/mobile/hello-kivy
../../../.venv/bin/kivyforge doctor -p ios
```

Report anything the doctor flags.

### Step 4 — re-lock a real iOS project and diff (before/after evidence)

`examples/mobile/hello-kivy/pylock.ios.toml` is committed and was produced
*before* this change, so the diff is the evidence.

```bash
cd examples/mobile/hello-kivy
cp pylock.ios.toml /tmp/pylock.ios.before.toml
../../../.venv/bin/kivyforge lock -p ios --update
diff /tmp/pylock.ios.before.toml pylock.ios.toml
```

**Expected diff — and how to judge it:**

- **`dependencies = [...]` lists shrink.** This is the point of the change.
  The committed Kivy entry records **35** raw `Requires-Dist` names including
  `pytest`, `sphinx`, `ruff`, `pypiwin32`, `kivy_deps.angle`, `kivy_deps.glew`
  — none of which are installed on iOS. They should now be filtered to the
  edges whose markers actually hold on iOS (with `extra` empty, so extra-gated
  edges drop too).
- **`generated_at` changes.** Expected.
- **Nothing else should change.** In particular **no wheel filename, URL,
  version or sha256 may change**, and the set of `[[packages]]` must be
  identical. If a package appears or disappears, stop and report it in detail —
  that means the marker change altered which distributions get installed, which
  is a real behavioural change worth understanding before it ships.

Record the before/after `dependencies` list for Kivy verbatim.

### Step 5 — the SPM path (why `lock` is gated)

`keychain-spm` is the only example declaring Swift packages, so it is the one
that actually invokes `swift package resolve`.

```bash
cd examples/mobile/keychain-spm
../../../.venv/bin/kivyforge lock -p ios --update
```

**Expected:** succeeds, and the lock contains resolved Swift package pins
(revision, and a version when tag-resolved). This confirms the justification
for gating `lock -p ios` to macOS. Report the pinned revisions.

If it fails for a reason unrelated to this change (e.g. missing iOS wheels in
`examples/wheels/ios/`), say so explicitly rather than treating it as a
regression — and check whether `find_links` is populated.

### Step 6 — build and run on the simulator

Proves the toolchain path still works after the host-gate wiring.

```bash
cd examples/mobile/hello-kivy
../../../.venv/bin/kivyforge build -p ios --simulator
../../../.venv/bin/kivyforge run -p ios --simulator
```

**Expected:** the app builds, launches in the simulator, and renders. Capture
a screenshot if you can (`xcrun simctl io booted screenshot /tmp/ios.png`).
If the build fails for a pre-existing reason unrelated to these changes, say
so and include the error.

### Step 7 — Android host-independence, third host (bonus, only if wheels present)

The Android lock is deliberately host-portable and has been verified identical
between Windows and Linux. macOS would be a third data point.

**This step needs the vendored Android wheels, which are not committed** (see
`examples/wheels/android/README.md` — binaries stay out of the repo, matching
`examples/wheels/ios/`). Check first:

```bash
ls examples/wheels/android/*.whl 2>/dev/null || echo "SKIP step 7: no vendored wheels"
```

If they are absent, **skip this step and say so** — do not build them just for
this check; the recipe needs Linux/WSL plus the NDK, and the Windows↔Linux
comparison already covers the claim. If they are present:

```bash
cd examples/mobile/hello-android
cp pylock.android.toml /tmp/pylock.android.before.toml
../../../.venv/bin/kivyforge lock -p android --update
diff /tmp/pylock.android.before.toml pylock.android.toml
```

**Expected:** the *only* difference is the `generated_at` timestamp. Line
endings must stay LF. Any other difference is a host-independence regression —
report it in full.

### Step 8 — report

Write findings to `docs/design/dev/ios-validation-findings.md` covering:

- pip / Xcode / Swift versions and the macOS version.
- Step 2's `environment` values — the decisive evidence.
- The Step 4 diff, with the before/after Kivy `dependencies` lists.
- Whether any `[[packages]]` entry changed (and if so, which and why).
- Step 5 Swift pins; Step 6 build/run result; Step 7 diff.
- Anything that failed, with full error text.

Then update these, if and only if the evidence supports it:

- `kivyforge/platforms/ios/lock/markers.py` — correct any marker value that
  turned out wrong on a real resolve.
- `docs/design/dev/android-wheel-build-recipe.md` §"RESOLVED — the lock was
  host-dependent" — extend to record that the iOS half is now verified too.

Commit the findings on `modernization-rfc`. Do not push without asking.

**Be accurate about what you actually observed.** If a step could not run,
say it could not run — do not infer that it would have passed.
