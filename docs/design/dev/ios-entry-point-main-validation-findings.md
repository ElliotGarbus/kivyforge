# Findings — iOS `entry_point`/`__main__` fix validation

Run 2026-09-21 on the Mac, per
[`ios-entry-point-main-validation-prompt.md`](ios-entry-point-main-validation-prompt.md).

## Environment

| | |
|---|---|
| macOS | 26.6.2 (build 25G83) |
| Xcode | 26.6 (build 17F113) |
| Swift | 6.3.3 (swiftlang-6.3.3.1.3, clang-2100.1.1.101) |
| kivyforge | 3.0.0.dev0, at commit `d38fc4ce` ("Unify entry_point execution as
  `__main__` across Android and iOS") |
| Simulator | iOS 26.5 runtime |
| Device | Elliot's iPhone (iPhone 13 Pro Max, `iPhone14,3`), connected via
  `devicectl`, state `connected` |
| Example | `examples/mobile/hello-kivy` (committed-lock on-device gate
  example) |

Baseline: `pytest -q` and `pyright` both clean before and after this run
(679 stmts missed unrelated to this change, 92.78% coverage, 0 pyright
errors).

## Step 1 — unmodified regression check (simulator)

```
kivyforge doctor -p ios   → all PASS/expected WARN (no final CPython 3.15,
                             xcframework privacy manifests) — same as every
                             prior run of this example, nothing new.
kivyforge build  -p ios --simulator  → succeeded, "Built .../hello-kivy.app"
kivyforge run    -p ios --simulator  → launched; screenshot shows "Hello Kivy"
```

`xcrun simctl io booted screenshot /tmp/ios-hello-baseline.png` → "Hello
Kivy" rendered correctly, centered, white-on-black, same as every prior run.

Confirms the unified `runpy.run_module(..., run_name="__main__")` execution
path does not break the existing, guard-free `App().run()` style.

## Step 2 — the actual proof: flip the guard, rebuild, confirm it still works

Edited `examples/mobile/hello-kivy/src/main.py` to wrap the final call:

```python
if __name__ == "__main__":
    HelloKivyApp().run()
```

This is exactly the idiom that silently failed on iOS before the fix
(`entry_point` was `import`ed, not run as `__main__`, so this guard was
always `False` and `run()` was never called — no error, no crash, just a
window that never draws anything).

```
kivyforge build -p ios --simulator          → succeeded
kivyforge run   -p ios --simulator --no-build → launched; screenshot shows
                                                 "Hello Kivy" — pixel-identical
                                                 result to Step 1.
```

`xcrun simctl io booted screenshot /tmp/ios-hello-guarded.png` → "Hello
Kivy" rendered correctly — pixel-identical to the Step 1 screenshot (same
text, position, size; only the status-bar clock differs, one minute later).

**Result: PASS.** The guard style now boots identically to the unguarded
style. This is the scenario the fix was written for, run for real for the
first time.

### Device run (bonus — a device was connected and already provisioned)

A physical device (`Elliot's iPhone`) was connected and `connected` per
`devicectl list devices`, and this repo's `KIVYFORGE_TEAM_ID` override was
already known from the earlier macOS/iOS validation session, so Step 2 was
repeated `--device` in place of `--simulator`, still with the guard in place:

```
KIVYFORGE_TEAM_ID=R5PKSQLUZY kivyforge build -p ios --device
  → succeeded, "Built .../hello-kivy.app" (device slice)
KIVYFORGE_TEAM_ID=R5PKSQLUZY kivyforge run -p ios --device --no-build
  → "Installing on device Elliot's iPhone (...) ..."
    "Launching org.kivy.hello-kivy ..."
  → exit 0, no crash, no "device not unlocked" error (the failure mode seen
    in the prior macOS/iOS validation session when the phone was locked)
```

**Caveat, stated plainly per the prompt's rules of engagement:** unlike the
simulator, there is no `devicectl`/`xcrun` subcommand to screenshot a
physical device's screen from the CLI (checked: `devicectl device info
--help` has no screenshot verb). Exit 0 and the absence of a launch error is
real evidence the app installed and started, but it is not the same
first-hand visual confirmation as the simulator screenshots above. The user
was asked to glance at the phone; treat the device result as "launched
without error," not as an independently-verified render, unless confirmed
otherwise.

## Step 3 — revert

```
git diff examples/mobile/hello-kivy/src/main.py   # confirmed: just the guard
git checkout -- examples/mobile/hello-kivy/src/main.py
git status                                         # clean
```

The temporary guard change was not committed.

### Lock drift check — and an unrelated bug found and fixed along the way

`kivyforge lock -p ios --check` reported `KF-LOCK-DRIFT` on
`hello-kivy/pylock.ios.toml` with an **empty diff** (`"diff": []` in the
`--json` envelope) — consistently, across three repeated runs, even though
`git diff`/`git status` showed no changes anywhere in the example and
`pyproject.toml`'s live SHA-256 matched the `pyproject_sha256` already
recorded in the lock.

Backing up the lock and running `kivyforge lock -p ios --update` to see what
it would actually change showed the answer: the regenerated file was
**byte-identical to the committed one except for the `generated_at`
timestamp**. So the lock was not actually stale — `--check` was wrong.

Root cause, confirmed by comparing the loaded lock against a freshly-built
one field-by-field: `build_lockfile()` returns `packages` (and, within each
package, `wheels`) in **resolver-encounter order**, and only
`writer.dumps()` sorts them into the canonical order that ends up on disk
(module docstring: "a deterministic ordering ... so diffs across runs show
only real changes"). `lock --check`'s `semantic_equal()` compared the raw,
unsorted, freshly-built `Lockfile` against the one reloaded from the
previously-sorted file using plain dataclass equality — order-sensitive. For
this example the resolver's natural order (`Kivy`, `more-itertools`,
`filetype`) doesn't match the alphabetical order the file was written in
(`filetype`, `Kivy`, `more-itertools`), so **every** `--check` failed, and
would keep failing forever, regardless of whether anything had actually
changed. `diff_summary()` builds its comparison from `{name: package}` dicts
on both sides, which is why the reported diff was empty — nothing
order-sensitive is checked there, only the (order-insensitive) `--check`
verdict itself was wrong.

This is a real bug in tooling this repo's own docstring calls "the CI
pre-flight," not a Step-3-specific fluke: it reproduces for any project where
the resolver's encounter order isn't already alphabetical, which is
effectively any project with more than one package.

**Fixed** (`kivyforge/platforms/ios/lock/builder.py::semantic_equal`):
normalize both sides — sort `packages` by the same `sort_key` the writer
uses, sort each package's `wheels` by filename, and sort `xcframeworks`/
`swift_packages` the same way — before comparing, matching the tolerance
`diff_summary()` already had. A real content change (tested: bumping a
version) is still caught in either order.

**The desktop lock builder (`kivyforge/lock/wheelruntime/builder.py`, shared
by macOS/Linux/Windows) has the identical `semantic_equal()` shape** — same
unsorted-build/sorted-write split, same order-sensitive comparison. It was
not independently reproduced against a real desktop example in this session
(that would need its own re-resolve against a project whose resolver order
happens to disagree with alphabetical, which wasn't set up here), but the
code is the same shape as the iOS bug that *was* reproduced, so it was fixed
the same way rather than left for a future example to trip over. Regression
tests were added for both (`tests/platforms/ios/lock/test_builder.py`,
`tests/platforms/macos/lock/test_builder.py`) exercising reordered
packages/wheels (still equal) and a real version change under reordering
(still unequal). Full suite + `pyright` + `ruff check`/`format` clean after
the fix.

`hello-kivy`'s `pylock.ios.toml` itself was **not** changed or committed —
per the example-repo lock policy, the on-device gate examples track their
lock on purpose, and this was a false positive, not real drift.

## Step 4 — roadmap / test-matrix updates

See `roadmap.md`'s `entry_point` inconsistency item and `test-matrix.md` §7
for the dated entries recording this run.

## Summary

| Check | Result |
|---|---|
| Unmodified `App().run()` style, simulator | PASS — renders "Hello Kivy" |
| `if __name__ == "__main__":` guard style, simulator | PASS — renders "Hello Kivy", identical to unguarded |
| Guard style, physical device | Launched, exit 0, no error — not visually confirmed (no CLI screenshot path for a physical device) |
| `pylock.ios.toml` drift after revert | False positive (`--check` bug, fixed); no real drift, lock not touched |

**iOS is now validated for real**, the same way Android was: the guard style
that used to silently fail boots identically to the style that always
worked, on real Apple toolchain, not just hermetic template tests.
