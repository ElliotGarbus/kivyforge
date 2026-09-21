# Agent prompt — validate the iOS `entry_point` / `__main__` fix on the Mac

> **Run this on the Mac**, from the repo root of `main`. Written 2026-09-21
> from the Windows host, where none of it can run.
>
> Point the agent at this file, or copy the "Prompt" section.

## Background — what changed and why this needs a real run

Until today, `entry_point` was *imported* (not run as `__main__`) on Android
and iOS, while Linux/macOS/Windows already ran it as `__main__` (fixed
2026-09-14/17 specifically so ordinary `if __name__ == "__main__":` apps would
start). That split was a real, silent migration trap: the idiom started fine
on desktop and **silently never started on mobile** — no error, nothing in the
log.

An external contributor ([PR #1](https://github.com/ElliotGarbus/kivyforge/pull/1),
kengoon) independently found and fixed this for iOS via `runpy.run_module`.
The PR was declined (it did iOS alone, breaking a same-day regression test and
leaving the common spec wrong) but credited, and the fix was taken on directly
so both platforms land together, per this repo's own stated requirement for
this change (`roadmap.md`, the `entry_point` inconsistency item).

**Both platforms are now fixed in code and hermetically tested:**

- `kivyforge/platforms/android/bootstrap/templates/cpp/main.c` and
  `kivyforge/platforms/ios/templates/kivyforge_bootstrap.m` both now run
  `entry_point` via `runpy.run_module(entry_point, run_name="__main__",
  alter_sys=True)`.
- `docs/design/common/01-pyproject-kivy-spec.md`'s `entry_point` section
  states one unified contract (all five platforms run as `__main__`) with a
  migration note for two real behavior changes: a package-style `entry_point`
  now needs a `__main__.py` everywhere, and the entry module is no longer left
  in `sys.modules` after startup.
- `tests/platforms/android/test_bootstrap.py::test_entry_point_is_run_as_main`
  and `tests/platforms/ios/test_plist_sources.py::test_entry_point_is_run_as_main`
  pin the new generated-source content.

**Android is validated on real hardware, 2026-09-21 (Pixel 8a, this repo's
own findings — see `roadmap.md`).** `hello-android`'s contract smoke test
passed unmodified, then passed again after temporarily adding the
`if __name__ == "__main__":` guard to its `src/main.py` — the exact scenario
that silently failed before this fix. Reverted after.

**iOS has had no run at all since the fix landed** — no simulator, no device,
nothing beyond hermetic template-rendering tests. That is what this prompt is
for: the same proof, on iOS.

---

## Prompt

You are validating the iOS half of the `entry_point`/`__main__` unification on
real Apple toolchain. The environment is already set up. Follow the Android
methodology exactly: prove the fix by actually flipping an example to the
guard style and watching it still boot, not by re-reading the diff.

### Step 0 — environment and baseline

```bash
git pull                      # you need the commit titled "Unify entry_point
                               # execution as __main__ across Android and iOS"
                               # or later, on main
sw_vers; xcodebuild -version; swift --version
.venv/bin/kivyforge --version
```

Read [`test-matrix.md`](test-matrix.md)'s top three rules and §7 before doing
anything else — do not rely on a summary of it, including this file's
Background section.

### Step 1 — unmodified regression check

Pick `examples/mobile/hello-kivy` (a committed-lock on-device gate example,
so no re-lock needed) or another already-working iOS example if you have a
reason to prefer it.

```bash
cd examples/mobile/hello-kivy
../../../.venv/bin/kivyforge doctor -p ios
../../../.venv/bin/kivyforge build  -p ios --simulator
../../../.venv/bin/kivyforge run    -p ios --simulator
xcrun simctl io booted screenshot /tmp/ios-hello-baseline.png
```

Expected: builds, launches, renders "Hello Kivy" — same as every prior run of
this example. This confirms the fix does not break the existing, portable,
guard-free `App().run()` style before you touch anything.

### Step 2 — the actual proof: flip the guard, rebuild, confirm it still works

Edit `examples/mobile/hello-kivy/src/main.py`: wrap the final `HelloKivyApp().run()`
call in `if __name__ == "__main__":` (indent it one level). This is precisely
the buildozer-idiomatic style that silently failed on iOS before today's fix.

```bash
../../../.venv/bin/kivyforge build -p ios --simulator
../../../.venv/bin/kivyforge run   -p ios --simulator
xcrun simctl io booted screenshot /tmp/ios-hello-guarded.png
```

Expected: identical result to Step 1 — builds, launches, renders "Hello Kivy".
If it does **not** render, or the simulator shows a blank/frozen screen with
no crash, that is the fix not actually working end-to-end despite the
hermetic test passing — a real, serious finding. Capture full build/run
output either way.

If you have a **physical device and a provisioning profile**, repeat Step 2
there too (`--device` in place of `--simulator`) — closer to what an app
actually ships as, and the config already has `[tool.kivy.ios].simulator_archs`
separate from the device path. If you have neither, say so and skip; do not
infer that it would have worked.

### Step 3 — revert

```bash
git diff examples/mobile/hello-kivy/src/main.py   # confirm it's just the guard
git checkout -- examples/mobile/hello-kivy/src/main.py
git status                                         # must be clean
```

Do not commit the temporary guard change. Also confirm no `pylock.ios.toml`
drift: `hello-kivy`'s lock is one of the three exempt on-device gate examples
and tracks its lock on purpose — if `lock -p ios` would change it, diff and
report rather than committing the change (`common/03-lockfile-concept.md`
§"Example-repo lock policy").

### Step 4 — report

Write findings to `docs/design/dev/ios-entry-point-main-validation-findings.md`:
an environment table (Xcode/Swift versions, simulator or device + OS version),
then Step 1/2's actual output (build logs, screenshot paths, pass/fail).

Then update `docs/design/dev/roadmap.md`'s `entry_point` inconsistency item
(search for "iOS validation is next") with the real result, the same way the
Android paragraph already reads. Update `test-matrix.md` §7 with a dated row
if this is the kind of run that belongs there (check the file's own rules for
what qualifies).

### Rules of engagement

- Record what you **observed**, not what you expect. If a step fails, capture
  the full error and say so plainly rather than working around it.
- The guard change in Step 2 is temporary and must not be committed.
- Do not commit a generated `pylock.ios.toml` change (Step 3).
- Commit on `main`. **Do not push without asking.**
