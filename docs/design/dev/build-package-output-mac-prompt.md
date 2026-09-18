# Agent prompt — `build`/`package` output on the Mac

> **Run this on the Mac**, from the repo root of `modernization-rfc`. Written
> 2026-09-16 from the Windows host, where the macOS and iOS paths below ran only
> against stubs.
>
> Point the agent at this file, or copy the "Prompt" section.
>
> Follows the shape of [`macos-ios-validation-prompt.md`](macos-ios-validation-prompt.md).

## Background — what changed, and what was never run for real

[`build-package-output-proposal.md`](build-package-output-proposal.md) was
implemented in four commits on 2026-09-16:

| Commit | Step | What it did |
|---|---|---|
| `1930abe2` | 1 | Backends return a `BuildOutcome` and report through `BuildEvents` callbacks |
| `07fb1b7f` | 2 | Gradle's output goes to stderr instead of inheriting stdout |
| `e0a42ed9` | 3 | `build --json` / `package --json`; all progress moves to stderr |
| `89798096` | 4 | Failure codes and exit statuses (§4.4) |

Every one of those was verified on Windows only. The hermetic suite exercises
the macOS and iOS backends with `xcodebuild`, `codesign`, the bundler and the
host gates **stubbed**, so none of the following has executed for real:

- **iOS `build --simulator`/`--device` now builds into
  `<slug>-ios/build/DerivedData`** (it passes `-derivedDataPath`, as `run`
  already did) and then **fails if the `.app` is not there**. That existence
  check has only ever met a fake xcodebuild. If the real product lands somewhere
  else — a different configuration folder, a `PRODUCT_NAME` that is not the
  scheme — a build that used to succeed now fails with `KF-ARTIFACT-MISSING`.
  This is the highest-risk change in the set.
- **iOS `package`/`build --release` now checks the exported `.ipa` exists**
  at `<slug>-ios/build/<scheme>.ipa`, and fails otherwise. Same risk, needs a
  signing identity to reach.
- **A failed `xcodebuild` no longer embeds its log in the error.** The log is
  printed as progress on stderr and the error is one line
  (`xcodebuild build failed (exit 65); its output is above.`).
- **Stream split.** Everything except product lines (`Built`, `Generated`,
  `Packaged`, `Exported`, and the distribution advice) moved to stderr. Human
  output is meant to look identical on a terminal.
- **Spawn failures.** `run_command` now catches `OSError`, and the macOS
  `codesign`/`otool`/`clang`/`notarytool` handlers were widened from
  `FileNotFoundError` to `OSError`; both used to escape as tracebacks.
- **Rich renders the human lines** under `build`/`package` now, instead of
  `click.echo`. Byte-identical on Windows in `CliRunner`; never seen on a real
  macOS terminal.

The envelope contract, for reference: stdout under `--json` is exactly one JSON
object with `schema`, `kivyforge`, `command`, `platform`, `ok`, `data` and
`diagnostics`; `data.artifacts` is a list of `{"path", "kind"}`, paths relative
to the project root and posix-separated. Exit codes: `0` ok, `1` config/other,
`3` environment (host, missing/unusable tool), `4` lock, `5` build failure.

---

## Prompt

You are verifying kivyforge's new `build`/`package` output contract on a real
Mac. The code is written and passes its hermetic tests on Windows; your job is to
find out whether it is true against real Xcode. **Record what you observe.** Do
not summarise a step as passing without its output in front of you. If a step
fails, capture the full output and continue with the independent steps.

**Capture stdout and stderr separately in every step**, because the streams are
the thing under test:

```bash
kf() { ../../../.venv/bin/kivyforge "$@" >/tmp/kf.out 2>/tmp/kf.err; echo "exit=$?"; }
```

After each `kf` call, look at `/tmp/kf.out` and `/tmp/kf.err`, and for `--json`
runs validate stdout with `python -m json.tool /tmp/kf.out`.

### Step 0 — environment and the suite

```bash
git pull                      # you need 89798096 or later
sw_vers; xcodebuild -version
.venv/bin/kivyforge --version; .venv/bin/python -V
.venv/bin/python -m pytest -q
.venv/bin/pyright kivyforge
```

The full suite matters more here than on Windows: the iOS CLI tests are marked
`requires_symlinks` and **skip on the Windows host**, so this is the first run of
`tests/cli/test_build.py`, `test_package.py` and `test_build_run_open.py` against
the Step 1–4 changes. Report any failure verbatim. `pyright kivyforge` should
report 0 errors.

### Step 1 — macOS, human mode then `--json`

```bash
cd examples/desktop/dice-roller
kf build -p macos
kf build -p macos --json
kf package -p macos --json
```

For the human run, check:

- `/tmp/kf.out` holds **only** `Built build/macos/<Name>.app`.
- `/tmp/kf.err` holds the staging and signing progress.
- Run it once more with no redirection and compare by eye with how `build`
  looked before today: the interleaved text should be unchanged, with no escape
  codes when piped (`| cat`).

For the `--json` runs, check:

- stdout parses as one document; `ok` is `true`, `platform` is `"macos"`.
- `build`: `data.artifacts == [{"path": "build/macos/<Name>.app", "kind": "app"}]`.
- `package` without an identity: the same single `app` artifact (never two —
  the inner build must not be recorded) and a `KF-SIGNING-UNCONFIGURED` warning
  in `diagnostics`, exit `0`.
- If a Developer ID identity is available, repeat `package` with
  `--signing-identity` (and `--notary-profile` if you have one): one artifact,
  no `KF-SIGNING-UNCONFIGURED`, and the signing/notarization progress on stderr.

If `byte_compile` degraded because no final CPython of the target minor was
found, expect a `KF-BYTECOMPILE-NO-INTERP` warning and note which interpreter
was missing.

### Step 2 — iOS simulator: the DerivedData change

This is the step most likely to find a real defect.

```bash
cd examples/mobile/hello-kivy
rm -rf hello-kivy-ios/build/DerivedData      # prove this run produces it
kf build -p ios --simulator
ls -d hello-kivy-ios/build/DerivedData/Build/Products/*/*.app
kf build -p ios --simulator --json
```

Adjust the `hello-kivy-ios` name to whatever `Generated` printed.

- The human run must end with `Built hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/<scheme>.app`
  on stdout, and that path must exist.
- The `--json` run: artifacts are `project` then `app`, in that order.
- If the build **fails with `KF-ARTIFACT-MISSING`**, do not work around it.
  Record the path kivyforge expected (it is in the message), the path Xcode
  actually used (`ls` the DerivedData tree), and the scheme's `PRODUCT_NAME`.
  That mismatch is the finding.

Then confirm `run` and `status` agree with where `build` now puts things:

```bash
kf run -p ios --simulator --no-build        # must find the .app build just made
kf status -p ios --json                     # simulator artifact should read as built
```

`run` is out of scope for the output change and still prints progress on stdout;
note it, do not report it as a defect.

### Step 3 — iOS failure classification

Each of these should produce a parseable envelope with `ok: false`. Record the
exit code, `diagnostics[0].code`, `diagnostics[0].context` and the first line of
`diagnostics[0].message`.

**a. A tool that fails** (expect exit `5`, `KF-BUILD-TOOL-FAILED`,
`context = {"tool": "xcodebuild", "task": "build"}`):

```bash
kf build -p ios --device --signing-identity "No Such Identity" --json
```

Check the xcodebuild transcript is in `/tmp/kf.err` and **not** in the
diagnostic message — the message should be a single line. If `--device` fails
earlier on a missing team ID, that is `KF-ERROR` from the signing pre-flight;
record it, set a team ID, and retry.

**b. A tool that is missing** (expect exit `3`, `KF-TOOLCHAIN-MISSING`,
`context.tool == "xcodebuild"`):

```bash
env PATH="$PWD/../../../.venv/bin" ../../../.venv/bin/kivyforge build -p ios --simulator --json \
  >/tmp/kf.out 2>/tmp/kf.err; echo "exit=$?"
```

Before today this was a Python traceback with nothing on stdout. If something
else on the path fails first (`swift`, `git`), record what, since that is a
spawn site this change did not reach.

**c. Lock drift** (expect exit `4`, `KF-LOCK-DRIFT`):

```bash
cp pyproject.toml /tmp/pyproject.bak
echo "# drift" >> pyproject.toml
kf build -p ios --json
cp /tmp/pyproject.bak pyproject.toml
```

**d. `--release` / `package -p ios`**, only if you have a distribution identity
and team: expect artifacts `project` + `ipa` for `build --release`, and `ipa`
alone for `package`. If `package` fails with `KF-ARTIFACT-MISSING`, record where
`-exportArchive` actually wrote the `.ipa` — kivyforge expects
`<slug>-ios/build/<scheme>.ipa`. Without signing credentials, **say so and skip**.

### Step 4 — macOS spawn handling (optional, cheap)

```bash
cd examples/desktop/dice-roller
env PATH="$PWD/../../../.venv/bin" ../../../.venv/bin/kivyforge build -p macos --json \
  >/tmp/kf.out 2>/tmp/kf.err; echo "exit=$?"
```

With `/usr/bin` off the path, `clang` or `codesign` should be reported as
`KF-TOOLCHAIN-MISSING`, exit `3`, with an envelope. A traceback is a defect.

### Step 5 — Android from the Mac (only if the SDK is set up)

If `kivyforge doctor -p android` is green on this Mac:

```bash
cd examples/mobile/hello-android
kf build -p android --debug --json
```

Gradle's whole transcript must be in `/tmp/kf.err`; stdout must be only the
envelope, with artifacts `project` then `apk`. Otherwise skip and say so.

### Step 6 — report

Write findings to `docs/design/dev/build-package-output-mac-findings.md`: an
environment table, then each step's commands, exit codes and the relevant output
verbatim. Lead with any defect, especially from Step 2.

If you fix a defect, keep the fix and its test in a separate commit from the
findings, and add the scenario to the hermetic suite
(`tests/cli/test_build_package_json.py` or `test_build_package_failures.py`) so
it cannot regress on the Windows host.

Add a row to [`test-matrix.md`](test-matrix.md) §7 for this run (`local`, dated,
Host `macOS`).

### Rules of engagement

- Record what you **observed**. A skipped step is reported as skipped, with the
  reason.
- Do **not** commit generated example locks, or example `pyproject.toml` edits
  from Step 3c.
- Commit on `modernization-rfc`. **Do not push without asking.**

---

## Follow-up added 2026-09-17 — the compiled stdlib on macOS

Independent of the steps above; needs `7aab358f` or later. Roadmap item 9 now
byte-compiles the staged stdlib, and the Windows host measured it
(`import kivy`: 66 ms compiled against 276 ms source-only). **macOS is
unmeasured, and the signing interaction is macOS-only**, which is the part no
other host can check: the compile is placed before `codesign` precisely because
writing into a bundle afterwards invalidates what it sealed.

```bash
cd examples/desktop/dice-roller
kivyforge package -p macos                       # your usual signing config
APP=$(ls -d build/macos/*.app)
```

**1. The artifact ships compiled, with sources kept.** The stdlib keeps its
`.py` *and* gains `.pyc` (tracebacks and `inspect` need the sources); the app
payload stays `.pyc`-only:

```bash
PY="$APP/Contents/Resources/python"
find "$PY/lib" -name '*.py'  -not -path '*site-packages*' | wc -l    # expect many
find "$PY/lib" -name '*.pyc' -not -path '*site-packages*' | wc -l    # expect ~the same
find "$APP/Contents/Resources/app" -name '*.py' | wc -l              # expect 0
```

**2. The signature survives it — the macOS-specific question.**

```bash
codesign --verify --deep --strict --verbose=2 "$APP"
xcrun stapler validate "$APP"     # if this build was notarized
```

Then launch it (`"$APP/Contents/MacOS/"*` directly, not via `open`, so you see
stderr), quit, and re-run `codesign --verify`. It must still be valid, and the
`.pyc` count must be unchanged — the build's caches are sealed in, and
`PYTHONDONTWRITEBYTECODE` stops the launch adding more.

**3. Measure, min of 5, with the bundle's own interpreter:**

```bash
cd "$APP/Contents/Resources"
for i in 1 2 3 4 5; do
  PYTHONHOME="$PWD/python" PYTHONPATH="$PWD/app:$PWD/lib" \
  PYTHONDONTWRITEBYTECODE=1 \
  ./python/bin/python3 -X importtime -c 'import kivy' 2>&1 | tail -1
done
```

Take the cumulative figure for `kivy`, then delete the stdlib `__pycache__`
(`find "$PWD/python/lib" -name __pycache__ -not -path '*site-packages*' -exec rm -rf {} +`)
and repeat for the source-only number. **Re-package afterwards** so the example
is not left with a doctored, now-unsigned bundle.

**4. Record** in [`test-matrix.md`](test-matrix.md) §7 (Host `macOS`), and
replace §5.10's "not re-measured on macOS" line with the number.
