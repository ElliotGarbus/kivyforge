# Agent prompt — `module:function` entry points on macOS and iOS (issue #68)

> **Run this on the Mac**, from the repo root of `main` at `778cc91f` (the
> merge of PR #165) or later. Written 2026-10-21 from the Windows host, where
> neither target can run.
>
> Point the agent at this file, or copy the "Prompt" section. Results go in
> [`entry-point-mac-ios-findings.md`](entry-point-mac-ios-findings.md).

## Background — what changed, and what is already proven

[Issue #68](https://github.com/ElliotGarbus/kivyforge/issues/68), merged in
[PR #165](https://github.com/ElliotGarbus/kivyforge/pull/165), follows the
entry-points spec:

- `[tool.kivy].entry_point` may be `"pkg.app:main"`. kivyforge imports
  `pkg.app` **as part of its package** and calls `main()` with no arguments, as
  an installed gui-script does. A relative import inside the package then works;
  it fails when `pkg/app.py` itself runs as `__main__`, which was the only
  option before.
- With `entry_point` unset, the one `[project.gui-scripts]` entry is used.
  `[project.scripts]` is never read.
- The bare form (`entry_point = "main"`) is **unchanged**: the module still
  runs as `__main__`, with no launcher.

How each platform does it: `kivyforge/bundle/entry_launcher.py` renders a small
launcher, `_kivyforge_main`, which every platform runs as `__main__`.

- **macOS** writes `_kivyforge_main.py` into `Contents/Resources/app`, after the
  package metadata (so `top_level.txt` does not list it) and before
  byte-compiling (so `package` ships it as a sourceless `.pyc`). The compiled
  launcher's `ENTRY` becomes `_kivyforge_main`, so it still execs
  `python3 -P -m <ENTRY>`.
- **iOS** cannot write it into `app/`: a debug build's `app/` is a symlink to the
  user's source tree. So `main_config.h` gains `ENTRY_LAUNCHER`, the launcher
  source as a C string. `main.m` passes it to `kivyforge_main()`, which has a new
  `entry_launcher` parameter, and `kivyforge_bootstrap.m` runs it with
  `PyRun_SimpleString` instead of `runpy` when it is non-empty.
- **One deliberate difference from pip's wrapper:** the launcher raises
  `SystemExit` only for a status that is not success. On the Android emulator,
  pip's unconditional `sys.exit(main())` turned every clean stop into an abort
  (SIGABRT). A function that returns `None` or `0` now simply returns.

**Proven on real runs** (test-matrix §7, 2026-10-21): Windows, Linux (WSL2) and
the Android emulator. On each, `build`, the stripped `package` and `run`
started a src-layout package app declared only in `[project.gui-scripts]`. The
relative import worked, and the exit status was `main()`'s return value. The
bare-form fixtures and examples are unchanged.

**Not proven, and the reason for this prompt:**

1. **The iOS C changes have never been compiled.** Neither the new
   `kivyforge_main` signature nor `_run_entry_launcher` has been through clang.
   Hermetic tests only check the rendered text, and they run the `ENTRY_LAUNCHER`
   string with the host interpreter's `-c`.
2. **No macOS `.app` has started a function entry point.** The hermetic test
   ran the launcher module with the Windows interpreter. The compiled launcher,
   the staged runtime, signing and Kivy's window have not been in the loop.

---

## Prompt

You are validating issue #68's entry-point launcher on macOS and on the iOS
simulator, on real Apple toolchains. Prove it by running a real app and
reading what it reports about itself, not by re-reading the diff. Record what
you observe; where a step fails, keep the full output.

### Step 0 — environment

```bash
git switch main && git pull
git log --oneline -1           # 778cc91f or later
sw_vers; xcodebuild -version; swift --version; clang --version | head -1
.venv/bin/kivyforge --version
.venv/bin/kivyforge doctor -p macos
.venv/bin/kivyforge doctor -p ios
```

Read [`test-matrix.md`](test-matrix.md)'s top rules and the 2026-10-21 rows in
§7 yourself; do not rely on this file's summary of them.

Below, `kf` means `<repo>/.venv/bin/kivyforge`.

### Step 1 — the test app, outside the repo

It is the app the Windows, Linux and Android runs used: a package whose module
imports a sibling relatively, with `main()` declared **only** in
`[project.gui-scripts]`, a decoy `[project.scripts]` entry, and **no
`entry_point`**. With `KF_GUI_DEMO_PROBE` set, it writes what it saw to that
file, stops itself after 2 s, and `main()` returns 7. Without it, it stays up
until its button is tapped, and `main()` returns `None`.

```bash
mkdir -p ~/kf-gui68/gui-demo/src/gui_demo && cd ~/kf-gui68/gui-demo
touch src/gui_demo/__init__.py
echo 'GREETING = "relative import ok"' > src/gui_demo/greeting.py
printf 'def main():\n    raise SystemExit("the console script must never be what kivyforge starts")\n' > src/gui_demo/cli.py
```

`src/gui_demo/app.py`:

```python
"""Started only through [project.gui-scripts] gui-demo = "gui_demo.app:main"."""

import os

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.button import Button

from .greeting import GREETING

#: With KF_GUI_DEMO_PROBE set, the app writes what it saw there, stops itself,
#: and main() returns this, which the launcher makes the exit status.
PROBE_EXIT = 7


class GuiDemoApp(App):
    def build(self):
        print(f"KF-GUI-DEMO: module={__name__} greeting={GREETING}", flush=True)
        probe = os.environ.get("KF_GUI_DEMO_PROBE")
        if probe:
            Clock.schedule_once(lambda dt: self._finish(probe), 2)
        # A tap stops the app, so main() returns and the launcher exits.
        return Button(
            text=f"{GREETING}\n{__name__}:main()\ntap to stop",
            halign="center",
            on_release=lambda *_: self.stop(),
        )

    def _finish(self, probe):
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(f"{__name__}|{GREETING}")
        self.stop()


def main():
    GuiDemoApp().run()
    print("KF-GUI-DEMO: main() returning", flush=True)
    return PROBE_EXIT if os.environ.get("KF_GUI_DEMO_PROBE") else 0
```

`pyproject.toml` (Kivy 2.3.1 from PyPI on macOS, and on iOS the Kivy 3.0 build
`examples/mobile/hello-kivy` pins):

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "gui-demo"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "kivy==2.3.1; sys_platform == 'darwin'",
    "kivy==3.0.0.dev202610051055; sys_platform == 'ios'",
    "more-itertools==11.1.0; sys_platform == 'ios'",
    "filetype==1.2.0; sys_platform == 'ios'",
]

[project.scripts]
gui-demo-cli = "gui_demo.cli:main"

[project.gui-scripts]
gui-demo = "gui_demo.app:main"

[tool.kivy]
display_name = "GUI Demo"
app_dir = "src"
orientation = ["portrait"]

[tool.kivy.macos]
schema_version = 1
bundle_id = "org.kivyforge.guidemo"
build = 1
archs = ["arm64"]
exclude = ["kivy-garden", "requests", "certifi", "charset-normalizer", "idna", "urllib3", "docutils", "pygments"]

[tool.kivy.macos.python]
version = "3.13.14"

[tool.kivy.ios]
schema_version = 1
bundle_id = "org.kivyforge.guidemo"
build = 1
deployment_target = "16.0"
extra_index_urls = ["https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"]
exclude = ["kivy-garden", "requests", "certifi", "charset-normalizer", "idna", "urllib3", "docutils", "pygments"]

[tool.kivy.ios.python]
version = "3.15.0b4"

[tool.kivy.ios.signing]
team_id = ""
identity = "Apple Development"
provisioning_profile = ""
auto_signing = true
upload_symbols = true
```

If either overlay fails validation on this kivyforge, fix the overlay to match
`examples/mobile/hello-kivy` or `tests/fixtures/apps/macos-gate`, and record what
you changed. **Do not touch `[project.gui-scripts]` or add an `entry_point`:**
resolving the entry point from the gui-script is what is under test.

### Step 2 — macOS, the gui-scripts app

```bash
cd ~/kf-gui68/gui-demo
kf lock -p macos
kf build -p macos
APP="build/macos/GUI Demo.app"      # adjust if the name differs; record it
ls "$APP/Contents/Resources/app"
cat "$APP/Contents/Resources/app/"*.dist-info/top_level.txt
strings "$APP/Contents/MacOS/"* | grep -x _kivyforge_main
cat "$APP/Contents/Resources/app/_kivyforge_main.py"
```

Expected: `_kivyforge_main.py` beside `gui_demo/` and `gui_demo-0.1.0.dist-info`,
`top_level.txt` listing only `gui_demo`, and `_kivyforge_main` present in the
compiled launcher.

Launch the executable **directly**. `open` and Finder swallow stderr and the
exit status, which are the evidence here.

```bash
rm -f /tmp/probe-build.txt
KF_GUI_DEMO_PROBE=/tmp/probe-build.txt "$APP/Contents/MacOS/"*; echo "exit=$?"
cat /tmp/probe-build.txt
codesign --verify --deep --strict "$APP" && echo "signature still valid"
```

Expected: a window opens and closes itself after about 2 s; `exit=7`;
the probe reads `gui_demo.app|relative import ok`; the signature is still valid
after the launch (the launcher sets `PYTHONDONTWRITEBYTECODE`).

Then without the probe: launch again, click the button, and confirm the process
exits with `exit=0`. A clean stop must return without a crash report: check
`~/Library/Logs/DiagnosticReports` for a new `GUI Demo` entry.

The release path (`strip_source`):

```bash
kf package -p macos                  # add the signing flags you normally use, if any
find "$APP/Contents/Resources/app" -name '*.py' | wc -l     # expect 0
ls "$APP/Contents/Resources/app"                             # expect _kivyforge_main.pyc
```

Without a signing identity, `package` rebuilds the same `$APP` as a release,
ad-hoc signed; with one, use the `.app` its output names. Launch it directly
with the probe set, as above. Expected: `exit=7`, the same probe text, and a
valid signature afterwards. If you notarize, say so; it is not required here.

`run` reports the launcher's real exit status:

```bash
KF_GUI_DEMO_PROBE=/tmp/probe-run.txt kf run -p macos; echo "kivyforge exit=$?"
KF_GUI_DEMO_PROBE=/tmp/probe-run-rel.txt kf run -p macos --release; echo "kivyforge exit=$?"
```

Expected, matching Windows and Linux: the app starts and writes the probe, and
`run` ends with `GUI Demo.app exited with status 7.` and exit 1, which is
correct for a non-zero app status. (`run -p macos` execs the launcher in the
foreground, not through `open`, so it sees the status.)

### Step 3 — macOS, the bare form is unchanged

```bash
cp -R <repo>/tests/fixtures/apps/macos-gate ~/kf-gui68/macos-gate && cd ~/kf-gui68/macos-gate
kf build -p macos
ls build/macos/*.app/Contents/Resources/app          # expect main.py, no _kivyforge_main
strings build/macos/*.app/Contents/MacOS/* | grep -x main
```

Launch the executable directly. Expected: the window opens and stays up, as
before #68. Close it yourself.

### Step 4 — iOS simulator, the gui-scripts app (the first compile of the C change)

```bash
cd ~/kf-gui68/gui-demo
kf lock -p ios
kf build -p ios --simulator
grep -n "ENTRY_POINT\|ENTRY_LAUNCHER" gui-demo-ios/main_config.h
grep -n "kivyforge_main" gui-demo-ios/main.m
```

(If the Xcode project folder has another name, use the one `build` reports.)

Expected: the build **compiles and links**. This is the first time
`kivyforge_main(argc, argv, ENTRY_POINT, ENTRY_LAUNCHER, APP_DIR, ...)` and
`_run_entry_launcher` go through clang, so a compile error here is the most
likely failure; keep the full error. `main_config.h` should show
`ENTRY_POINT "gui_demo.app"` and a non-empty `ENTRY_LAUNCHER` string.

```bash
kf run -p ios --simulator
xcrun simctl io booted screenshot ~/kf-gui68/ios-gui-demo.png
```

Expected: the button reads `relative import ok` / `gui_demo.app:main()` /
`tap to stop`. That text is computed from the module's own `__name__` and the
relatively imported value, so the screenshot is the proof. Also capture the
app's stdout for the `KF-GUI-DEMO: module=gui_demo.app ...` line, e.g.:

```bash
xcrun simctl terminate booted org.kivyforge.guidemo
xcrun simctl launch --console-pty booted org.kivyforge.guidemo
```

Then **click the button** in the Simulator window. Expected: `KF-GUI-DEMO: main()
returning` on the console, and the app ends without a crash report (check
`~/Library/Logs/DiagnosticReports` for a new entry). On iOS, an app ending
itself is unusual; report what the simulator does rather than judging it.

The non-zero path, `SystemExit(7)` through `PyErr_Print`:

```bash
xcrun simctl terminate booted org.kivyforge.guidemo
SIMCTL_CHILD_KF_GUI_DEMO_PROBE=/tmp/probe-ios.txt \
  xcrun simctl launch --console-pty booted org.kivyforge.guidemo; echo "exit=$?"
cat /tmp/probe-ios.txt
```

Expected: the probe file holds `gui_demo.app|relative import ok`, and the
process ends with status 7. If the simulator's sandbox stops the write to
`/tmp`, or `simctl` does not report the status, say exactly that and rely on the
console lines instead. Do not count it as a pass.

### Step 5 — iOS, the bare form is unchanged

```bash
cd <repo>/examples/mobile/hello-kivy
kf build -p ios --simulator
grep -n "ENTRY_POINT\|ENTRY_LAUNCHER" hello-kivy-ios/main_config.h   # "main", and ""
kf run -p ios --simulator
xcrun simctl io booted screenshot ~/kf-gui68/ios-hello-kivy.png
git status                                                          # must be clean
```

Expected: `ENTRY_LAUNCHER ""`, the app renders "Hello Kivy" as before, and the
repo is clean. `hello-kivy` commits its lock on purpose: if anything would change
`pylock.ios.toml`, diff and report rather than committing
(`common/03-lockfile-concept.md`, "Example-repo lock policy").

### Step 6 — optional: a device, and a release `.ipa`

If you have a provisioning profile and a device, repeat Step 4's build and run
with `--device`. `package -p ios` materializes a release copy of `app/`; the
launcher is compiled in, so it should not care. If you cannot run either, say
so and skip. Do not infer that it would have worked.

### Step 7 — report

Write [`entry-point-mac-ios-findings.md`](entry-point-mac-ios-findings.md),
**defects first**, in the shape of the other findings files:

- an environment table (macOS, Xcode, clang, simulator model and iOS version,
  and the kivyforge commit);
- per step: the commands, verbatim output for anything that failed, exit
  statuses, probe contents, and screenshot paths;
- pass or fail per step, stated plainly.

Then add dated rows to [`test-matrix.md`](test-matrix.md) §7. Replace nothing:
the 2026-10-21 "iOS, macOS: the same launcher" row stays as the record that
these were unverified then.

### Rules of engagement

- Record what you **observed**. A step that could not run is reported as not
  run, with the reason.
- If the iOS build fails to compile, that is the main finding: capture the full
  clang error and stop the iOS half there. Do not patch `kivyforge_bootstrap.m`,
  `main.m` or `kivyforge_bootstrap.h` as part of this run; propose the fix in
  the findings instead.
- Out of scope, do not fix here: macOS rejects a dotted **bare** `entry_point`
  (`"pkg.start"`), because `render_launcher_source` checks `isidentifier()`. It
  predates #68 and is a separate follow-up.
- Keep the test app outside the repo. Commit only the findings file and the
  test-matrix rows, on a branch. **Do not push without asking.**
