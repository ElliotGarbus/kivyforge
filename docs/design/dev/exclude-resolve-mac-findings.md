# `exclude` applied during resolution, on iOS (#190) — findings

Run per [`exclude-resolve-mac-prompt.md`](exclude-resolve-mac-prompt.md)
against `exclude-during-resolve` @ `b02c443c` (after) and `origin/main` @
`a423f475` (before). Date: 2026-10-26.

**The fix works on iOS.** With the culprit excluded, `main` fails on the
excluded package and the branch locks without it. The scratch app had to
deviate from the prompt, though: on iOS the first package with no wheel is
not `pycairo` or `pillow` but `materialyoucolor`, and KivyMD cannot start
without it.

## Defects and deviations first

1. **Not a #190 defect — KivyMD 2.0.0 cannot ship on iOS today.** It needs
   `materialyoucolor>=3.0.3`, which has no iOS wheel on PyPI or
   kivy-mobile-wheels (pip sees only 1.0, 1.1 and 1.2.0). KivyMD imports it
   unconditionally: `kivymd/app.py:82` imports `kivymd.theming`, and
   `kivymd/theming.py:41-49` imports from `materialyoucolor`. So excluding it
   locks, but the app dies at `from kivymd.app import MDApp` (Step 5).
   Excluding `pycairo` is enough to get past `materialshapes`. The answer to
   the reporter's question ("can a KivyMD app ship on iOS with `pycairo`
   excluded?") is no, and that is because of `materialyoucolor`, not `pycairo`.
   The fix is for `materialyoucolor` to publish iOS wheels on PyPI, which
   CPython 3.15's release makes the natural next step for its maintainers.
   Android locked `materialyoucolor` fine (§7, Windows row), so the gap is
   iOS only.
2. **Deviation from Step 2's expectation.** `pillow` has an iOS wheel
   (`pillow-13.0.0-cp315-cp315-ios_13_0_arm64_iphoneos` and
   `..._iphonesimulator`), so it never needed excluding on iOS. pip gives up
   on `materialyoucolor` before it reaches `materialshapes`, so `pycairo`
   never shows up in the baseline. Steps 3–4 therefore excluded `pycairo` *and*
   `materialyoucolor`, so the run exercises the shim on a package pip
   would otherwise have failed on.
3. **Side observation — `init` still seeds `3.15.0b4`.**
   `kivyforge/cli/init_writer.py:27` has `DEFAULT_PYTHON_VERSION = "3.15.0b4"`,
   while the loader's hints and `platforms/ios/sources.py:56` already say
   `3.15.0`. Not part of this change and not fixed here. The examples are
   being moved to `3.15.0` on `ios-python-315-final`, and this default
   should probably move with them.
4. **Side observation — `run -p ios --simulator` exits 0 when the app fails
   at startup.** The log ends with `kivyforge bootstrap fatal: failed to run
   entry module "main"`, but `run` returned 0. That is arguably right, since
   `run` launched the app and the app's own failure is not kivyforge's.
   Recorded so the result is not read as a launch that worked.

No code was changed.

## Environment

| Item | Value |
|------|-------|
| Host | macOS 26.6.2 (`25G83`), arm64 |
| Xcode | 27.0 (build 27A266a) |
| Host Python | 3.14.7 |
| pip | 26.2.1 |
| kivyforge | 3.0.0.dev1, editable install in a separate worktree with its own venv (the main clone had uncommitted work on another branch, so it was not switched) |
| Simulator | iPhone Air, iOS 27.0 |
| Hermetic suite on the branch | `pytest` exit 0, coverage 94.25% (not asked for; run because this is the first macOS run of the change) |
| Scratch app | in the session scratchpad instead of `/tmp/kf190`; contents as the prompt gives them |

## Step 1 — the scratch app

`kivyforge init -p ios` → exit 0, `Added [tool.kivy] + [tool.kivy.ios] to
pyproject.toml.` Seeded `[tool.kivy.ios.python].version = "3.15.0b4"` (see
defect 3). The seeded `exclude` is `kivy-garden`, `requests`, `certifi`,
`charset-normalizer`, `idna`, `urllib3`, `docutils`, `pygments`.

## Step 2 — baseline: nothing extra excluded

`kivyforge lock -p ios --json` → **exit 1**, `ok: false`, one diagnostic:

```
KF-ERROR: pip could not resolve the iOS slice 'ios_16_0_arm64_iphoneos': no wheel for 'materialyoucolor>=3.0.3'.
  pip said:
    Collecting kivy>=3.0.0.dev0
      Downloading kivy-3.0.0.dev202610251128-cp315-cp315-ios_13_0_arm64_iphoneos.whl.metadata (14 kB)
    Collecting kivymd==2.0.0
      Downloading kivymd-2.0.0-py3-none-any.whl.metadata (16 kB)
    Collecting pillow (from kivymd==2.0.0)
      Downloading pillow-13.0.0-cp315-cp315-ios_13_0_arm64_iphoneos.whl.metadata (9.1 kB)
    INFO: pip is looking at multiple versions of kivymd to determine which version is compatible with other requirements. This could take a while.
    ERROR: Could not find a version that satisfies the requirement materialyoucolor>=3.0.3 (from kivymd) (from versions: 1.0, 1.1, 1.2.0)
    ERROR: No matching distribution found for materialyoucolor>=3.0.3
```

The first package with no iOS wheel is `materialyoucolor`. It is neither
`pycairo` nor `pillow` (defect 2).

## Step 3 — before the fix, with the culprits excluded

`exclude` gained `"pycairo"` and `"materialyoucolor"` (the prompt's snippet,
run as `python3 - pycairo materialyoucolor`). Worktree detached at
`origin/main` (`a423f475`), `pylock.ios.toml` absent.

`kivyforge lock -p ios --json` → **exit 1**, `ok: false`, `KF-ERROR`,
byte-for-byte the same message as Step 2 (`Using cached` instead of
`Downloading`): `no wheel for 'materialyoucolor>=3.0.3'`, although
`materialyoucolor` was excluded. **That is the bug, reproduced on iOS.**

## Step 4 — after the fix

Worktree back on `exclude-during-resolve` (`b02c443c`), `pylock.ios.toml`
removed.

`kivyforge lock -p ios --json` → **exit 0**:

```json
{
  "schema": 1,
  "kivyforge": "3.0.0.dev1",
  "command": "lock",
  "platform": "ios",
  "ok": true,
  "data": {
    "lockfile": "pylock.ios.toml",
    "action": "wrote",
    "in_sync": true,
    "packages": 7
  },
  "diagnostics": []
}
```

stderr: `[lock] arm64_iphoneos: resolving wheels`, `[lock]
arm64_iphonesimulator: resolving wheels`. Packages in the lock: `asyncgui`
0.6.3, `asynckivy` 0.6.4, `filetype` 1.2.0, `Kivy`
3.0.0.dev202610251128 (cp315, iphoneos + iphonesimulator), `kivymd` 2.0.0,
`materialshapes` 0.3, `pillow` 13.0.0 (cp315, both slices). **No `pycairo`, no
`materialyoucolor`**, and nothing from the seeded `exclude`. **PASS.**

`kivyforge lock -p ios --check` → `pylock.ios.toml is up to date.`, exit 0.
**PASS.**

Extra check, not in the prompt: the same app with only `pycairo` excluded
(the issue's configuration minus the `pillow` it needs on Android) still
fails on the branch, with `KF-ERROR`, `no wheel for 'materialyoucolor>=3.0.3'`.
So a name is skipped only when it is listed, as on Android.

## Step 5 — does the app run without them?

`kivyforge build -p ios --simulator` → exit 0, `Built
kf190-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/kf190.app`.

`kivyforge run -p ios --simulator --no-build` → installed and launched on the
iPhone Air simulator. Kivy and KivyMD load (`[KivyMD] 2.0.0`), the SDL3
window and ANGLE GL context come up, then:

```
 Traceback (most recent call last):
   ...
   File ".../kf190.app/app/main.py", line 1, in <module>
     from kivymd.app import MDApp
   File ".../kf190.app/pip-deps/kivymd/app.py", line 82, in <module>
     from kivymd.theming import ThemeManager
   File ".../kf190.app/pip-deps/kivymd/theming.py", line 41, in <module>
     from materialyoucolor.dislike.dislike_analyzer import DislikeAnalyzer
 ModuleNotFoundError: No module named 'materialyoucolor'
 kf190[28621:42914719] kivyforge bootstrap fatal: failed to run entry module "main"
```

No KivyMD window. `run` exited 0 (defect 4). `cairo` was never reached:
`materialshapes` is imported only by `kivymd/uix/loadingindicator`, which the
app does not use. Whether a KivyMD app runs with `pycairo` excluded stays
unanswered on iOS until `materialyoucolor` has a wheel.

## Step 6 — clean up

Scratch app and the downloaded KivyMD/materialshapes wheels (used to read
their imports) removed.
