# Agent prompt — macOS: accept a dotted module `entry_point`, on the Mac

> **Run this on the Mac**, from the repo root of `main` at `2aefa0e4` or later.
> Written 2026-10-21 from the Windows host. The change itself is small, but
> only a Mac can compile the launcher and start the `.app`, so it is developed
> there.
>
> Point the agent at this file, or copy the "Prompt" section. Results go in
> `macos-dotted-entry-point-findings.md` beside it, in the shape of
> `entry-point-mac-ios-findings.md` (PR #167; on `main` once that merges):
> environment table, per-step commands and verbatim output, defects first.

## Background — the one platform that rejects `"pkg.start"`

`[tool.kivy].entry_point` written as a dotted module, such as `"pkg.start"` for
`src/pkg/start.py`, is a documented layout
([`common/01-pyproject-kivy-spec.md`](../common/01-pyproject-kivy-spec.md),
"`app_dir` + `entry_point` interaction"). The config loader accepts it, and
Windows, Linux, Android and iOS run it as `python -m pkg.start`.

**macOS refuses it.** `render_launcher_source` in
`kivyforge/platforms/macos/launcher.py` validates with `str.isidentifier()`,
which fails on any dot:

```python
def render_launcher_source(entry_point: str) -> str:
    if not entry_point.isidentifier():
        raise AppBundleError(f"entry_point {entry_point!r} is not a valid module name.")
    return _SOURCE.format(entry=entry_point)
```

Nothing else in the path needs a single segment. Since the strip-source fix
(2026-09-14), the compiled launcher execs `python3 -P -m <ENTRY>` with
`Resources/app` on `PYTHONPATH`, and `-m` takes a dotted name. Since #68
(PR #165), the missing-file check in `_copy_app_sources`
(`kivyforge/platforms/macos/bundle.py`) uses the shared
`entry_launcher.missing_entry_module`, which already maps `pkg.start` to
`src/pkg/start.py`. Before #68 it looked for `src/pkg.start.py`, so the
`isidentifier` check was hidden behind an earlier, wrong error.

The `module:function` form from #68 is **not** affected: its launcher module,
`_kivyforge_main`, is a plain identifier. The limitation was found during #68,
left out of scope on purpose, and noted in
[`entry-point-mac-ios-prompt.md`](entry-point-mac-ios-prompt.md).

The value is inlined into a C string literal
(`static const char *ENTRY = "{entry}";`), so the check is also what keeps a
quote or newline out of generated C. The fix must keep that guarantee.

---

## Prompt

You are fixing and validating, on the Mac, macOS's handling of a dotted
module-form `entry_point`. Reproduce it first, then fix it, then prove the fix
by launching a real `.app`.

### Step 0 — environment

```bash
git switch main && git pull
git log --oneline -1                    # 2aefa0e4 or later
git switch -c macos-dotted-entry-point
sw_vers; xcodebuild -version; clang --version | head -1
.venv/bin/kivyforge --version
.venv/bin/kivyforge doctor -p macos
```

Read [`AGENTS.md`](../../../AGENTS.md) and the top rules of
[`test-matrix.md`](test-matrix.md) yourself. Below, `kf` means
`<repo>/.venv/bin/kivyforge`.

### Step 1 — the test app, outside the repo

A Buildozer-style app in a package: `entry_point = "pkg.start"`, run as
`__main__`, with a relative import. Under `-m`, `__package__` is set, so the
relative import works. With `KF_DOTTED_PROBE` set, it writes what it saw, stops
itself after 2 s, and exits 7.

```bash
mkdir -p ~/kf-dotted/app/src/pkg && cd ~/kf-dotted/app
touch src/pkg/__init__.py
echo 'GREETING = "relative import ok"' > src/pkg/helper.py
```

`src/pkg/start.py`:

```python
"""Run as __main__ through entry_point = "pkg.start"."""

import os
import sys

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.label import Label

from .helper import GREETING


class DottedApp(App):
    def build(self):
        print(f"KF-DOTTED: name={__name__} spec={__spec__.name} {GREETING}", flush=True)
        probe = os.environ.get("KF_DOTTED_PROBE")
        if probe:
            Clock.schedule_once(lambda dt: self._finish(probe), 2)
        return Label(text=f"{GREETING}\n{__spec__.name} as {__name__}")

    def _finish(self, probe):
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(f"{__name__}|{__spec__.name}|{GREETING}")
        self.stop()


if __name__ == "__main__":
    DottedApp().run()
    if os.environ.get("KF_DOTTED_PROBE"):
        sys.exit(7)
```

`pyproject.toml`:

```toml
[project]
name = "dotted-demo"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["kivy==2.3.1"]

[tool.kivy]
display_name = "Dotted Demo"
app_dir = "src"
entry_point = "pkg.start"

[tool.kivy.macos]
schema_version = 1
bundle_id = "org.kivyforge.dotteddemo"
build = 1
archs = ["arm64"]
exclude = ["kivy-garden", "requests", "certifi", "charset-normalizer", "idna", "urllib3", "docutils", "pygments"]

[tool.kivy.macos.python]
version = "3.13.14"
```

### Step 2 — reproduce, before changing anything

```bash
cd ~/kf-dotted/app
kf lock -p macos
kf build -p macos; echo "exit=$?"
```

Expected on unmodified `main`: the build fails with
`entry_point 'pkg.start' is not a valid module name.` Record the exact output
and exit status. If it does **not** fail, stop and report: the premise of this
prompt is wrong.

### Step 3 — the fix

In `kivyforge/platforms/macos/launcher.py`, make `render_launcher_source`
accept a dotted module whose every segment is a non-keyword identifier: the
same rule as `render_apprun` in `kivyforge/platforms/linux/launcher.py` and
`_validate_entry_point` in `kivyforge/platforms/windows/launcher/__init__.py`.
Everything else must still be rejected, because the value lands in a C string
literal. Keep the error type and text (`AppBundleError`, "... is not a valid
module name.").

Update the docstring and the comment above `_SOURCE` if they say or imply a
single segment.

Tests, in `tests/platforms/macos/test_plist_launcher.py`:

- **A dotted name renders:** `render_launcher_source("pkg.start")` contains
  `static const char *ENTRY = "pkg.start";`.
- **Bad values are still rejected,** parametrized: `""`, `"pkg-start"`,
  `"pkg.class"` (keyword), `"pkg..start"`, `".pkg"`, `"pkg.app:main"`,
  `'pkg"x'`, `"pkg\nx"`.
- **Change `test_rejects_non_identifier_entry`.** It uses `"main.py"` as its
  invalid example, but under a dotted rule `"main.py"` is a valid module path
  (`main/py.py`), as it already is on Linux and Windows and in the config
  loader. Replace it with a truly invalid value; do not keep `"main.py"`
  rejected with a special case.
- **The real-clang tests in the same file**
  (`test_child_is_invoked_with_dash_m_not_a_source_path` and its neighbours)
  run only where clang exists, which is here. Add or parametrize one so a
  launcher compiled for `"pkg.start"` execs `python3 -P -m pkg.start`. They are
  marked `requires_toolchain`, so run them so they cannot silently skip:
  `KIVYFORGE_REQUIRE_TOOLCHAIN=1 pytest tests/platforms/macos/test_plist_launcher.py`.

A bundle-level test belongs in `tests/platforms/macos/test_bundle.py`. Check
whether it can drive `_copy_app_sources` plus `render_launcher_source` for
`entry_point = "pkg.start"` with a `src/pkg/start.py` fixture, and add one if
the file's existing fakes allow it.

### Step 4 — prove it on a real `.app`

```bash
cd ~/kf-dotted/app
kf build -p macos
APP="build/macos/Dotted Demo.app"
ls "$APP/Contents/Resources/app" "$APP/Contents/Resources/app/pkg"
strings "$APP/Contents/MacOS/"* | grep -x pkg.start
rm -f /tmp/probe-dotted.txt
KF_DOTTED_PROBE=/tmp/probe-dotted.txt "$APP/Contents/MacOS/"*; echo "exit=$?"
cat /tmp/probe-dotted.txt
codesign --verify --deep --strict "$APP" && echo "signature still valid"
```

Launch the executable directly, not through `open`, which hides stderr and the
exit status. Expected: the window opens and closes after about 2 s, `exit=7`,
the probe reads `__main__|pkg.start|relative import ok`, and the signature is
valid after the launch. There is no `_kivyforge_main` in `Resources/app`: this
is the bare form.

The release path, and `run`:

```bash
kf package -p macos
find "$APP/Contents/Resources/app" -name '*.py' | wc -l      # expect 0
ls "$APP/Contents/Resources/app/pkg"                          # expect start.pyc, helper.pyc
KF_DOTTED_PROBE=/tmp/probe-dotted-rel.txt "$APP/Contents/MacOS/"*; echo "exit=$?"
KF_DOTTED_PROBE=/tmp/probe-run.txt kf run -p macos; echo "kivyforge exit=$?"
```

Expected: the stripped `.app` gives the same exit status and probe, and `run`
ends with `Dotted Demo.app exited with status 7.` (exit 1, correct for a
non-zero app status).

### Step 5 — regressions on this Mac

- **Single-segment bare form:** `tests/fixtures/apps/macos-gate`, copied out of
  the repo. `build`, launch directly; the window stays up as before. `strings`
  shows `main`.
- **`module:function` form:** the #68 test app, at `~/kf-gui68/gui-demo` if it is
  still there; otherwise rebuild it from
  [`entry-point-mac-ios-prompt.md`](entry-point-mac-ios-prompt.md) Step 1.
  `build`, launch with `KF_GUI_DEMO_PROBE` set: `exit=7` and
  `gui_demo.app|relative import ok`, as in its findings.

### Step 6 — docs, changelog, gates

- `docs/design/platforms/macos/macos-spec.md`: make sure nothing says or implies
  the entry point is a single segment.
- `docs/guides/`: search for the macOS build guide or the `[tool.kivy]`
  reference saying macOS needs a single-segment name, and remove it if found.
  If nothing says so, change nothing.
- `CHANGELOG.md` under `[Unreleased]`: a **Fixed** entry ("macOS builds accept a
  dotted `entry_point` such as `"pkg.start"`, which every other platform already
  ran") with **Migration:** none needed.
- [`test-matrix.md`](test-matrix.md) §7: a dated row for Steps 2, 4 and 5,
  appended, with no edits to existing rows.
- Gates, all of them: `ruff check kivyforge tests`,
  `ruff format --check kivyforge tests`, `pyright` (0 errors), `pytest`
  (coverage gate), and `mkdocs build --strict`.

### Step 7 — report and commit

Write `macos-dotted-entry-point-findings.md`, **defects first**: the environment
table, then Step 2's reproduction verbatim, the change, the test list, Step 4
and 5's commands with exit statuses, probe contents and screenshot paths, and
gate results.

Commit on `macos-dotted-entry-point`: the code, tests, docs, CHANGELOG, findings
and the test-matrix row. Explain *why* in the message. **Do not push without
asking.** When asked to open a PR, reference this prompt and the findings.

### Rules of engagement

- Record what you **observed**. A step that could not run is reported as not
  run, with the reason.
- Keep the change to the validation rule and its tests. Do not touch the
  `module:function` launcher (`kivyforge/bundle/entry_launcher.py`) or the
  other platforms' launchers; they already accept dotted names.
- Keep the test apps outside the repo, and copy fixtures out before building
  them. Do not commit a generated lock.
