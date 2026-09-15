# Agent prompt — the macOS launcher cannot start a stripped `.app`

> **Run this on the Mac**, from the repo root of `modernization-rfc`. Written
> 2026-09-14 from the Linux (WSL2) host, where no part of the `.app` path can
> run.
>
> Point the agent at this file, or copy the "Prompt" section.
>
> Follows the shape of
> [`macos-ios-validation-prompt.md`](macos-ios-validation-prompt.md), whose run
> produced [`macos-ios-validation-findings.md`](macos-ios-validation-findings.md).
> This file exists because that run's own evidence contains an unnoticed defect.

## Background — a defect inferred from your own findings, not from a new run

The same bug was **found and fixed on Linux** on 2026-09-13 (see
[`test-matrix.md`](test-matrix.md) §7). The Linux `AppRun` exec'd
`usr/app/main.py`; `kivyforge package` applies `strip_source`, which deletes
`main.py` and leaves `main.pyc`; so every release AppImage died before Python
started, exit 2, `can't open file '.../usr/app/main.py'`. `build` and `run` were
unaffected because neither passes `release=True`, which is exactly why it
survived so long unnoticed.

`kivyforge/platforms/macos/launcher.py` has the identical shape:

```c
snprintf(script, sizeof(script), "%s/%s.py", app, ENTRY);
...
child[0] = py;
child[1] = script;
execv(py, child);
```

There is no `.pyc` fallback and the path is absolute, so neither the
`chdir(app)` above it nor `PYTHONPATH` can rescue it.

And unlike Linux, the precondition is already **recorded as observed** —
[`macos-ios-validation-findings.md`](macos-ios-validation-findings.md) Step 2:

| Location | `.py` | `.pyc` |
|---|---|---|
| `Contents/Resources/app` | **0** | 1 (`main.pyc`) |

`ENTRY` is `main`, so the launcher execs `Contents/Resources/app/main.py` — a
file that step counted as absent. The conclusion follows from the repo's own
log: **the notarized `Dice Roller.app` is very probably unlaunchable.**

It is stated as "very probably" on purpose. Nothing has launched it, so this is
an inference from two observed facts, not a result. Your Step 1 turns it into
one or kills it.

### Why nothing caught it

Every macOS check to date is static. Step 1 ran `codesign`, `stapler`, `spctl`,
`lipo`; Step 5 added `macos_app_problems` and ran it against the same bundle;
all green. None of them start the app. §3.2's macOS row still reads `none` in
the launch column, and §5 already carries this as an open item ("A
launcher-entry check on macOS, which neither desktop checker has"). The Linux
equivalent only fell out because `_apprun_target_problems` parses `AppRun` and
checks the target exists — a check the macOS side cannot copy directly, since
its launcher is a compiled Mach-O rather than a script.

The uncomfortable corollary: five `Accepted` notarization submissions attest to
a correctly signed bundle, and say nothing whatsoever about whether it runs.

### This is **not** the iOS 3.15 issue — do not merge the two

They are easy to conflate (same session, same findings file, same Apple
toolchain) and they are opposites:

- **iOS** pins `3.15.0b4`; there is no final CPython 3.15; `select_compiler`
  returns `None`; `package -p ios` degrades to **shipping source**. `main.py`
  is present in the `.ipa` (Step 6 confirms), so `main.m` finds its script.
  **iOS is unaffected — because its stripping does not happen.**
- **macOS** pins a final `3.13.14` (`examples/desktop/dice-roller/pyproject.toml`),
  takes the native staged-interpreter branch, and strips for real.
  **macOS is affected — because its stripping works.**

Findings-doc conclusion 3 ("macOS `strip_source` is real and correctly scoped")
is accurate about *scope* and is not being retracted. What it does not say, and
could not have said without a launch, is whether the correctly stripped bundle
starts.

---

## Prompt

You are fixing a launcher defect in kivyforge on the Mac. Base: `modernization-rfc`
at `91e8853b` or later. **Evidence first**: confirm the defect before changing
code, so the fix has a "before" to point at.

If `kivyforge/platforms/linux/launcher.py` already contains `-P -m {entry}`, the
Linux fix has landed and you are mirroring it. If it still names
`usr/app/{entry}.py`, it has not landed yet — that does not block you; the whole
fix is specified below.

### Step 0 — read before touching anything

Read [`test-matrix.md`](test-matrix.md) (§3.2, §5, §7, and the three rules at
the top) and [`macos-ios-validation-findings.md`](macos-ios-validation-findings.md)
Steps 2 and 5. Do not rely on this file's Background section for either.

### Step 1 — reproduce, and capture the failure verbatim

```bash
cd examples/desktop/dice-roller
APP=$(ls -d build/macos/*.app)          # note: the name contains a space
ls "$APP"/Contents/Resources/app/       # expect main.pyc, no main.py
"$APP"/Contents/MacOS/*                 # run in the foreground
```

Run the executable directly. Do **not** use `open` or Finder — they swallow
stderr, and the error text is the entire point.

Expected: a non-zero exit with `can't open file '.../Resources/app/main.py'`, or
`kivyforge launcher: execv`. Record it verbatim.

**If it launches instead, stop and report that.** The inference is then wrong
and the rest of this prompt is void — find out why (an unstripped rebuild since
Step 2? a `.py` that came back?) before touching the launcher. A negative result
here is a genuinely useful outcome, not a failed errand.

If `build/macos/` holds an unstripped bundle (`main.py` present), it came from
`build`/`run`; re-run `kivyforge package -p macos` to get the release shape.
Ad-hoc signing is enough to reproduce — stripping is driven by `release=True`,
not by signing tier, so no identity or notarization is needed for Step 1.

### Step 2 — the fix

In `kivyforge/platforms/macos/launcher.py`, exec the entry point as a **module**
instead of a path. Three edits to `_SOURCE`:

1. Drop `script[PATH_MAX]` from the declaration on the `char py[PATH_MAX], ...`
   line. Leaving it triggers an unused-variable warning under the existing
   `-Wall`.
2. Delete the `snprintf(script, ...)` line.
3. Replace the argv assembly:

```c
    char **child = (char **)malloc(sizeof(char *) * (argc + 4));
    if (child == NULL) return 71;
    child[0] = py;
    child[1] = "-P";
    child[2] = "-m";
    child[3] = (char *)ENTRY;
    for (int i = 1; i < argc; i++) child[i + 3] = argv[i];
    child[argc + 3] = NULL;
    execv(py, child);
```

The `(char *)` cast on `ENTRY` is needed because it is `const char *` and
`execv` takes `char *const []`; without it `-Wall` complains.

Why this works: `-m` goes through the import system, which loads a sourceless
`.pyc` in the legacy (non-`__pycache__`) layout exactly as happily as a `.py`,
so the launcher stops caring what shape the payload is in. `PYTHONPATH` is
already set to `Resources/app:Resources/lib` immediately above, so `main`
resolves.

**Keep `chdir(app)`** — apps may load resources relative to it.

On `-P`: it suppresses Python putting the working directory on `sys.path` for
`-m`. Be aware this is weaker-stakes here than on Linux, and say so in the
comment rather than overselling it: because macOS `chdir`s into `app` first, the
directory `-m` would add is the one you want anyway. It is defensive, it keeps
the two launchers symmetric, and it means imports resolve from `PYTHONPATH`
rather than depending on the `chdir` — but it is not load-bearing the way it is
in the Linux `AppRun`, which has no `chdir`. `-P` needs CPython >= 3.11; macOS
ships 3.13.14 here.

Leave the `entry_point.isidentifier()` validator alone. `-m` would now make
dotted entry points workable (Linux allows them), but that is scope creep for
this fix.

### Step 3 — tests, mirroring the Linux ones

In `tests/platforms/macos/test_plist_launcher.py`:

- `TestLauncherSource` — add the regression guard, the analog of Linux's
  `test_the_launcher_never_names_a_source_file`: assert `render_launcher_source("main")`
  contains `"-P"`, `"-m"`, and `ENTRY` in the argv, and contains **no** `.py`
  path. Assert the absence, not just the presence — the presence of `-m` would
  not have caught a stray leftover `snprintf`.
- `TestLauncherCompile` (the real-clang, macOS-only class) — extend the pattern
  already in `test_child_sees_bin_first_on_path`: build a real launcher, plant a
  fake `Resources/python/bin/python3` shell script that prints `"$@"`, and
  assert the argv it receives is `-P -m main` with no `.py` path in it. This is
  the closest thing to an end-to-end proof that runs in CI.

Then the full hermetic suite (unfiltered `pytest`, matching the `unit_tests`
job) plus `ruff check` and `ruff format --check`.

### Step 4 — the real proof, and macOS's first T4

```bash
cd examples/desktop/dice-roller
kivyforge package -p macos
ls build/macos/*.app/Contents/Resources/app/    # main.pyc only — still stripped
APP=$(ls -d build/macos/*.app); "$APP"/Contents/MacOS/*
```

The window should open. That is macOS's **first launch evidence of any kind**,
and specifically of a stripped bundle — §3.2's launch column can move off
`none`.

Then re-run the T3 driver against the rebuilt bundle to confirm the fix broke
nothing structural:

```bash
pytest tests/platforms/macos/test_app_artifact.py \
  --macos-app "$APP" --macos-arch arm64 --macos-stripped
```

The launcher binary changed, so the bundle needs re-signing (the build does this)
and, if you want notarized evidence again, re-notarizing. Not required for the
fix — but worth noting that the five prior `Accepted` submissions covered a
bundle that could not start.

### Step 5 — optional: close §5's launcher-entry gap statically

§5 wants a launcher-entry check in `macos_app_problems`. macOS cannot copy
Linux's approach (`_apprun_target_problems` parses the shell `AppRun`; the Mach-O
stub is opaque). The cheap version: add a `--macos-entry` conftest option
(default `main`) and assert the payload provides that module — `<entry>.pyc`,
`<entry>.py`, or `<entry>/__init__.pyc`. Post-fix that is a weaker check than it
was pre-fix, which is the point: the failure mode it guards has been designed
out, and the `TestLauncherSource` guard in Step 3 is what actually holds the line.
Skip it if it feels like ceremony; record the decision either way.

### Step 6 — update the record

1. **`test-matrix.md` §7** — a dated row: the defect, the reproduction from Step 1,
   the fix, and the Step 4 launch.
2. **`test-matrix.md` §3.2**, macOS row — launch column `none` → `local only`.
3. **`test-matrix.md` §5** — tick the launcher-entry item, or narrow it per Step 5.
4. **`test-matrix.md` "Known-unverified"** — the macOS launcher bullet becomes a
   resolved finding; it should stop predicting and start reporting.
5. **`macos-ios-validation-findings.md` conclusion 3** — qualify rather than
   retract. Scope was correct; what was missing was that nothing had started the
   stripped bundle. Link here.

Write a findings file if the run turns up anything the prompt did not predict.

## Acceptance

- [ ] Step 1 failure captured verbatim (or the inference refuted, and reported).
- [ ] Launcher execs `-P -m <entry>`; no `.py` path remains in `_SOURCE`.
- [ ] `clang` compiles it warning-free under `-Wall`.
- [ ] Regression test asserts the *absence* of a source path.
- [ ] Real-clang test asserts the argv the interpreter actually receives.
- [ ] Full hermetic suite + lint clean.
- [ ] A stripped, repackaged `Dice Roller.app` launches and renders.
- [ ] T3 driver still passes against the rebuilt bundle.
- [ ] §7, §3.2, §5, "Known-unverified", and findings conclusion 3 all updated.

## Do not

- **Do not use `-I`.** It implies `-E`, which discards the `PYTHONHOME` and
  `PYTHONPATH` the launcher sets two lines earlier. `-P` is the narrow flag.
- **Do not add a `.py`/`.pyc` fallback in the C.** It reintroduces the coupling
  between launcher and payload shape that caused this.
- **Do not "fix" it by disabling `strip_source`.** Stripping is working
  correctly; the launcher is what is wrong.
- **Do not treat this as the iOS 3.15 problem.** Different platform, opposite
  cause. See Background.
- **Do not commit `examples/desktop/dice-roller/pylock.macos.toml`.** Desktop
  example locks are gitignored on purpose
  ([`common/03-lockfile-concept.md`](../common/03-lockfile-concept.md)
  §"Example-repo lock policy"); the findings file already records one false
  alarm on exactly this point.
- **Do not hardcode a personal `team_id`** into any shared example, per the same
  file's Step 6 note.
