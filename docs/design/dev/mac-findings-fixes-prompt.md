# Agent prompt — fixes for the Mac docs and provisioning findings, on the Mac

> **Run this on the Mac**, from the repo root. Written 2026-09-24 from the
> Windows host, where none of it can run.
>
> Point the agent at this file, or copy the "Prompt" section. Results go in
> `mac-findings-fixes-findings.md` beside it, in the shape of
> [`mac-docs-and-provisioning-findings.md`](mac-docs-and-provisioning-findings.md):
> environment table, per-step commands and verbatim output, defects first.

## Background — what changed, and what only a Mac can prove

[`mac-docs-and-provisioning-findings.md`](mac-docs-and-provisioning-findings.md)
reported five defects. All five are fixed and unit-tested on Windows; none of
the fixes has touched a real Apple toolchain.

1. **`run -p ios` streams the app console.** The launch no longer goes through
   `run_command` (captured output, `stdin=DEVNULL`) but through
   `run_foreground` (`platforms/ios/xcode/runner.py`), which inherits the
   terminal. The simulator argv is unchanged (`simctl launch --console-pty`).
   The device argv **gained `--console`**
   (`devicectl device process launch --console --device ID BUNDLE`), which is
   believed to attach to the app's stdio and wait for exit. That flag has never
   been run.
2. **A pinned profile under `auto_signing = true` stops before `xcodebuild`.**
   `preflight_profile` (`platforms/ios/entitlements.py`) raises for device and
   release builds, `run --device`, and `package`; `doctor`'s Provisioning
   profile check FAILs. `KF-ENTITLEMENTS-UNGRANTED` is retired.
3. **An Xcode-managed profile under manual signing stops before `xcodebuild`.**
   kivyforge now reads `IsXcodeManaged` from the profile. Same four call sites,
   same `doctor` check.
4. **iOS `--arch` suggests `arm64` only**, and `WheelSelectionError` is
   classified (exit 1, with a `--json` envelope) instead of a traceback. An
   Intel host building for the simulator fails before collecting, exit 3.
5. **The macOS `.app` (and Linux AppDir) get `mkdir`'s mode**, not `mkdtemp`'s
   `0700` (`kivyforge/bundle/workdir.py`).

Also changed: `package -p ios` now runs the entitlements check that only
`build` ran before.

Read [`test-matrix.md`](test-matrix.md) §3.2, §5, §6 and §7 before starting.

---

## Prompt

You are validating kivyforge fixes on the Mac. Work through the steps in order.
Record the actual output of each check — do not summarise a step as passing
without the evidence in front of you. If a step fails, capture the full error
and continue with the independent steps. **Report defects first.** Do not fix
code in this run; findings only, unless a fix is a one-line typo.

Never paste secrets (keystore passwords, notary credentials, full provisioning
profile contents) into the findings. Team IDs and profile *names* are fine.

### Step 0 — environment, as evidence

```bash
git pull
git log -1 --oneline
sw_vers; xcodebuild -version; xcode-select -p
.venv/bin/kivyforge --version; .venv/bin/python -V
xcrun devicectl list devices
ls ~/Library/Developer/Xcode/UserData/Provisioning\ Profiles/ 2>/dev/null | wc -l
```

For each installed profile you use, record its `Name`, `UUID`, and
`IsXcodeManaged` (not the whole plist):

```bash
P=~/Library/Developer/Xcode/UserData/Provisioning\ Profiles/SOME_FILE.mobileprovision
for k in Name UUID IsXcodeManaged; do security cms -D -i "$P" | plutil -extract $k raw -; done
```

Replace `SOME_FILE` with a real file name.

### Step 1 — `run -p ios` streams the console

In `examples/mobile/hello-kivy`, in a real terminal (or under a pty, as the
findings did — say which):

```bash
kivyforge build -p ios --simulator
kivyforge run -p ios --simulator --no-build      # let it run ~15 s, then Ctrl+C
echo "exit=$?"
```

Expected: after `Launching org.kivy.hello-kivy ...`, the app's Kivy log lines
(`[INFO   ] [Kivy        ] v3.0...`) appear live, without waiting for the app
to exit. Record the first ~10 lines, what Ctrl+C prints, the exit status, and
whether the app is still running in the Simulator afterwards.

Then the device flag, which needs no device:

```bash
xcrun devicectl device process launch --help | grep -n -A2 -- --console
```

Expected: `--console` is listed. **If it is not, that is a defect** — record
the help text for the options that attach to output. If a device is paired and
available, also run `kivyforge run -p ios --device` and record whether the
console streams and what Ctrl+C does. If none is, say so.

### Step 2 — pinned profiles Xcode refuses

Work on a scratch copy so the example stays clean; **do not commit a re-locked
`pylock.ios.toml`**:

```bash
rm -rf /tmp/pf && cp -R examples/mobile/hello-kivy /tmp/pf && cd /tmp/pf
```

After each edit to `pyproject.toml`, run `kivyforge lock -p ios`, then:

```bash
kivyforge doctor -p ios --json | python3 -c "import json,sys; d=json.load(sys.stdin); [print(c) for c in d['data']['checks'] if 'rovision' in c['name'] or 'ntitlement' in c['name']]"
kivyforge build -p ios --device 2>&1 | tee /tmp/pf.log; echo "exit=${PIPESTATUS[0]}"
grep -c "xcodebuild build" /tmp/pf.log
```

| Case | `[tool.kivy.ios.signing]` | Expected `doctor` | Expected `build --device` |
|---|---|---|---|
| F | `provisioning_profile` = an installed profile's name, `auto_signing = true` | Provisioning profile **FAIL** "is pinned, but auto_signing is on" | exit 1 "auto_signing is on", **0** `xcodebuild` lines |
| G | same name (Xcode-managed), `auto_signing = false` | **FAIL** "is an Xcode-managed profile" | exit 1 "is managed by Xcode", 0 `xcodebuild` lines |
| H | a manually created profile (see below), `auto_signing = false` | PASS | signs; installs if a device is available |
| I | no `provisioning_profile`, `auto_signing = true` | PASS "not set" | as before (automatic signing) |

Case H needs a profile that is not Xcode-managed: create an iOS App
Development profile for the example's App ID at developer.apple.com, download
it, and double-click it. If you cannot, record that and skip H — it is the
only case that proves a pinned profile signs at all.

Also, with case G's settings, run `kivyforge build -p ios --device --json` and
record `exit_code`, `ok`, `diagnostics[].code`, and `data.artifacts`.

**Package runs the entitlements check.** With case H's settings (or G's, if H
was skipped — then expect G's refusal instead), add an entitlement the profile
does not grant, re-lock, and run:

```bash
kivyforge package -p ios --export-method development; echo "exit=$?"
```

Expected (H): the "not granted by the provisioning profile" error, exit 1, no
`xcodebuild archive` line.

### Step 3 — iOS `--arch`

```bash
cd examples/mobile/hello-kivy
kivyforge build -p ios --simulator --arch aarch64; echo "exit=$?"
kivyforge build -p ios --simulator --arch x86_64;  echo "exit=$?"
kivyforge build -p ios --simulator --arch x86_64 --json; echo "exit=$?"
kivyforge build -p ios --simulator --arch arm64;   echo "exit=$?"
```

Expected: the first three fail with "is not an iOS simulator arch", suggest
`--arch arm64` only (no `x86_64`), print no `Collecting artifacts` line and no
traceback; the `--json` one prints one envelope with `ok: false`. The last
builds as before.

### Step 4 — bundle permissions

On a scratch `examples/desktop/dice-roller` with `[tool.kivy.macos.signing]`
removed:

```bash
umask
kivyforge build -p macos
stat -f "%Sp %N" "build/macos/Dice Roller.app" "build/macos/Dice Roller.app/Contents"
kivyforge package -p macos
stat -f "%Sp %N" "build/macos/Dice Roller.app"
```

Expected under umask `022`: `drwxr-xr-x` for both, before and after `package`.
If a second user account is available, open the app from it after copying it
to `/Applications`; otherwise say it was not tried.

### Step 5 — the corrected docs

Read, and follow where a command is given:

- `docs/guides/guides/ios/signing.md` — the "Pinning a profile requires manual
  signing" warning and the Entitlements section.
- `docs/guides/reference/pyproject/ios.md` — the `provisioning_profile` row and
  note.
- `docs/guides/guides/macos/signing.md` — the new `codesign --verify` step in
  Verify, and the `security unlock-keychain` step under
  `errSecInternalComponent`.
- `docs/guides/get-started/quickstart-ios.md` — "`run` then streams the app's
  console output", now that Step 1 has tested it.

Record every statement that does not match what you observed.

### Step 6 — report

Write `docs/design/dev/mac-findings-fixes-findings.md`:

1. Environment table.
2. **Defects**, each with the command, verbatim output, and the page or source
   file it contradicts.
3. Per step: commands and verbatim output (trim long build logs to the
   relevant lines; keep every error in full).
4. Doc corrections as a list of page + wrong text + what is true.

Then add a dated entry to [`test-matrix.md`](test-matrix.md) §7 for what ran,
and commit **only** the findings doc and the test-matrix entry. Ask before
pushing.
