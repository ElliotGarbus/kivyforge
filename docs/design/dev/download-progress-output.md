# Download progress output

**Status:** implemented in PR #87 (issues #84 and #74), 2026-10-05.

`lock` and `build` both do long downloads. Before this change, `lock -p android`
printed nothing until it finished, and `build` let Gradle download a missing NDK
with no progress at all. On a slow connection both looked like a hang. This
document describes what is shown now and the rules behind it.

## What the user sees

### `lock -p android`, on a terminal

One line per step, and a live bar for each download that redraws in place:

```
[lock] arm64_v8a: resolving wheels
[lock] arm64_v8a: Kivy-2.3.1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 8.9 MB / 8.9 MB 0:00:00
[lock] x86_64: resolving wheels
[lock] x86_64: Kivy-2.3.1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 9.3 MB / 9.3 MB 0:00:00
Wrote pylock.android.toml (8 packages pinned).
```

While a download is running, the bar shows the percentage, the bytes so far and
the time remaining. A finished bar stays on screen as a record.

With Maven dependencies, the Gradle step is announced, because Gradle names
nothing it downloads:

```
[lock] resolving 2 Maven dependencies with Gradle (a first run also downloads Gradle itself)
```

### The same, in a log or a pipe

No bar, since a bar in a log is a wall of redraws. Instead, a few lines per
download:

```
[lock] arm64_v8a: resolving wheels
[lock] arm64_v8a: Kivy-2.3.1  0% of 8.9 MB
[lock] arm64_v8a: Kivy-2.3.1  64% of 8.9 MB
[lock] arm64_v8a: Kivy-2.3.1  100% of 8.9 MB
```

### When nothing visible happens

After 30 seconds with nothing new to show (a slow resolve, or Gradle working
quietly), a line says the step is still alive:

```
[lock] x86_64: still resolving (1m 30s)
[lock] Gradle: still resolving (2m 00s)
```

### `build`, the first time the NDK or CMake is needed

Before any Gradle run, a missing NDK or CMake at the pinned version is installed
with the SDK's `sdkmanager`:

```
[sdk] NDK 27.3.13750724: not installed; installing it with sdkmanager
[sdk] NDK 27.3.13750724 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%  0:00:00
[sdk] NDK 27.3.13750724: installed
```

`sdkmanager` reports only a percentage, so there is no size column. When it
cannot do the install, the build says why and carries on, and Gradle installs it
as it always did:

```
[sdk] NDK 27.3.13750724: not installed, its license has not been accepted (run `sdkmanager --licenses`); Gradle will try instead.
[sdk] NDK 27.3.13750724 is not installed; Gradle will download and install it during this build. That is a large download and Gradle shows no progress for it. (Installing the Android SDK command-line tools lets kivyforge show it.)
```

The first line is for an unaccepted license, the second for no `sdkmanager` at
all.

## Rules

- **Everything here is progress, so it goes to stderr**, including under
  `--json`. stdout keeps carrying only the product: the envelope, or
  `Wrote pylock.android.toml`.
- **A bar only on a real terminal.** Lines are used whenever stderr is not a
  terminal, and under `--no-color` or `NO_COLOR`, the same rule that decides
  colour (`want_color` in `report/console.py`).
- **Lines are throttled**: the first, then every 10 percentage points, or every
  10 seconds if the transfer has moved at all, and always the last. A fast
  download gives three or four lines; a slow one keeps showing it is alive
  without flooding the log.
- **The "still" line fires after 30 seconds without visible output**, and again
  every 30 seconds after that.
- **Labels are short**: `[lock] <abi>: <package>-<version>` rather than the full
  wheel filename, and they are capped at 40 characters, cut with an ellipsis. A
  narrow terminal keeps the percentage and size in view.
- **Nothing fails because of this.** If `sdkmanager` is missing or does not
  install, the build continues. A stalled download still ends through pip's own
  15-second timeout and retries, or Gradle's; this changes what is shown, not
  when anything gives up.

## How it is built

Backends report numbers, never formatted bars, which keeps the rule that backends
do not print (AGENTS.md):

- `BuildEvents.on_transfer(label, done, total, unit)`, next to `on_progress`,
  where `unit` is `"bytes"` or `"percent"`. The Android lock builder takes the
  same two callbacks.
- `Report.transfer(...)` renders them through `report/transfers.py`: a Rich
  `Progress` on a terminal, `TransferLines` otherwise.
- The bar uses its own Rich console on the same stream. The report console sets
  `soft_wrap` for its pre-wrapped messages, which broke the live redraw in a real
  terminal, piling every frame onto one line. Progress messages printed while a
  bar is live go through the bar's console, so Rich puts them above the bar.
- The `reporting()` context stops a live bar when a verb ends, including on
  failure, so an error message is never drawn into a bar.
- Long-running tools run through `platforms/android/streaming.py`
  (`run_streaming`). It reads their output live, splits it on `\r` as well as `\n`
  (`sdkmanager` redraws with `\r`), and hands each piece to a small parser:
  - pip runs with `--progress-bar raw`, which prints `Progress <done> of <total>`
    lines even when its output is not a terminal (pip 24.1 and later; Android
    already requires 25.1);
  - `sdkmanager` prints `[====    ] 42% Downloading …`, read for the percentage.

## Not covered, and follow-ups

- **Only Android's `lock` reports progress.** The desktop and iOS lock backends
  are unchanged; `_LockOps.emits_progress` turns it on per backend.
- **Gradle's own downloads during `build`** (AGP, dependencies) are still shown
  only as Gradle's plain console prints them.
- **The kivy-mobile-wheels index could publish PEP 658 metadata.** pip would then
  read a few KB per wheel instead of downloading it, which removes most of the
  wait this output exists to explain. That is a change in that repository.
- **`sdkmanager` warns that it is deprecated** in favour of an `android sdk`
  command in recent command-line tools. It still works; switching is a follow-up.
