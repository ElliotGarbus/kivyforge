# Agent prompt — `exclude` applied during resolution, on iOS (#190)

> **Run this on a Mac with Xcode**, from a clone on branch
> `exclude-during-resolve` (or `main` once it is merged). `lock -p ios` runs
> only on macOS, so the Windows host checked the fix on Android only
> (`test-matrix.md` §7, 2026-10-26). Written 2026-10-26.

## Background

[#190](https://github.com/ElliotGarbus/kivyforge/issues/190): with KivyMD 2.0.0
as a dependency, `exclude = ["pycairo", ...]` under `[tool.kivy.ios]` did not
stop the lock from trying to install `pycairo`. KivyMD needs `materialshapes`,
which needs `pycairo` and `pillow`; `pycairo` publishes no iOS wheel.

The cause: the lock builders let pip resolve the whole graph and dropped
excluded packages *afterwards*, so pip failed on `pycairo` before the filter
ran. The fix (`kivyforge/lock/_pip_shim.py`, `_install_exclude_filter`) wraps
pip's `PipProvider.get_dependencies` so a dependency on an excluded name is
never followed. A side effect: what only an excluded package needed leaves the
lock with it.

On Windows, against Android, the old code failed with "no wheel for 'pillow'"
although `pillow` was excluded, and the new code locked 8 packages with neither
`pillow` nor `pycairo`. iOS goes through the same shim, but has not been run.

Note: the issue's config lists `materialshape`; the package is `materialshapes`,
so that entry matches nothing either way. Do not "fix" it in the scratch app;
it is not part of this test.

## Prompt

You are checking that `kivyforge lock -p ios` honours `exclude` during
resolution. **Record what you observe**, verbatim. Read `AGENTS.md` first: its
rules on the results log apply. Change no code unless a step fails; if one does,
report it first.

### Step 0 — environment

```bash
sw_vers; xcodebuild -version; python3 --version; python3 -m pip --version
git branch --show-current; git log --oneline -1
pip install -e ".[dev]"
```

### Step 1 — the scratch app

Outside the repo, so nothing in the tree changes:

```bash
mkdir -p /tmp/kf190/src && cd /tmp/kf190
cat > pyproject.toml <<'EOF'
[project]
name = "kf190"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = ["kivy>=3.0.0.dev0", "kivymd==2.0.0"]
EOF
printf 'from kivymd.app import MDApp\n\nMDApp().run()\n' > src/main.py
kivyforge init -p ios
```

`init` seeds the current `[tool.kivy.ios]` defaults, including an `exclude`
block for Kivy's own optional dependencies. Record the seeded
`[tool.kivy.ios.python].version`.

### Step 2 — baseline: nothing extra excluded

```bash
kivyforge lock -p ios --json > base.json 2> base.err; echo "exit=$?"
cat base.json
```

Expected: exit 1 or 5, and a diagnostic naming the first package with no iOS
wheel (`pycairo`, or `pillow` if it has none either). Record which.

### Step 3 — before the fix, with the culprit excluded

Add `pycairo` to the `exclude` list, plus `pillow` if Step 2 named it:

```bash
python3 - <<'EOF'
import pathlib, sys
p = pathlib.Path("pyproject.toml")
names = sys.argv[1:] or ["pycairo"]
text = p.read_text()
entries = "".join(f'    "{n}",\n' for n in names)
p.write_text(text.replace("exclude = [\n", "exclude = [\n" + entries, 1))
EOF
grep -A3 '^exclude' pyproject.toml
```

(To add both, run it as `python3 - pycairo pillow <<'EOF' ...`.)

Then run the lock against `main`, which does not have the fix. The editable
install follows the checkout:

```bash
REPO=<path to your clone>
git -C "$REPO" switch main
rm -f pylock.ios.toml
kivyforge lock -p ios --json > before.json 2> before.err; echo "exit=$?"
cat before.json
git -C "$REPO" switch exclude-during-resolve
```

Expected: **fails**, still naming an excluded package. That is the bug.

### Step 4 — after the fix

```bash
rm -f pylock.ios.toml
kivyforge lock -p ios --json > after.json 2> after.err; echo "exit=$?"
cat after.json
grep '^name = ' pylock.ios.toml
```

Pass if: exit 0, `ok: true`, and `pylock.ios.toml` names neither `pycairo` nor
anything you excluded. If it fails on a *different* package with no iOS wheel,
record it, exclude that too, and repeat until it locks or until the package is
one KivyMD cannot run without (then stop and report).

Then confirm the lock is stable:

```bash
kivyforge lock -p ios --check; echo "exit=$?"
```

Pass if: exit 0, in sync.

### Step 5 (optional) — does the app run without them?

Not part of the fix, but it answers the reporter's real question: can a KivyMD
app ship on iOS with `pycairo` excluded?

```bash
kivyforge build -p ios --simulator && kivyforge run -p ios --simulator
```

Record whether the KivyMD window appears, or the traceback if `materialshapes`
imports `cairo` at startup.

### Step 6 — clean up

```bash
rm -rf /tmp/kf190
```

## Record

1. Write `docs/design/dev/exclude-resolve-mac-findings.md`: environment table,
   each step's command and verbatim output (trim pip's download lines), defects
   first.
2. Append a row to `docs/design/dev/test-matrix.md` §7: date,
   `iOS lock, exclude applied during resolution (issue #190)`,
   `lock only (local, network)`, the host (macOS, Xcode, Python, pip), the
   commit, and the result, before and after.
3. Commit both on `exclude-during-resolve` with a message that says why, and
   push that branch: the owner asked for the results to come back this way.
   Report back, defects first.
