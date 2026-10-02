# Agent prompt — the Mac hardware passes

> **Run this on the Mac**, from the repo root, on `main`. Written 2026-09-30
> from the Windows host, after every checklist item that host can reach was
> recorded (PRs #36–#40).
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what is left, and why only the Mac can do it

[`hardware-checklist.toml`](hardware-checklist.toml) lists the checks that need
real hardware; `python scripts/hardware_pass.py list` groups them by what this
host can run, `show <id>` prints the exact commands and pass criteria, and
`record <id>` appends the dated row to [`test-matrix.md`](test-matrix.md) §7.
**`show` is the authority.** Where this prompt and `show` disagree, follow
`show` and say so in the report.

State on 2026-09-30:

| Item | Status | Notes |
|---|---|---|
| `desktop-linux`, `desktop-windows`, `windows-interactive`, `android-device`, `pi5-appimage` | recorded PASS | Windows host and WSL2 — nothing to do here |
| `desktop-macos` | **passed, not recorded** | The owner ran `verify-desktop-examples.sh -p macos --no-pause` on this Mac on 2026-09-30 and every example passed. Only the row is missing. |
| `ios-device` | to run | Last run 2026-09-27 (PR #20 validation) |
| `macos-notarize` | to run | Last evidence 2026-09-14 (`notarytool history`), never through the checklist |
| `windows-authenticode`, `store-play`, `store-appstore` | out of scope | Need credentials the owner does not hold |
| `ios-strip-source` | out of scope | Blocked on CPython 3.15.0 final |
| `pi4-appimage` | out of scope | No Pi 4 |

Two things changed since the Mac last ran these scripts:

- **The verify scripts now restore only a lock git tracks** (#35). An
  untracked `pylock.*.toml` left by an earlier run is overwritten by the fresh
  resolve instead of being put back. `hello-kivy` *tracks* `pylock.ios.toml`
  on purpose (see its `.gitignore`), so for the iOS pass the lock is still
  compared and restored.
- **`record` appends the §7 row only.** The "Last known result" column of the
  checklist table in `test-matrix.md` is maintained by hand and must be updated
  in the same commit.

---

## Prompt

You are finishing kivyforge's hardware checklist on a real Mac. Record what you
observe; do not mark a criterion as met without its output in front of you. If
a step fails, capture the full output, record the item as `fail` (or `blocked`
when a prerequisite is missing), and carry on with the independent items.

Some criteria are visual — a window on the Mac, an app on the iPhone. You
cannot see them. Ask the owner, and record only what they confirm.

### Rules

- **Never commit an edit made to an example to get a pass through.** The iOS
  item takes its Team ID from `KIVYFORGE_TEAM_ID`, not an edit (Step 2). If
  re-locking `hello-kivy` reports **lock drift**, diff and report it — do not
  commit the regenerated lock (`AGENTS.md`, "Committing").
- **Check every `record` note before committing.** A placeholder such as
  `<what you saw>` must never reach §7; that has happened once already.
- One branch for all rows, **ask the owner before pushing**, and do not open
  the PR — the owner opens and merges it from the Windows session.

### Step 0 — environment

```bash
git switch main && git pull --ff-only
source .venv/bin/activate && pip install -e ".[dev]"
git log --oneline -1                     # e2e2d421 or later
sw_vers; xcodebuild -version
kivyforge --version
python scripts/hardware_pass.py list
```

`list` should show `ios-device`, `macos-notarize` and `desktop-macos` under
"Runnable on this host". Note the Mac model (`sysctl -n hw.model`, or ask the
owner) for the `--device` strings below.

```bash
git switch -c hardware-pass-macos
```

### Step 1 — `desktop-macos`: record the owner's pass

Nothing to run. Confirm with the owner that all four examples (dice-roller,
notes, desktop-viewer, hello-native) passed and each window showed its UI, then:

```bash
python scripts/hardware_pass.py record desktop-macos --result pass \
  --device "<Mac model>, macOS <version>" \
  --note "verify-desktop-examples.sh -p macos --no-pause, run by the owner: dice-roller, notes, desktop-viewer and hello-native passed; each run and packaged app showed its UI."
```

If the owner reports anything other than a clean pass, record what they saw
instead.

### Step 2 — `ios-device`

```bash
python scripts/hardware_pass.py show ios-device
xcrun devicectl list devices
```

Pre-flight (the script's header explains each one):

1. Exactly one iPhone is listed as connected or available (paired). If an
   Apple Watch or a second phone is paired, use `--destination 'NAME'`.
2. The Apple ID in Xcode → Settings → Accounts belongs to the team that will
   sign. `examples/mobile/hello-kivy/pyproject.toml` commits `team_id = ""`;
   pass the owner's Team ID (Xcode → Settings → Accounts, or the earlier
   device-run findings) in `KIVYFORGE_TEAM_ID`. Do not edit `team_id`: the
   script re-locks, the edit changes the lock's `pyproject_sha256`, and the
   script then restores the committed lock, which the build refuses as stale.
3. The phone is **unlocked** when `run` launches the app. A locked phone fails
   late, after a successful install.

```bash
cd examples
KIVYFORGE_TEAM_ID=<team id> ./verify-ios-device.sh hello-kivy 2>&1 | tee /tmp/ios-pass.log
cd ..
git status --porcelain examples/mobile/hello-kivy      # must be empty
```

The `run` step is the visual check: it stays attached to the app's console
(`devicectl --console`) until the app exits. While it streams, ask the owner
whether the app opened on the phone and shows its label, then have them close
the app **from the app switcher** (swipe up and pause, then swipe the app's
card away) so `run` returns and the script continues to `package`. Going to
the Home Screen only suspends the app, and `run` keeps waiting. iOS often ends
a closed app with SIGKILL: `devicectl` prints "App terminated due to signal
9." and `run` exits 1. That is iOS behaviour, not a failure. So the script
checks only that the app launched (`devicectl` printed "Launched application
with ..."); it fails the run step if not, as on a locked phone. Once the app
launched, the script prints `run`'s exit status and does not count it: whether
the app worked is the owner's confirmation. Put the exit status and that
confirmation in the note. Ctrl+C also ends `run` (`Aborted!`), and the script
goes on.

Pass only if all of these hold:

- The script's build, launch and package steps succeed for `hello-kivy`
  (`+++ hello-kivy: OK (app launched; ...)`).
- The owner confirms the app opened on the phone and showed its label, and
  the console streamed Kivy's log, including `Start application main loop`
  (grep `/tmp/ios-pass.log`).

If the lock step reports `lock DRIFT` on `pylock.ios.toml`, the script restores
the committed lock; record the drift in the note and in your report, and leave
the lock alone.

```bash
python scripts/hardware_pass.py record ios-device --result pass \
  --device "<iPhone model>, iOS <version>" \
  --note "verify-ios-device.sh hello-kivy: build and package (development export) succeeded; app showed its label (confirmed by the owner); log reached 'Start application main loop'; run exited <status> after the owner closed the app from the app switcher (<devicectl's last line>). Xcode <version>."
```

### Step 3 — `macos-notarize`

```bash
python scripts/hardware_pass.py show macos-notarize
security find-identity -v -p codesigning       # the exact "Developer ID Application: ..." string
```

You also need a notarytool keychain profile name. Ask the owner; if none
exists, they create one with `xcrun notarytool store-credentials <profile>`
(interactive; it takes an Apple ID app-specific password, so the owner types
it, not you). Never put credentials in a command line or a file.

```bash
cd examples/desktop/dice-roller
kivyforge package -p macos \
  --signing-identity "Developer ID Application: <name> (<team>)" \
  --notarize --notary-profile <profile> 2>&1 | tee /tmp/notarize.log
spctl -a -vvv -t exec build/macos/*.app
xcrun stapler validate build/macos/*.app
cd ../../..
```

Notarization usually takes a few minutes; `package` waits for it.

Pass only if all of these hold:

- `package` reports the notarization accepted and the ticket stapled.
- `spctl` reports `accepted` with `source=Notarized Developer ID`.
- `stapler validate` reports `The validate action worked!`.

```bash
python scripts/hardware_pass.py record macos-notarize --result pass \
  --device "<Mac model>, macOS <version>" \
  --note "dice-roller: package --notarize accepted and stapled; spctl accepted (Notarized Developer ID); stapler validate worked."
```

If the identity or the profile is missing, record `--result blocked` with what
was missing, rather than `fail`.

### Step 4 — the table, the commit, the report

In `docs/design/dev/test-matrix.md`, update the "Last known result" column of
the checklist table for each item you recorded, in the style of the rows
already there, e.g.:

```
| `desktop-macos` | runnable | macOS | 2026-09-30: `verify-desktop-examples.sh` passed all four examples |
```

Keep the previous date where it adds something (see the `android-device` and
`pi5-appimage` rows).

```bash
git diff                                  # only test-matrix.md; no placeholders, no example edits
git add docs/design/dev/test-matrix.md
git commit -m "Record the macOS hardware passes"   # body: what ran, on what, and why each result
```

Ask the owner before `git push -u origin hardware-pass-macos`.

Then report, defects first:

1. Anything that failed or was blocked: the step, the command, the verbatim
   output, and what you think caused it.
2. Lock drift on `hello-kivy`, if any, with the diff.
3. Per item: result, device string, and the §7 row as committed.
4. The branch name and commit hash, and whether it was pushed.
