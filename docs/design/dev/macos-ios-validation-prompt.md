# Agent prompt — macOS and iOS validation on the Mac

> **Run this on the Mac**, from the repo root of `modernization-rfc`. Written
> 2026-09-14 from the Windows host, where none of it can run.
>
> Point the agent at this file, or copy the "Prompt" section.
>
> Follows the shape of [`ios-validation-prompt.md`](ios-validation-prompt.md),
> whose run produced [`ios-validation-findings.md`](ios-validation-findings.md).

## Background — why this is worth a careful run

Per [`test-matrix.md`](test-matrix.md), as of this morning:

- **`kivyforge build -p macos` had never run anywhere**, in CI or locally, so
  `codesign`, `lipo`, and `hdiutil` had never executed outside a mock.
  `macos_integration` proves two `clang` tests and nothing about a `.app`.
- **Notarization and real-certificate signing** were both on §6's manual
  checklist as never attempted.
- **iOS is already proven on the *simulator*** — `build`/`run -p ios
  --simulator` green and all six iOS examples rendering, as first-party local
  runs in July. What is missing for iOS is `strip_source`, any device, any T3,
  and anything in CI. iOS is not virgin ground; do not treat it as such.

Since then the maintainer has, by hand: **built `examples/desktop/dice-roller`
for macOS, Developer-ID signed it, run it, and submitted it for notarization,
which Apple accepted.** None of that is recorded yet.

So three never-done items moved in one afternoon and the evidence is sitting on
one machine, unlogged. Under this repo's own rule — an unlogged manual test did
not happen — capturing it is more valuable than any new build. **Evidence
first.**

---

## Prompt

You are continuing kivyforge's macOS/iOS validation on the Mac. The environment
is already set up. Significant work has already been done by hand: your first
job is to **capture** it, not repeat it.

Work through the steps in order. Record the actual output of each check — do not
summarise a step as passing without the evidence in front of you. If a step
fails, capture the full error and continue with the remaining independent steps.

### Step 0 — environment, as evidence

```bash
git pull                      # you need 481da969 or later
sw_vers; xcodebuild -version; swift --version
.venv/bin/kivyforge --version; .venv/bin/python -V; .venv/bin/python -m pip -V
security find-identity -v -p codesigning | grep "Developer ID"
```

Then **read [`test-matrix.md`](test-matrix.md)** before doing anything else:
§3.2 for what is actually covered, §5 for the gap list, §6 for the manual
checklist, §7 for the dated log, and the three rules at the top. Do not rely on
any summary of it, including this file's Background section.

### Step 1 — capture the macOS artifact before the state is lost

```bash
cd examples/desktop/dice-roller
APP=$(ls -d build/macos/*.app)          # locate it; adjust if the path differs

codesign --verify --deep --strict --verbose=2 "$APP"
codesign -dvvv "$APP"                   # identity, hardened runtime, flags
codesign -d --entitlements - "$APP"
xcrun stapler validate "$APP"
spctl -a -vvv -t exec "$APP"
lipo -archs "$APP"/Contents/MacOS/*
xcrun notarytool history --keychain-profile <profile>
```

Record all of it verbatim. **`spctl` accepting a stapled build is the strongest
single signal in this exercise** and nothing in this repo has ever produced it.

**Notarization was submitted and ACCEPTED, so two of these are assertions, not
observations:**

- `xcrun stapler validate` must print *"The validate action worked!"*
- `spctl -a -vvv -t exec` must report **accepted**, `source=Notarized Developer ID`

If the submission is Accepted but `stapler validate` **fails**, that is a
genuine finding rather than a fluke. Acceptance only means Apple issued a
ticket; stapling is what attaches it to the bundle. The two come apart if
stapling errored without failing the command, or if the `.app` was rebuilt or
re-signed *after* being stapled. Report the mismatch — do not re-run until it
passes. An app that needs the network to clear Gatekeeper is not correctly
stapled, and that is exactly the kind of defect a first-ever run should surface.

Also confirm the generated `pylock.macos.toml` was **not** committed. Desktop
examples gitignore `pylock.*.toml` deliberately — see
[`common/03-lockfile-concept.md`](../common/03-lockfile-concept.md)
§"Example-repo lock policy". If it got committed, untrack it.

### Step 2 — is the payload already stripped? (probably a free win)

`byte_compile` and `strip_source` both default to the string `"release"` for
`[tool.kivy.macos.build_settings]`, and `package` is the release path — so the
app you already notarized **may already have a bytecode-only payload**. If so,
macOS `strip_source` is proven and needs only verifying.

```bash
find "$APP" -name '*.py'   | wc -l        # expect 0 if stripping happened
find "$APP" -name '*.pyc'  | wc -l        # expect many
find "$APP" -name '__pycache__' -type d   # expect none
```

Then verify the bytecode is importable **by the runtime the bundle ships**. This
was roadmap item 1's actual bug on Android:

- find the shipped CPython (`Python.framework` / `libpython`) and its version
- read the first four bytes of several `.pyc` files
- compare against **that** runtime's magic, **not** against whatever `python`
  you are running

Deriving the expected magic from the running interpreter is how the check ends
up blaming the artifact for a runner mismatch — that mistake was made once
already and caught only because two real APKs were on hand to test against.

If `.py` files **are** present, then `strip_source` did not apply on the release
path. That is a finding in its own right: report it rather than setting
`strip_source = true` and moving on, because the interesting question is why the
default did not take effect.

### Step 3 — iOS simulator regression check

```bash
cd examples/mobile/hello-kivy
../../../.venv/bin/kivyforge doctor -p ios
../../../.venv/bin/kivyforge build -p ios --simulator
../../../.venv/bin/kivyforge run   -p ios --simulator
xcrun simctl io booted screenshot /tmp/ios-hello.png
```

July proved this and nothing re-proves it, so treat it as a regression check
against two months of Windows-side work. Expected: builds, launches, renders
"Hello Kivy".

`hello-kivy/pylock.ios.toml` **is** committed — it is one of the three exempt
on-device gate examples. If `lock -p ios` would change it, diff and report
rather than committing the change.

### Step 4 — iOS `strip_source`, never done on any target

**Read [`ios-source-stripping.md`](ios-source-stripping.md) first.** It is the
design record for this feature (implemented 2026-07-30) and it contains a hazard
you must not discover empirically.

The config paths are asymmetric. Do not guess them:

| Target | Table |
|---|---|
| iOS | `[tool.kivy.ios.python.build_settings]` |
| macOS | `[tool.kivy.macos.build_settings]` |

Both accept a bool or the string `"release"`, and both default to `"release"`,
so a **debug** build proves nothing.

> **Use `package -p ios`, not `build -p ios`.**
>
> On iOS, `<app>-ios/app` is a **symlink into your own `app_dir`**, not a copy —
> it exists for fast edit-rebuild iteration (`platforms/ios/staging.py`).
> Byte-compiling and stripping *through that symlink* would delete `.py` files
> from the real working tree. That is precisely why the feature is release-only:
> `build`/`run` keep the symlink untouched, and `package` materialises a real,
> disposable copy of `app_dir` first and strips **that**.
>
> So: run `package`, and afterwards run `git status` in the example directory and
> confirm **no source file was deleted from the working tree**. If any were, stop
> immediately and report it — that is a data-loss bug, and it is the single most
> serious thing this whole exercise could uncover. Consider working from a clean
> commit so the check is unambiguous.

Then apply Step 2's checks to the payload inside the packaged artifact. For the
macOS side, [`macos-x86-removal-and-desktop-stripping.md`](macos-x86-removal-and-desktop-stripping.md)
is the corresponding record.

### Step 5 — T3 artifact assertions, now that real artifacts exist

[`test-matrix.md`](test-matrix.md) §5.1 has this open and it is no longer
blocked. Copy the Android shape exactly; the split is deliberate:

- `tests/artifact_checks.py` — **pure functions returning lists of problem
  strings**, so one run reports every fault instead of stopping at the first,
  and so they unit-test against synthetic bundles with no build in sight.
- `tests/test_artifact_checks.py` — the hermetic half.
- `tests/platforms/android/test_apk_artifact.py` — a thin driver aiming them at
  a real file via `--android-apk`, with options registered in
  `tests/conftest.py`.

Add the macOS equivalent behind `--macos-app`: Mach-O arch (import the
constants from `platforms/macos/machotools.py` so they cannot drift from the
build's), Step 2's payload properties, `Info.plist` against config, and
`codesign`/`stapler` verification. The signed and notarized dice-roller app is
your fixture.

### Step 6 — device, only with hardware and a profile

Simulator builds skip signing and provisioning entirely, so the device path is
wholly unexercised. `examples/verify-ios-device.sh` exists and has never had a
logged run.

If you have no device or no provisioning profile, **say so and skip**. Do not
infer that it would have worked.

### Step 7 — report

Write findings to `docs/design/dev/macos-ios-validation-findings.md`, using
[`ios-validation-findings.md`](ios-validation-findings.md) as the model: an
environment table, then per-step actual output.

Then update [`test-matrix.md`](test-matrix.md). These are substantial edits, not
cosmetic ones:

- **§7** — a row per run. The table has a **Host** column; fill it. Mark
  maintainer-run work as `local` with a date, never "every push".
- **§3.2** — macOS T2 is no longer "two `clang` tests" and macOS T3 is no longer
  `none`. macOS may now be the only desktop target with a verified end-to-end
  distributable artifact, **ahead of both Windows and Linux**, which reorders
  §5's desktop priorities.
- **§6** — tick notarization and real-certificate signing, linking the evidence.
- **Known-unverified** — remove what you proved; add what you discovered is not.

### Rules of engagement

- Record what you **observed**. If a step could not run, say it could not run.
- Describe what actually **executed**. `test-matrix.md` has twice been wrong
  because someone trusted a findings doc's summary line over its steps — most
  recently a claim that no iOS toolchain had ever run, while the linked
  document's Step 6 was a green `xcodebuild`. Read the evidence, not the
  abstract.
- Do **not** commit generated example locks (Step 1).
- Commit on `modernization-rfc`. **Do not push without asking.**
