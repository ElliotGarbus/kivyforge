# Agent prompt — iOS T3 artifact checks (roadmap item 5, test-matrix §5.1)

> **Run this on the Mac**, from the repo root of `main`. Written 2026-09-23
> from the Windows host, where none of the validation can run — no iOS `.app`
> can be produced there, and `codesign`/`lipo` do not exist.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what exists, what's missing

`tests/artifact_checks.py` holds T3 checks as **pure functions returning lists
of problem strings**, so one run reports every fault and each check is
unit-testable against a synthetic tree with no build. Four platforms have one:

| Platform | Function | Driver |
|---|---|---|
| Android | `android_apk_problems` | `tests/platforms/android/test_apk_artifact.py` |
| macOS | `macos_app_problems` | `tests/platforms/macos/test_app_artifact.py` |
| Linux | `linux_appdir_problems` | `tests/platforms/linux/test_appimage_artifact.py` |
| Windows | `windows_onedir_problems` | `tests/platforms/windows/test_onedir_artifact.py` |

**iOS has none.** It is the only platform with no T3 tier at all — §3.2 shows
T2 and T4 covered by `ios_simulator` and T3 blank. That job builds a real
`.app` on `macos-latest` on every push, so both the artifact and the place to
wire the check already exist.

`macos_app_problems` is the closest model and shares `machotools`, but **an
iOS `.app` is not shaped like a macOS one** — no `Contents/`, a flatter
layout, a different set of required `Info.plist` keys. Step 0 exists because
the bundle layout must be read off a real build rather than assumed.

### Scope constraint — read this before deciding what to check

**iOS `strip_source` is currently unreachable, so the stripping and
`.pyc`-magic checks cannot be written honestly yet.** Every iOS example pins
CPython `3.15.0b4`; `package -p ios` degrades to shipping source with "no
final CPython 3.15 found" (§7, 2026-09-14). There is no "pin to an
already-final minor" escape the way desktop has, because python.org's iOS
`Python.xcframework` artifact only exists from `3.15.0b1` onward.

That matters because those are the highest-value checks on the other four
platforms — they are what caught roadmap item 1, the Linux `AppRun` defect and
the macOS launcher defect. **Do not write a `stripped=True` path you cannot
exercise.** Either omit it, or add it with an explicit "never validated
against a real stripped bundle" note and leave the parameter unused by the
driver. Say which you chose and why in the findings.

What *is* checkable today, and what this prompt asks for:

- required bundle entries (the app is launchable at all)
- Mach-O arch across the bundle, and no host-arch binary leaked in
- `Info.plist` contents vs. what `pyproject.toml` declared
- the code signature verifies (simulator builds are ad-hoc signed)

## Prompt

Work through the steps in order. Each builds on the last. Record verbatim
output as you go — the findings doc is the deliverable, not just the code.

### Step 0 — baseline, and read the real bundle layout

This is the step that cannot be done from Windows and that everything after
depends on.

```bash
cd examples/mobile/hello-kivy
kivyforge doctor -p ios
kivyforge build -p ios --simulator
```

Then find the built `.app` and **dump its structure**:

```bash
find <path-to>.app -maxdepth 2 | sort
plutil -p <path-to>.app/Info.plist
```

Capture both verbatim. Note specifically: where the executable lives, where
the Python runtime and the app payload live, and which `Info.plist` keys are
present. Write these into the findings doc — the next maintainer should not
have to rebuild to learn the layout.

### Step 1 — the checker function

Add `ios_app_problems` to `tests/artifact_checks.py`, in the same shape as its
four siblings: pure, returns `list[str]`, no assertions, no subprocess.

Reuse rather than reinvent:

- `machotools.read_macho_cpu_type` / `cpu_type_name` for arch — do **not**
  write a second Mach-O reader or shell out to `lipo`
- the `CPU_TYPE_ARM64` / `CPU_TYPE_X86_64` constants already imported there
- `macos_expected_plist`'s approach for the config comparison: derive the
  expectation by calling the **production** plist builder and dropping the
  keys a config-only caller cannot know, so the expectation cannot drift from
  what the build actually writes

Cover: required entries, arch (plus a stray-arch sweep of the whole bundle),
and `Info.plist` vs. config. Keep every path spelled with `as_posix()`, per
the module docstring.

### Step 2 — hermetic tests

In `tests/test_artifact_checks.py`, following the existing per-platform
sections. Build synthetic `.app` trees with a helper like `_macos_app`'s.
Every check gets a test that it **fires**, not only one that it passes — a
checker validated only against good input proves nothing about its ability to
catch, which is the lesson of item 1.

### Step 3 — CLI options and driver

`--ios-app`, `--ios-arch` (default `arm64`), and `--ios-project` in
`tests/conftest.py`, matching the naming of the other four. Then
`tests/platforms/ios/test_app_artifact.py`, mirroring
`tests/platforms/macos/test_app_artifact.py`: skips without `--ios-app`, and
a separate test for the code signature.

`--ios-project` is what turns the `Info.plist` check from a shape check into a
comparison. Note the macOS precedent: `macos_app_problems` carried plist
expectations for a week that **no driver ever passed**, so the comparison had
never run. Wire it, do not just accept it.

### Step 4 — validate against the real `.app`, including negatives

Point the driver at the Step 0 build. Then prove it can fail:

- claim the wrong arch (`--ios-arch x86_64`) and confirm it names the real
  Mach-O binaries
- edit a value in the built `Info.plist` (not the fixture's config) and
  confirm the comparison catches it — on macOS this also broke `codesign`,
  since the signature seals `Info.plist`; report whether iOS behaves the same
- rebuild clean afterwards

### Step 5 — wire it into `ios_simulator`

Add a T3 step to that job, after the build and before or after the launch.
It already produces the artifact; this is wiring plus a `pytest` invocation.
Confirm the step's pytest prints `.` and not `s` — a green job containing a
skipped assertion is the failure this tier exists to remove.

### Step 6 — full suite, docs, then report

```bash
pytest
ruff check kivyforge tests && ruff format --check kivyforge tests
pyright
```

Update: §5.1 (iOS box), §3.1 (job's Serves column), §3.2 (iOS T3 cells), and
add a §7 results row. Correct roadmap item 5's remaining-work list — an iOS
T3 harness is named there as outstanding.

Then write `docs/design/dev/ios-t3-checks-findings.md`: environment table,
the Step 0 layout dump, per-step commands and verbatim output, **defects
first**, and an explicit statement of what the harness does *not* cover
(the stripping path, per the scope constraint above).

### Rules of engagement

- Record what you **observed**, not what you expect. If a step fails, capture
  the full error and say so plainly rather than working around it.
- The `Info.plist` edit in Step 4 is temporary and must not be committed.
- Do not commit a regenerated `pylock.ios.toml`; `hello-kivy` is an
  on-device gate example whose lock is evidence
  (`common/03-lockfile-concept.md` §"Example-repo lock policy"). If it would
  change, diff and report instead.
- If the scope constraint turns out to be stale — if a final 3.15 iOS
  xcframework now exists — say so, and scope the stripping checks in rather
  than around. Check; do not assume this file is still current.
- Work on a branch. **Do not push without asking.**
