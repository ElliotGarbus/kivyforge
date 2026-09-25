# Agent prompt — end-user docs and provisioning-profile fix, on the Mac

> **Run this on the Mac**, from the repo root. Written 2026-09-24 from the
> Windows host, where none of it can run.
>
> Point the agent at this file, or copy the "Prompt" section. Results go in
> `mac-docs-and-provisioning-findings.md` beside it, in the shape of
> [`macos-ios-validation-findings.md`](macos-ios-validation-findings.md):
> environment table, per-step commands and verbatim output, defects first.

## Background — what changed, and what only a Mac can prove

Four changes landed together, all unit-tested on Windows, none exercised on a
real Apple toolchain:

1. **`[tool.kivy.ios.signing].provisioning_profile` was read two incompatible
   ways.** Xcode received it as a profile *name or UUID* (the documented form);
   `doctor` and the entitlements pre-flight treated it as a *file path*. So the
   documented form made `doctor` FAIL and silently skipped the entitlements
   check, and a path passed `doctor` and then failed `xcodebuild`. Now:
   - a name or UUID is looked up among installed profiles
     (`~/Library/Developer/Xcode/UserData/Provisioning Profiles`, then
     `~/Library/MobileDevice/Provisioning Profiles`; UUID match first, then
     `Name`, newest file among duplicate names);
   - a value ending in `.mobileprovision` is a path; kivyforge reads the file
     and passes **its UUID** to Xcode as `PROVISIONING_PROFILE_SPECIFIER`, and
     `doctor` WARNs if that profile is not installed.
   Code: `kivyforge/platforms/ios/entitlements.py`, `buildsettings.py`,
   `doctor.py`. Tests use fake profile files; **no real profile has been read.**
2. **`--arch` now accepts `aarch64`** on `build`/`package` (Linux). The shared
   Choice reaches iOS too, so iOS now rejects `--arch aarch64` with a clear
   message instead of deriving a bogus platform tag.
3. **`pip` is a runtime dependency** (`pip>=25.1`), because `uv tool install`
   environments ship without pip and every `lock` failed there. Verified on
   Windows only.
4. **The end-user docs site** (`docs/guides/`, MkDocs Material). The iOS and
   macOS pages were checked against code, but several claims were never
   walked on a Mac — listed in Step 5.

Read [`test-matrix.md`](test-matrix.md) §3.2, §5, §6 and §7 before starting.

---

## Prompt

You are validating kivyforge changes on the Mac. Work through the steps in
order. Record the actual output of each check — do not summarise a step as
passing without the evidence in front of you. If a step fails, capture the full
error and continue with the independent steps. **Report defects first.** Do not
fix code in this run; findings only, unless a fix is a one-line typo.

Never paste secrets (keystore passwords, notary credentials, full provisioning
profile contents) into the findings. Team IDs and profile *names* are fine.

### Step 0 — environment, as evidence

```bash
git pull
git log -1 --oneline
sw_vers; xcodebuild -version; xcode-select -p
.venv/bin/kivyforge --version; .venv/bin/python -V; .venv/bin/python -m pip -V
security find-identity -v -p codesigning
ls ~/Library/Developer/Xcode/UserData/Provisioning\ Profiles/ 2>/dev/null | wc -l
ls ~/Library/MobileDevice/Provisioning\ Profiles/ 2>/dev/null | wc -l
```

For one installed profile you intend to use, record its `Name` and `UUID`
(not the whole plist):

```bash
P=~/Library/Developer/Xcode/UserData/Provisioning\ Profiles/SOME_FILE.mobileprovision
security cms -D -i "$P" | plutil -extract Name raw -
security cms -D -i "$P" | plutil -extract UUID raw -
```

Replace `SOME_FILE` with a real file name. If the `UserData` directory is
empty, use the `MobileDevice` one and say so.

### Step 1 — `provisioning_profile` by name, UUID, and path

Use `examples/mobile/hello-kivy` (its lock is tracked on purpose; **do not
commit a re-locked `pylock.ios.toml`** — diff and report instead). Work on a
scratch copy so the example's `pyproject.toml` stays clean:

```bash
rm -rf /tmp/pp && cp -R examples/mobile/hello-kivy /tmp/pp && cd /tmp/pp
```

For each of the four values below, set
`[tool.kivy.ios.signing].provisioning_profile`, run `kivyforge lock -p ios`
(any edit makes the lock stale), then:

```bash
kivyforge doctor -p ios --json | python3 -c "import json,sys; d=json.load(sys.stdin); [print(c) for c in d['data']['checks'] if 'rovision' in c['name'] or 'ntitlement' in c['name']]"
kivyforge build -p ios --device
grep PROVISIONING_PROFILE_SPECIFIER hello-kivy-ios/*.xcodeproj/project.pbxproj | sort -u
```

(If the `--json` shape differs, print the whole `data` and say so.)

| Case | Value | Expected `doctor` | Expected specifier in pbxproj |
|---|---|---|---|
| A | the profile's `Name` | PASS "(installed)" | the name, verbatim |
| B | the profile's `UUID` | PASS | the UUID |
| C | a copy of the file in the project: `cp "$P" ./dev.mobileprovision`, value `dev.mobileprovision` | PASS (it is installed) | **the UUID**, not the path |
| D | `Nobody At All` | FAIL "no installed profile has the name or UUID" | the string verbatim |

Also run case C with `auto_signing = false` and a matching `identity`, since a
pinned profile only really matters under manual signing. Record whether the
device build signs and installs. A device must be attached for install; if
none is, record that and stop at the build.

**Case E — path to a profile that is not installed.** Take a profile that is
*not* in either directory (download one from developer.apple.com without
double-clicking it, or temporarily move an installed one out and restore it
afterwards — say which). Expected: `doctor` WARNs "is not installed" with a
"double-click" hint.

### Step 2 — the entitlements pre-flight now fires for a pinned name

The bug hid this check for anyone following the docs. In `/tmp/pp`, pin the
profile **by name** (case A), set `auto_signing = false`, and add an
entitlement the profile does *not* grant, e.g.:

```toml
[tool.kivy.ios.entitlements]
"com.apple.developer.healthkit" = true
```

Re-lock, then:

```bash
kivyforge doctor -p ios
kivyforge build -p ios --device; echo "exit=$?"
```

Expected: `doctor` "Entitlements vs. profile" **FAIL** naming the key and the
App ID; `build --device` stops **before** `xcodebuild` with the "not granted by
the provisioning profile" message. Then flip `auto_signing = true`: expect a
WARN and the build proceeding (Xcode may or may not register the capability —
record which).

### Step 3 — `--arch aarch64` on iOS

```bash
cd examples/mobile/hello-kivy
kivyforge build -p ios --simulator --arch aarch64; echo "exit=$?"
kivyforge build -p ios --simulator --arch arm64;   echo "exit=$?"
```

Expected: the first fails with "is not an iOS simulator arch" and no
collection; the second behaves as before.

### Step 4 — install paths (pip present)

In throwaway locations, never the repo's `.venv`:

```bash
# uv
UV_TOOL_DIR=/tmp/uvt UV_TOOL_BIN_DIR=/tmp/uvb uv tool install "$PWD"
/tmp/uvt/kivyforge/bin/python -m pip --version
# pipx (the docs claim pipx environments have pip; never verified)
PIPX_HOME=/tmp/px PIPX_BIN_DIR=/tmp/pxb pipx install "$PWD"
/tmp/px/venvs/kivyforge/bin/python -m pip --version
```

Then, from a scratch copy of `examples/desktop/dice-roller` with its
`[tool.kivy.macos.signing]` table removed, run `lock -p macos` with each
installed `kivyforge` and record `ok`. Clean up `/tmp/uvt /tmp/uvb /tmp/px
/tmp/pxb` afterwards.

### Step 5 — walk the Mac-side docs as a reader

Serve the site (`pip install -e ".[docs]" && mkdocs serve`) or read the
Markdown under `docs/guides/`. For each page, follow it literally on a clean
scratch copy and record every command that fails, every output path that is
wrong, and every step you had to improvise:

- `get-started/quickstart-ios.md` — end to end on the simulator, including the
  Xcode setup steps (`xcode-select --switch`, `xcodebuild -license accept`).
  Does `run` stream the app's console as the page says?
- `get-started/quickstart-desktop.md`, the macOS path — including the new step
  that deletes `[tool.kivy.macos.signing]` from dice-roller before locking.
  Is the stated output path `build/macos/Dice Roller.app` correct?
- `guides/ios/run.md` — `run -p ios --device` via `devicectl` (device needed),
  `--list-devices`, `--destination`.
- `guides/macos/signing.md` — its **Verify** section (`codesign`, `spctl`,
  `xcrun stapler validate`) against a Developer-ID-signed, notarized build.
- `guides/macos/dmg.md` — the do-it-yourself `hdiutil` procedure: does the
  resulting DMG mount, show the app and an Applications link, and (if you sign
  and notarize it as the page describes) pass `spctl -a -t open
  --context context:primary-signature`?
- `guides/ios/signing.md` — the `package -p ios` path and the stated `.ipa`
  location.

### Step 6 — report

Write `docs/design/dev/mac-docs-and-provisioning-findings.md`:

1. Environment table.
2. **Defects**, each with the command, verbatim output, and the page or source
   file it contradicts.
3. Per step: commands and verbatim output (trim long build logs to the
   relevant lines; keep every error in full).
4. Doc corrections as a list of page + wrong text + what is true.

Then add a dated entry to [`test-matrix.md`](test-matrix.md) §7 for what ran,
and commit **only** the findings doc and the test-matrix entry. Ask before
pushing.
